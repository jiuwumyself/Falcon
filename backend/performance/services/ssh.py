"""SSH 型压力机的公共 SSH helper（executor 跑压测 + load-generators ssh-refresh 端点共用）。

密码走本机凭据文件 settings.SSH_PASSWORD_FILE（默认 ~/.ssh/.lgpw，一行密码 chmod 600），
不在 DB 存明文；同密码的多台机器共用此文件。用 sshpass -f <file> 连。
传输全走 ssh（base64 管道推文件，免 scp，兼容只放行 ssh 端口的环境）。
"""
from __future__ import annotations

import base64
import os.path
import subprocess

from django.conf import settings


def _pw_file() -> str:
    return os.path.expanduser(getattr(settings, 'SSH_PASSWORD_FILE', '~/.ssh/.lgpw'))


def ssh_base(lg) -> list[str]:
    """sshpass + ssh 前缀（不含远端命令）。lg 需有 ssh_user/ssh_port/ip。"""
    return [
        'sshpass', '-f', _pw_file(),
        'ssh', '-p', str(lg.ssh_port or 22),
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=/dev/null',
        '-o', 'ConnectTimeout=15',
        f'{lg.ssh_user or "root"}@{lg.ip}',
    ]


def ssh_run(lg, remote_cmd: str, *, timeout: int = 60,
            input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    """在远端跑一条命令（阻塞）。返回 CompletedProcess（stdout/stderr bytes + returncode）。"""
    cmd = ssh_base(lg) + [remote_cmd]
    return subprocess.run(
        cmd, input=input_bytes,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=timeout,
    )


def ssh_push(lg, remote_path: str, data: bytes, *, timeout: int = 120) -> None:
    """把 bytes 写到远端文件（base64 管道，免 scp）。"""
    b64 = base64.b64encode(data)
    r = ssh_run(lg, f'base64 -d > {remote_path}', timeout=timeout, input_bytes=b64)
    if r.returncode != 0:
        raise RuntimeError(f'推送 {remote_path} 失败: {r.stderr.decode("utf-8", "ignore")[:300]}')


def reverse_tunnel_cmd(lg, local_port: int, remote_port: int,
                       forward_host: str = 'localhost') -> list[str]:
    """主控起常驻反向隧道用的 argv：box 的 localhost:remote_port → 转发到（从 SSH 客户端
    =主控 pod 视角的）forward_host:local_port。
    `-N` 只转发不跑命令；`-o ExitOnForwardFailure=yes` 端口占用时立刻退（不静默假活）；
    keepalive 让长 run 期间隧道不被中间设备掐。Popen 起，用完 terminate。

    forward_host：单机 dev 时 InfluxDB 在主控 localhost → 'localhost'；K8s 时 InfluxDB 是
    独立 service（后端 pod 的 localhost 没有它）→ 传 InfluxDB 的 service DNS（如
    falcon-influxdb），否则 SSH 压力机实时 Trends 在 K8s 下转发到空地址断掉。"""
    return ssh_base(lg)[:-1] + [
        '-N',
        '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ServerAliveInterval=15',
        '-o', 'ServerAliveCountMax=4',
        '-R', f'{remote_port}:{forward_host}:{local_port}',
        ssh_base(lg)[-1],  # user@ip 放最后
    ]
