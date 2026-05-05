"""
建立 Falcon Step 3 需要的 InfluxDB 库和保留策略。幂等。

用法（Mac/Linux）：
  ./venv/bin/python manage.py setup_influxdb

前置：先起 InfluxDB（docker compose -f backend/docker-compose.dev.yml up -d）。
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = '建 / 校验 Falcon Step 3 需要的 InfluxDB 库 + 保留策略（幂等）'

    def handle(self, *args, **options):
        try:
            from influxdb import InfluxDBClient
        except ImportError:
            raise CommandError(
                "缺少 influxdb 库。先 pip install -r requirements.txt"
            )

        url = getattr(settings, 'INFLUXDB_URL', 'http://localhost:8086')
        db_name = getattr(settings, 'INFLUXDB_DB', 'jmeter')
        retention = getattr(settings, 'INFLUXDB_RETENTION', '30d')

        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.hostname or 'localhost'
        port = parsed.port or (8086 if parsed.scheme != 'https' else 443)
        ssl = parsed.scheme == 'https'

        self.stdout.write(f'连接 InfluxDB: {url}')
        client = InfluxDBClient(
            host=host, port=port, ssl=ssl,
            username=getattr(settings, 'INFLUXDB_USER', '') or None,
            password=getattr(settings, 'INFLUXDB_PASSWORD', '') or None,
            timeout=5,
        )
        try:
            client.ping()
        except Exception as e:
            raise CommandError(
                f'InfluxDB ping 失败 ({e})。先确认服务已起：\n'
                f'  docker compose -f backend/docker-compose.dev.yml up -d'
            )

        existing = {db['name'] for db in client.get_list_database()}
        if db_name in existing:
            self.stdout.write(self.style.SUCCESS(f'✅ 库 {db_name} 已存在'))
        else:
            client.create_database(db_name)
            self.stdout.write(self.style.SUCCESS(f'✅ 已创建库 {db_name}'))

        client.switch_database(db_name)
        rps = client.get_list_retention_policies(database=db_name)
        rp_name = 'falcon_default'
        if any(rp['name'] == rp_name for rp in rps):
            client.alter_retention_policy(
                rp_name, database=db_name, duration=retention,
                replication=1, default=True,
            )
            self.stdout.write(self.style.SUCCESS(
                f'✅ 保留策略 {rp_name} 已存在，已更新为 {retention}'
            ))
        else:
            client.create_retention_policy(
                rp_name, retention, '1', database=db_name, default=True,
            )
            self.stdout.write(self.style.SUCCESS(
                f'✅ 已创建保留策略 {rp_name} ({retention})'
            ))

        self.stdout.write(self.style.SUCCESS('\nInfluxDB 配置就绪。'))
