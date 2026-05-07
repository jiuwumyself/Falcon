"""K8s 编排适配器（v1.3 接入；当前仅 stub）。

预期实现：
  - scale_up：调 AppsV1Api.patch_namespaced_deployment_scale 增 replicas
  - scale_down：同上减 replicas，或按 pod 名 delete
  - list_pods：CoreV1Api.list_namespaced_pod label_selector="app=falcon-agent"
"""
from __future__ import annotations

from . import OrchestratorAdapter, OrchestratorError, PodInfo


class K8sAdapter(OrchestratorAdapter):
    """v1.3 待实现。"""

    def __init__(self, namespace: str = 'falcon', deployment_name: str = 'falcon-agent'):
        self.namespace = namespace
        self.deployment_name = deployment_name

    def scale_up(self, count: int) -> list[str]:
        raise NotImplementedError(
            'K8sAdapter v1.3 接入。当前请用 ORCHESTRATOR_TYPE=docker。',
        )

    def scale_down(self, pod_names: list[str] | None = None) -> list[str]:
        raise NotImplementedError(
            'K8sAdapter v1.3 接入。当前请用 ORCHESTRATOR_TYPE=docker。',
        )

    def list_pods(self) -> list[PodInfo]:
        raise NotImplementedError(
            'K8sAdapter v1.3 接入。当前请用 ORCHESTRATOR_TYPE=docker。',
        )
