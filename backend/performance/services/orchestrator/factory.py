"""按 settings.ORCHESTRATOR_TYPE 选 adapter。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from django.conf import settings


@lru_cache(maxsize=1)
def get_adapter():
    """返回单例 OrchestratorAdapter。get_adapter.cache_clear() 可重置（测试用）。"""
    typ = (getattr(settings, 'ORCHESTRATOR_TYPE', 'docker') or 'docker').lower()
    if typ == 'docker':
        from .docker import DockerComposeAdapter
        compose_file = Path(
            getattr(settings, 'AGENT_COMPOSE_FILE', '')
            or (settings.BASE_DIR / 'docker-compose.dev.yml')
        )
        service = getattr(settings, 'AGENT_COMPOSE_SERVICE', 'agent')
        project = getattr(settings, 'AGENT_COMPOSE_PROJECT', None)
        return DockerComposeAdapter(
            compose_file=compose_file,
            service_name=service,
            project_name=project,
        )
    if typ == 'k8s':
        from .k8s import K8sAdapter
        return K8sAdapter(
            namespace=getattr(settings, 'AGENT_K8S_NAMESPACE', 'falcon'),
            deployment_name=getattr(settings, 'AGENT_K8S_DEPLOYMENT', 'falcon-agent'),
        )
    raise ValueError(f'unknown ORCHESTRATOR_TYPE: {typ}')
