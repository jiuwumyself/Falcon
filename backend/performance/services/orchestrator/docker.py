"""DockerCompose 编排适配器（v1.2）。

依赖宿主上的 `docker compose` CLI。subprocess 调几个命令：
  - docker compose config --services                            列出 compose 里定义的所有 service
  - docker compose ps -q <service>                              拿某 service 当前运行的容器 id
  - docker compose up -d <service> [<service>...]               启动一个或多个 service
  - docker compose up -d --scale <service>=N --no-recreate ...  单 service 多副本（兼容老用法）
  - docker inspect <id> --format '{{.Name}} {{.State.Status}}'  查 pod_name + 状态

为什么不用 docker SDK：subprocess 形态对客户机器零额外依赖（只要装了 docker），
且 compose 文件 + service 名是用户已经熟悉的 mental model；后期换 K8s 也好对照。

**v1.2 后期支持两种 compose 形态**（2026-05-13）：
  1. 老形态：1 个 service 叫 'agent'，--scale agent=N 横向扩容
  2. 新形态：多个 service 叫 'agent1' / 'agent2' / ...，每个固定 host port
适配方法 = `service_name` 参数当**前缀**匹配 compose 中实际存在的 service。
list_pods 合并所有匹配 service 的容器；scale_up 按需启动未启动的 agentN。
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
        # service_name 作前缀：'agent' 匹配 'agent' / 'agent1' / 'agent2' ... 'agentN'
        self.service_name = service_name
        # project_name 默认 = compose 文件所在目录名（docker compose 的默认行为）
        self.project_name = project_name or self.compose_file.parent.name
        if not self.compose_file.exists():
            raise OrchestratorError(f'compose file not found: {self.compose_file}')

    # ── service 发现 ────────────────────────────────────────────

    def _list_defined_services(self) -> list[str]:
        """compose config --services 列出 compose 文件里定义的所有 service，按名字排序。"""
        out = self._run(['config', '--services'], timeout=15)
        services = sorted(s.strip() for s in out.splitlines() if s.strip())
        return services

    def _matching_services(self) -> list[str]:
        """compose 中所有以 service_name 开头的 service（兼容老单 service + 新多 service）。"""
        defined = self._list_defined_services()
        prefix = self.service_name
        # 完全匹配（老形态 service='agent'）+ 前缀匹配（新形态 agent1 / agent2 ...）
        # 排序保持 agent < agent1 < agent2 ...（lexicographic 自然 OK，因为数字位数都是 1）
        matched = [s for s in defined if s == prefix or s.startswith(prefix)]
        if not matched:
            raise OrchestratorError(
                f'compose 文件 {self.compose_file.name} 里找不到任何以 "{prefix}" '
                f'开头的 service（已定义：{defined}）',
            )
        return matched

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

    def _service_running(self, service: str) -> bool:
        """该 service 当前是否有运行中的容器。"""
        out = self._run(['ps', '-q', service], timeout=15)
        return any(line.strip() for line in out.splitlines())

    def list_pods(self) -> list[PodInfo]:
        """合并所有匹配 service 的容器；对每个 service 跑 ps -q + 批量 inspect。"""
        services = self._matching_services()
        all_ids: list[str] = []
        for svc in services:
            out = self._run(['ps', '-q', svc], timeout=15)
            all_ids.extend(x.strip() for x in out.splitlines() if x.strip())
        if not all_ids:
            return []
        try:
            r = subprocess.run(
                ['docker', 'inspect', '--format',
                 '{{.Name}}|{{.State.Status}}|{{.Config.Image}}', *all_ids],
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
        """两种 compose 形态分别处理：
          - 多 service（agent1/agent2/...）：找未运行的前 N 个 up 起来；不够数报错指引
            用户改 compose 加 agentN
          - 单 service（agent）：兜底走 --scale agent=N 老路径
        """
        if count <= 0:
            raise OrchestratorError(f'scale_up count must be positive, got {count}')

        services = self._matching_services()
        # 形态判断：>1 个匹配 service 走多 service 路径；否则单 service --scale
        if len(services) > 1:
            stopped = [s for s in services if not self._service_running(s)]
            if not stopped:
                raise OrchestratorError(
                    f'已达 compose 定义上限（{len(services)} 台 service 全已启动）。'
                    f'需要更多请编辑 {self.compose_file.name} 复制 agentN 段递增端口。',
                )
            to_start = stopped[:count]
            if len(to_start) < count:
                # 部分启动，明确告诉用户
                pass  # 仍然 up，最后报告新加的实际数量
            self._run(['up', '-d', *to_start], timeout=120)
            # to_start 是 service 名，agent 自注册后才知道真实 pod_name（容器 hostname）。
            # 这里返回 service 名作占位（前端展示用，agent 几秒后 register 后会按 pod_name 在 DB 出现）
            return to_start

        # 单 service 兜底（老 compose 形态）
        single = services[0]
        current = len(self.list_pods())
        target = current + count
        self._run(
            ['up', '-d', '--no-recreate', '--scale', f'{single}={target}', single],
            timeout=120,
        )
        new_pods = self.list_pods()
        return [p.pod_name for p in new_pods[-count:]]

    def scale_down(self, pod_names: list[str] | None = None) -> list[str]:
        """
        指定 pod_names 时逐个 docker rm；为 None 时整体 scale 到 0（多 service 形态走 stop）。
        """
        if pod_names is None:
            current = self.list_pods()
            services = self._matching_services()
            if len(services) > 1:
                # 多 service：stop 全部匹配 service（保留容器定义，下次 up 还能起）
                self._run(['stop', *services], timeout=60)
            else:
                # 单 service 兜底：--scale=0
                self._run(
                    ['up', '-d', '--no-recreate', '--scale', f'{services[0]}=0',
                     services[0]],
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
