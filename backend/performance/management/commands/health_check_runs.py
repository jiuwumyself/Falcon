"""
健康检查 + 僵尸任务清理。

功能：
  1. 扫描长时间处于 cancelling 状态但未终态的任务，强制标记为 FAILED
  2. 扫描 started_at 超过 MAX_RUN_DURATION_SEC 但仍 RUNNING 的任务，强制终止
  3. 扫描 executor 注册表中已失效的任务（executor 线程已退出但状态未更新）

建议配合 systemd timer / crontab 定期执行（如每 5 分钟）：
  */5 * * * * cd /path/to/backend && ./venv/bin/python manage.py health_check_runs

可选参数：
  --dry-run: 只显示会清理的任务，不实际执行
  --minutes: cancelling 超时阈值（分钟），默认 10 分钟
  --hours: RUNNING 超时阈值（小时），默认 24 小时
"""
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from performance.models import RunStatus, TaskRun
from performance.services import executor as executor_svc


# 默认 cancelling 超时：10 分钟内 agent 应该响应 cancel
DEFAULT_CANCELLING_TIMEOUT_MINUTES = 10

# 默认 running 超时：24 小时（与 _MAX_RUN_DURATION_SEC 对齐）
DEFAULT_RUNNING_TIMEOUT_HOURS = 24


class Command(BaseCommand):
    help = 'Health check: clean up zombie tasks stuck in cancelling/running state.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='只显示会清理的任务，不实际执行',
        )
        parser.add_argument(
            '--minutes', type=int, default=None,
            help=f'cancelling 超时阈值（分钟），默认 {DEFAULT_CANCELLING_TIMEOUT_MINUTES}',
        )
        parser.add_argument(
            '--hours', type=int, default=None,
            help=f'RUNNING 超时阈值（小时），默认 {DEFAULT_RUNNING_TIMEOUT_HOURS}',
        )

    def handle(self, *args, **opts):
        dry_run = opts['dry_run']
        cancelling_minutes = opts['minutes'] or DEFAULT_CANCELLING_TIMEOUT_MINUTES
        running_hours = opts['hours'] or DEFAULT_RUNNING_TIMEOUT_HOURS

        self.stdout.write(f'=== 健康检查开始 ===')
        self.stdout.write(f'  cancelling 超时: {cancelling_minutes} 分钟')
        self.stdout.write(f'  running 超时: {running_hours} 小时')
        self.stdout.write(f'  dry_run: {dry_run}')
        self.stdout.write('')

        cleaned = 0

        # 1. 清理长时间处于 cancelling 状态的任务
        cleaned += self._cleanup_stale_cancelling(cancelling_minutes, dry_run)

        # 2. 清理长时间处于 running 状态的任务
        cleaned += self._cleanup_stale_running(running_hours, dry_run)

        # 3. 清理 executor 注册表中已失效的任务
        cleaned += self._cleanup_dead_executors(dry_run)

        self.stdout.write('')
        self.stdout.write(f'=== 健康检查完成，清理了 {cleaned} 个任务 ===')

    def _cleanup_stale_cancelling(self, minutes: int, dry_run: bool) -> int:
        """清理 cancel_requested_at 超过 minutes 分钟但仍未终态的任务。"""
        cutoff = timezone.now() - timezone.timedelta(minutes=minutes)

        stale_runs = TaskRun.objects.filter(
            status=RunStatus.CANCELLING,
            cancel_requested_at__isnull=False,
            cancel_requested_at__lt=cutoff,
        )

        count = stale_runs.count()
        if count == 0:
            self.stdout.write('  [cancelling 超时] 无')
            return 0

        self.stdout.write(f'  [cancelling 超时] 发现 {count} 个任务超过 {minutes} 分钟未响应 cancel:')

        for run in stale_runs:
            elapsed = (timezone.now() - run.cancel_requested_at).total_seconds() / 60
            self.stdout.write(f'    - {run.run_id} ({run.task.title}): 已取消 {elapsed:.1f} 分钟')

        if not dry_run:
            stale_runs.update(
                status=RunStatus.FAILED,
                error_message=f'取消请求超时（超过 {minutes} 分钟无响应），系统强制标记为失败',
                finished_at=timezone.now(),
            )
            self.stdout.write(f'    -> 已标记为 FAILED')

        return count

    def _cleanup_stale_running(self, hours: int, dry_run: bool) -> int:
        """清理 started_at 超过 hours 小时但仍 RUNNING 的任务。"""
        cutoff = timezone.now() - timezone.timedelta(hours=hours)

        stale_runs = TaskRun.objects.filter(
            status=RunStatus.RUNNING,
            started_at__isnull=False,
            started_at__lt=cutoff,
        )

        count = stale_runs.count()
        if count == 0:
            self.stdout.write('  [running 超时] 无')
            return 0

        self.stdout.write(f'  [running 超时] 发现 {count} 个任务超过 {hours} 小时仍在运行:')

        for run in stale_runs:
            elapsed_hours = (timezone.now() - run.started_at).total_seconds() / 3600
            self.stdout.write(f'    - {run.run_id} ({run.task.title}): 已运行 {elapsed_hours:.1f} 小时')

        if not dry_run:
            # 尝试获取 executor 并调用 cancel()
            for run in stale_runs:
                executor = executor_svc.get_executor(run.run_id)
                if executor:
                    self.stdout.write(f'    -> 尝试通过 executor 取消 {run.run_id}...')
                    executor.cancel()
                else:
                    # executor 不存在，直接标记为 failed
                    self.stdout.write(f'    -> executor 不存在，直接标记为 FAILED')
                    run.status = RunStatus.FAILED
                    run.error_message = f'任务运行时长超过上限（{hours}小时）且执行器已失效，系统强制标记为失败'
                    run.finished_at = timezone.now()
                    run.save(update_fields=['status', 'error_message', 'finished_at', 'updated_at'])

        return count

    def _cleanup_dead_executors(self, dry_run: bool) -> int:
        """清理 executor 注册表中状态已终态但仍在注册的任务。"""
        from performance.services.executor import RUN_EXECUTORS

        dead_runs = []

        # 获取注册表中所有 executor
        with executor_svc._REGISTRY_LOCK:
            registered_run_ids = list(executor_svc.RUN_EXECUTORS.keys())

        for run_id in registered_run_ids:
            try:
                run = TaskRun.objects.get(run_id=run_id)
                if run.is_terminal:
                    dead_runs.append(run_id)
                    self.stdout.write(
                        f'  [dead executor] {run_id} 状态={run.status} 但仍在注册表中'
                    )
            except TaskRun.DoesNotExist:
                # run 已被删除但还在注册表中
                dead_runs.append(run_id)
                self.stdout.write(f'  [dead executor] {run_id} 已不存在于数据库')

        if not dead_runs:
            self.stdout.write('  [dead executor] 无')
            return 0

        if not dry_run:
            with executor_svc._REGISTRY_LOCK:
                for run_id in dead_runs:
                    executor_svc.RUN_EXECUTORS.pop(run_id, None)
            self.stdout.write(f'    -> 已从注册表移除 {len(dead_runs)} 个 dead executor')

        return len(dead_runs)
