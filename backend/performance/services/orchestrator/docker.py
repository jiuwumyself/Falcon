"""DockerCompose 编排适配器（v1.2）。

依赖宿主上的 `docker compose` CLI。subprocess 调三个命令：
  - docker compose -f <file> ps -q <service>     列出当前 agent 容器 id
  - docker compose -f <file> up -d --scale <service>=N --no-recreate <service>   扩 / 缩
  - docker inspect <id> --format '{{.Name}} {{.State.Status}}'   查 pod_name + 状态

为什么不用 docker SDK：subprocess 形态对客户机器零额外依赖（只要装了 docker），
且 compose 文件 + service 名是用户已经熟悉的 mental model；后期换 K8s 也好对照。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import OrchestratorAdapter, OrchestratorError, PodInfo


class DockerComposeAdapter(OrchestratorAdapter):
    """基于 docker compose CLI 的实现。"""

    def __init__(
        self,
        compose_file: Path,
        service_name: str = 'agent',
        project_name: str | None = None,
    ):
        self.compose_file = Path(compose_file)
        self.service_name = service_name
        # project_name 默认 = compose 文件所在目录名（docker compose 的默认行为）
        self.project_name = project_name or self.compose_file.parent.name
        if not self.compose_file.exists():
            raise OrchestratorError(f'compose file not found: {self.compose_file}')

    # ── 内部 helper ──────────────────────────────────────────

    def _compose_cmd(self) -> list[str]:
        return [
            'docker', 'compose',
            '-f', str(self.compose_file),
            '-p', self.project_name,
        ]

    def _run(self, args: list[str], timeout: int = 60) -> str:
        cmd = self._compose_cmd() + args
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                env={**os.environ},
            )
        except FileNotFoundError as e:
            raise OrchestratorError(f'docker CLI not found: {e}')
        except subprocess.TimeoutExpired as e:
            raise OrchestratorError(f'docker compose timeout: {" ".join(cmd)}: {e}')
        if r.returncode != 0:
            raise OrchestratorError(
                f'docker compose failed (rc={r.returncode}): {r.stderr.strip()[:500]}',
            )
        return r.stdout

    # ── 接口实现 ─────────────────────────────────────────────

    def list_pods(self) -> list[PodInfo]:
        """先拿 container id 列表，逐个 docker inspect 拿 name + status。"""
        ids_out = self._run(['ps', '-q', self.service_name], timeout=15)
        ids = [x.strip() for x in ids_out.splitlines() if x.strip()]
        if not ids:
            return []
        # 一次 inspect 多个 id 拿名字 / 状态（节省 fork）
        try:
            r = subprocess.run(
                ['docker', 'inspect', '--format', '{{.Name}}|{{.State.Status}}|{{.Config.Image}}', *ids],
                capture_output=True, text=True, timeout=15,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            raise OrchestratorError(f'docker inspect: {e}')
        pods: list[PodInfo] = []
        for line in r.stdout.splitlines():
            parts = line.split('|', 2)
            if len(parts) < 2:
                continue
            name = parts[0].lstrip('/').strip()
            status = parts[1].strip()
            image = parts[2].strip() if len(parts) > 2 else ''
            pods.append(PodInfo(pod_name=name, status=status, image=image))
        return pods

    def scale_up(self, count: int) -> list[str]:
        """扩到 (current + count)。docker compose --scale 是绝对值，所以先数当前。"""
        if count <= 0:
            raise OrchestratorError(f'scale_up count must be positive, got {count}')
        current = len(self.list_pods())
        target = current + count
        # --no-recreate 让现有 agent 不被重启（保持 register id 不变）
        self._run(
            ['up', '-d', '--no-recreate', '--scale', f'{self.service_name}={target}',
             self.service_name],
            timeout=120,
        )
        new_pods = self.list_pods()
        # 假设新加的 = 末尾的 count 个（compose 按 _1 _2 ... _N 命名）
        return [p.pod_name for p in new_pods[-count:]]

    def scale_down(self, pod_names: list[str] | None = None) -> list[str]:
        """
        指定 pod_names 时逐个 docker rm；为 None 时整体 scale 到 0。
        """
        if pod_names is None:
            current = self.list_pods()
            self._run(
                ['up', '-d', '--no-recreate', '--scale', f'{self.service_name}=0',
                 self.service_name],
                timeout=60,
            )
            return [p.pod_name for p in current]

        if not pod_names:
            return []
        # 单个 pod 移除：docker rm -f <name>
        removed: list[str] = []
        for name in pod_names:
            try:
                subprocess.run(
                    ['docker', 'rm', '-f', name],
                    capture_output=True, text=True, timeout=30, check=False,
                )
                removed.append(name)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        return removed
