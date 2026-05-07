"""容器编排适配器（v1.2）。

主控通过 OrchestratorAdapter 抽象层动态扩 / 缩压力源副本：
  - DockerComposeAdapter：本地 / 单宿主机生产，subprocess 调 docker compose
  - K8sAdapter：v1.3 接入 K8s 时实现（当前仅 stub）

Adapter 不关心 LoadGenerator 模型本身——副本起来后由 agent 自调
register/heartbeat 端点把 LoadGenerator 行写到 DB。Adapter 只负责
"让宿主上多出 / 少掉 N 个 agent 容器"。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PodInfo:
    pod_name: str          # 容器 / pod 名（与 LoadGenerator.pod_name 对齐）
    status: str            # running / pending / exited / unknown
    image: str = ''


class OrchestratorAdapter(ABC):
    """容器编排适配器抽象。子类必须实现 scale_up / scale_down / list_pods。"""

    @abstractmethod
    def scale_up(self, count: int) -> list[str]:
        """扩容 count 个副本。返回新 pod_name 列表（agent 还要 ~5-15s 才会 register）。"""

    @abstractmethod
    def scale_down(self, pod_names: list[str] | None = None) -> list[str]:
        """缩容指定 pod；pod_names=None 表示全部缩到 0。返回被释放的 pod_name 列表。"""

    @abstractmethod
    def list_pods(self) -> list[PodInfo]:
        """列出当前所有 agent 容器 / pod。"""


class OrchestratorError(RuntimeError):
    """编排操作失败（docker / k8s API 调用错误）。"""


from .factory import get_adapter  # noqa: E402, F401  re-export
