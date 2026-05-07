"""
扫 last_heartbeat_at >= IDLE_RELEASE_MINUTES 分钟前 + status=idle 的 LoadGenerator，
调编排适配器 scale_down 释放容器，DB 行标 LOST。

建议外接 systemd timer / crontab 每 5 min 跑一次：
  */5 * * * * cd /path/to/backend && ./venv/bin/python manage.py release_idle_agents
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from performance.models import LoadGenerator, LoadGeneratorStatus
from performance.services.orchestrator import OrchestratorError, get_adapter


class Command(BaseCommand):
    help = 'Release idle load generators that have been idle ≥ IDLE_RELEASE_MINUTES.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--minutes', type=int, default=None,
            help='Override settings.IDLE_RELEASE_MINUTES.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='只列出会释放的，不真调适配器。',
        )

    def handle(self, *args, **opts):
        minutes = opts['minutes'] or getattr(settings, 'IDLE_RELEASE_MINUTES', 30)
        cutoff = timezone.now() - timedelta(minutes=minutes)
        qs = LoadGenerator.objects.filter(
            status=LoadGeneratorStatus.IDLE,
            last_heartbeat_at__lte=cutoff,
        )
        targets = list(qs.values_list('pod_name', flat=True))
        if not targets:
            self.stdout.write('no idle agents to release.')
            return

        self.stdout.write(f'releasing {len(targets)} idle agents (>{minutes}min): {targets}')
        if opts['dry_run']:
            self.stdout.write('--dry-run, skip actual scale_down.')
            return

        try:
            adapter = get_adapter()
            removed = adapter.scale_down(targets)
        except (OrchestratorError, NotImplementedError) as e:
            self.stderr.write(f'orchestrator error: {e}')
            return

        LoadGenerator.objects.filter(pod_name__in=removed).update(
            status=LoadGeneratorStatus.LOST,
            released_at=timezone.now(),
        )
        self.stdout.write(f'released: {removed}')
