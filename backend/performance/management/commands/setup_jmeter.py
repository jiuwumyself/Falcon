"""
Download + install Apache JMeter into backend/jmeter/ (local dev only).

In Docker/production, bake JMeter into the image via the Dockerfile and set
JMETER_HOME instead of running this command.
"""
from django.core.management.base import BaseCommand

from performance.services.jmeter import ensure_jmeter_installed, ensure_plugins_installed


class Command(BaseCommand):
    help = '下载并安装 Apache JMeter + Step 2 需要的插件 JAR 到 backend/jmeter/'

    def handle(self, *args, **options):
        log = lambda m: self.stdout.write(m)  # noqa: E731
        try:
            home = ensure_jmeter_installed(log=log)
        except Exception as e:  # noqa: BLE001
            self.stderr.write(self.style.ERROR(f'JMeter 安装失败: {e}'))
            raise SystemExit(1)

        try:
            plugins = ensure_plugins_installed(log=log)
        except Exception as e:  # noqa: BLE001
            # Plugin install failures are non-fatal (standard TG still works)
            self.stderr.write(self.style.WARNING(f'插件安装警告: {e}'))
            plugins = []

        self.stdout.write(self.style.SUCCESS(f'OK: {home}'))
        if plugins:
            self.stdout.write(self.style.SUCCESS(f'已安装插件 {len(plugins)} 个'))
