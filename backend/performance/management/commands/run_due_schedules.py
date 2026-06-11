"""定时任务 tick：扫到点的 TaskSchedule，HTTP 触发 web 的 run 接口起压测。

为什么走 HTTP 而不在本命令进程直接 RunExecutor.start()：executor 用进程内
threading.Thread + 模块级 RUN_EXECUTORS dict，必须活在长驻 web 进程里；本命令是
短进程，起完线程一退就成孤儿 run。故由本命令 POST web 的 /tasks/<id>/run/，让
executor 落在 web 进程。

建议每分钟跑一次（start.sh bg loop / K8s CronJob）：
  * * * * * cd /path/to/backend && ./venv/bin/python manage.py run_due_schedules
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

import requests

from performance.models import TaskSchedule, TaskScheduleType, TaskRun


class Command(BaseCommand):
    help = '触发所有到点的定时压测任务（TaskSchedule）。'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='只列出到点的，不真触发。')

    def handle(self, *args, **opts):
        now = timezone.now()
        base_url = getattr(settings, 'FALCON_SELF_URL', 'http://localhost:8000').rstrip('/')
        due = list(TaskSchedule.objects.filter(
            enabled=True, next_run_at__isnull=False, next_run_at__lte=now,
        ).select_related('task'))

        if not due:
            self.stdout.write(f'[schedules] {now:%H:%M:%S} 无到点任务')
            return

        for s in due:
            if opts['dry_run']:
                self.stdout.write(f'[dry-run] 会触发 #{s.id} {s.name} → task {s.task_id}')
                continue
            self._trigger(s, base_url, now)

    def _trigger(self, s: TaskSchedule, base_url: str, now):
        lg_ids = list(s.load_generators.values_list('id', flat=True))
        url = f'{base_url}/api/performance/tasks/{s.task_id}/run/'
        try:
            r = requests.post(url, json={'load_generator_ids': lg_ids}, timeout=30)
        except requests.RequestException as e:
            # 连不上 web（重启中等）→ 瞬时错误，**不推进** next_run_at，下个 tick 重试
            TaskSchedule.objects.filter(pk=s.pk).update(
                last_error=f'触发失败（web 不可达）：{e}'[:500],
            )
            self.stderr.write(f'[schedules] #{s.id} {s.name} web 不可达，下次重试：{e}')
            return

        fields = {'last_triggered_at': now}
        if r.status_code == 201:
            run_id = (r.json() or {}).get('run_id')
            run = TaskRun.objects.filter(run_id=run_id).first() if run_id else None
            fields.update(last_run=run, last_error='')
            self.stdout.write(self.style.SUCCESS(
                f'[schedules] ✓ 触发 #{s.id} {s.name} → run {run_id}'))
        else:
            body = (r.text or '')[:500]
            fields['last_error'] = f'HTTP {r.status_code}: {body}'
            self.stderr.write(f'[schedules] ✗ #{s.id} {s.name} 触发被拒 HTTP {r.status_code}: {body}')

        # 推进 next_run_at：周期→下个点继续；一次性→关掉不再触发
        if s.schedule_type == TaskScheduleType.RECURRING:
            fields['next_run_at'] = s.compute_next_run(now)
        else:
            fields['next_run_at'] = None
            fields['enabled'] = False
        TaskSchedule.objects.filter(pk=s.pk).update(**fields)
