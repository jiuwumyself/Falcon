"""
调试 InfluxDB 里某个 run_id 的 measurement schema + 关键字段值。

用法：
    ./venv/bin/python manage.py debug_run_metrics <run_id>

会打印：
    1. 所有出现的 (transaction, statut) tag 组合
    2. measurement 'jmeter' 的字段列表
    3. CUMULATED 行（transaction='all' AND statut='all'）的最新 5 个数据点
       —— 看 count / countError / pct50.0/95.0/99.0 / sb / rb 是否有值
    4. 该 run_id 累计 sum(count) / sum(countError) / sum(rb) / sum(sb)
"""
from django.core.management.base import BaseCommand

from performance.services.influxdb import get_client


class Command(BaseCommand):
    help = '诊断某个 run_id 的 InfluxDB 写入情况'

    def add_arguments(self, parser):
        parser.add_argument('run_id', type=str)

    def handle(self, *args, **opts):
        run_id = opts['run_id']
        safe_run = run_id.replace("'", "''")
        client = get_client()
        if client is None:
            self.stdout.write(self.style.ERROR('InfluxDB 客户端连不上'))
            return

        # 1. tag 组合
        self.stdout.write(self.style.MIGRATE_HEADING('=== (transaction, statut) 组合 ==='))
        q = (
            "SELECT count(\"count\") FROM \"jmeter\" "
            f"WHERE \"run_id\"='{safe_run}' "
            "GROUP BY \"transaction\", \"statut\""
        )
        try:
            for (_meas, tags), _points in client.query(q).items():
                t = (tags or {}).get('transaction', '∅')
                s = (tags or {}).get('statut', '∅')
                self.stdout.write(f'  transaction={t!r:30s} statut={s!r}')
        except Exception as e:  # noqa: BLE001
            self.stdout.write(self.style.WARNING(f'  查询失败：{e}'))

        # 2. 字段列表
        self.stdout.write(self.style.MIGRATE_HEADING('\n=== measurement jmeter 的字段 ==='))
        try:
            for r in client.query("SHOW FIELD KEYS FROM \"jmeter\"").get_points():
                self.stdout.write(f"  {r['fieldKey']:24s} ({r['fieldType']})")
        except Exception as e:  # noqa: BLE001
            self.stdout.write(self.style.WARNING(f'  查询失败：{e}'))

        # 3. CUMULATED 行最新 5 条
        self.stdout.write(self.style.MIGRATE_HEADING(
            '\n=== CUMULATED 行（transaction=all AND statut=all）最新 5 条 ==='
        ))
        cum_q = (
            "SELECT \"count\", \"countError\", \"hit\", \"rb\", \"sb\", "
            "\"pct50.0\", \"pct95.0\", \"pct99.0\" "
            f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
            "AND \"transaction\"='all' AND \"statut\"='all' "
            "ORDER BY time DESC LIMIT 5"
        )
        try:
            rows = list(client.query(cum_q).get_points())
            if not rows:
                self.stdout.write(self.style.WARNING('  无数据 —— 这条 run_id 的 CUMULATED 行没写入'))
            for r in rows:
                self.stdout.write(
                    f"  {r.get('time')} count={r.get('count')} "
                    f"countError={r.get('countError')} hit={r.get('hit')} "
                    f"rb={r.get('rb')} sb={r.get('sb')} "
                    f"p50={r.get('pct50.0')} p95={r.get('pct95.0')} p99={r.get('pct99.0')}"
                )
        except Exception as e:  # noqa: BLE001
            self.stdout.write(self.style.WARNING(f'  查询失败：{e}'))

        # 4. 累计汇总
        self.stdout.write(self.style.MIGRATE_HEADING('\n=== 累计汇总（CUMULATED 行 sum）==='))
        sum_q = (
            "SELECT sum(\"count\") AS count, sum(\"countError\") AS errs, "
            "sum(\"rb\") AS rb, sum(\"sb\") AS sb "
            f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
            "AND \"transaction\"='all' AND \"statut\"='all'"
        )
        try:
            for r in client.query(sum_q).get_points():
                self.stdout.write(
                    f"  total_count={r.get('count')} total_errors={r.get('errs')} "
                    f"total_rb={r.get('rb')} total_sb={r.get('sb')}"
                )
        except Exception as e:  # noqa: BLE001
            self.stdout.write(self.style.WARNING(f'  查询失败：{e}'))
