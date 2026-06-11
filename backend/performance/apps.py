from django.apps import AppConfig


class PerformanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'performance'
    verbose_name = '性能压测'  # 后台侧边栏 app 分组名（替换 'Performance'）

    def ready(self):
        """
        Django 应用就绪钩子：在所有 app 加载完毕、服务进程启动后执行一次。

        问题背景
        --------
        Web 进程（或开发服务器）被强制重启时，正在运行的 RunExecutor 子线程随进程
        一起消亡，但 DB 中对应 TaskRun 的 status 仍停留在非终态
        （pre_checking / pending / running / cancelling）。
        这类行称为"孤儿 run"（zombie run）：
          - 前端轮询到 status=running 且 finished_at=null，计时器会一直滚动；
          - 用户点「取消」时后端找不到 executor 才能触发手动修复（被动）；
          - 新的 run 因唯一约束（unique_active_run_per_task）无法启动。

        解决方案
        --------
        服务启动时主动扫描所有孤儿 run，批量 UPDATE 为终态 failed，
        同时写入 finished_at，让前端计时器立刻定格、唯一约束得以释放。

        安全措施
        --------
        1. 先检查 performance_taskrun 表是否存在，避免首次执行 migrate 前报错
           （migrate 时 Django 也会触发 ready()，彼时表尚未建）。
        2. 捕获 OperationalError / ProgrammingError，防止数据库未就绪或表结构
           不完整时导致整个服务启动失败。
        3. 使用 .update() 单条 SQL 完成批量更新，无需逐行实例化，性能安全。
        """
        import sys
        # ⚠ 孤儿 run 清理**只在 web 服务进程**（runserver / waitress / gunicorn）启动时做。
        # 任何管理命令（migrate / shell / run_due_schedules / release_idle_agents 等）也会
        # 触发 ready()；若在那里清理，会把 web 进程里**正在跑的 run** 误标 failed——命令是
        # 独立进程，看不到 web 的 RUN_EXECUTORS，所有 active run 在它眼里都是"孤儿"。
        # 尤其定时 tick 每分钟跑一次，不 gate 就每分钟杀一次在跑的压测。
        argv = sys.argv
        is_web_server = (
            'runserver' in argv
            or any('waitress' in str(a) for a in argv)
            or any('gunicorn' in str(a) for a in argv)
            or any('uvicorn' in str(a) for a in argv)
        )
        if not is_web_server:
            return

        from django.db import connection
        from django.db.utils import OperationalError, ProgrammingError
        try:
            # 首次 migrate 前表不存在，直接跳过，避免启动报错
            if 'performance_taskrun' not in connection.introspection.table_names():
                return

            from django.utils import timezone
            from .models import TaskRun, RunStatus, ACTIVE_RUN_STATUSES

            import logging
            logger = logging.getLogger(__name__)

            # 1. 批量将所有孤儿 run（非终态）标记为 failed
            # ACTIVE_RUN_STATUSES = (pre_checking, pending, running, cancelling)
            zombie_count = TaskRun.objects.filter(
                status__in=[s.value for s in ACTIVE_RUN_STATUSES],
            ).update(
                status=RunStatus.FAILED,
                finished_at=timezone.now(),
                error_message='服务进程重启，运行中的任务被自动标记为失败（executor 线程已丢失）',
            )
            if zombie_count:
                logger.warning('startup: marked %d zombie run(s) as failed', zombie_count)

            # 2. 修复历史脏数据：终态但 finished_at=null（旧版本 views.py 漏写 finished_at 留下）
            # 前端 elapsedSec 依赖 finished_at 定格，若为 null 会持续滚动
            dirty_count = TaskRun.objects.filter(
                finished_at__isnull=True,
            ).exclude(
                status__in=[s.value for s in ACTIVE_RUN_STATUSES],
            ).update(
                finished_at=timezone.now(),
            )
            if dirty_count:
                logger.warning('startup: fixed %d run(s) with null finished_at', dirty_count)
        except (OperationalError, ProgrammingError):
            # 数据库未就绪 / 表结构不完整时静默跳过，不阻断服务启动
            pass