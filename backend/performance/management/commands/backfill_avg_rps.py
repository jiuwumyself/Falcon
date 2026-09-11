"""把历史 TaskRun 里虚高的 avg_rps 按 JTL 重算（一次性修数据用）。

背景：2026-09 之前 avg_rps 走 InfluxDB，把「一个上报周期（默认 5s）的累计请求数」
当成「每秒速率」求平均，恒定虚高一个上报间隔的倍数。修复只对新 run 生效，
已入库的历史值仍然是错的，用这个命令回填。

用法：
  ./venv/bin/python manage.py backfill_avg_rps --dry-run     # 只看要改什么
  ./venv/bin/python manage.py backfill_avg_rps               # 实际写库
  ./venv/bin/python manage.py backfill_avg_rps --run-id xxx  # 只修一个

JTL 已被保留策略清掉的 run 无法重算，会跳过并计数（原值保留，不置空——
置空会让历史报告更难看懂）。
"""
from django.core.management.base import BaseCommand

from performance.models import TaskRun
from performance.services.executor import _summarize_jtl
from performance.services.jmeter import get_run_dir


class Command(BaseCommand):
    help = '按 JTL 重算历史 run 的 avg_rps（修 InfluxDB 口径错误导致的虚高）'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='只打印不写库')
        parser.add_argument('--run-id', help='只处理指定 run_id')
        parser.add_argument('--threshold', type=float, default=0.05,
                            help='相对差异超过该比例才更新（默认 0.05 = 5%%）')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        qs = TaskRun.all_objects.all() if hasattr(TaskRun, 'all_objects') else TaskRun.objects.all()
        if opts.get('run_id'):
            qs = qs.filter(run_id=opts['run_id'])
        qs = qs.exclude(avg_rps__isnull=True).order_by('-created_at')

        fixed = skipped_no_jtl = unchanged = 0
        for run in qs:
            jtl = get_run_dir(run.run_id) / 'results.jtl'
            if not jtl.exists() or jtl.stat().st_size == 0:
                skipped_no_jtl += 1
                continue
            summary = _summarize_jtl(jtl)
            new_rps = summary.get('avg_rps') or 0
            old_rps = run.avg_rps or 0
            if new_rps <= 0:
                skipped_no_jtl += 1
                continue
            if old_rps > 0 and abs(new_rps - old_rps) / old_rps < opts['threshold']:
                unchanged += 1
                continue
            ratio = (old_rps / new_rps) if new_rps else 0
            self.stdout.write(
                f'  {run.run_id}  {old_rps:9.1f} → {new_rps:8.1f} rps'
                f'  (原值是真值的 {ratio:.1f} 倍)',
            )
            if not dry:
                run.avg_rps = new_rps
                run.save(update_fields=['avg_rps'])
            fixed += 1

        self.stdout.write(self.style.SUCCESS(
            f'\n{"[dry-run] 将" if dry else "已"}修正 {fixed} 条；'
            f'{unchanged} 条本来就对；{skipped_no_jtl} 条因 JTL 已清理无法重算（保留原值）',
        ))
