"""zapp-server（K8s 管理网关）客户端：列集群 / 命名空间 / 某服务的实时 pod。

给 Arthas 终端「不用手填」用：前端级联选 集群→命名空间→pod，cluster_id/namespace/
container 全自动带出。登录拿 JWT、带 Authorization header、trust_env=False 绕本机代理
（同 Pinpoint：内网域名走系统代理会 502/reset）。

账号密码走环境变量 ZAPP_ACCOUNT / ZAPP_PASSWORD（写在 backend/.env，dotenv 会加载）。
"""
from __future__ import annotations

import os
import time
from typing import Any

import requests

BASE = os.getenv('ZAPP_BASE_URL', 'https://zapp-server.zhihuishu.com')
# 账号密码走 backend/.env（gitignored，不进 git）：ZAPP_ACCOUNT / ZAPP_PASSWORD
ACCOUNT = os.getenv('ZAPP_ACCOUNT', '')
PASSWORD = os.getenv('ZAPP_PASSWORD', '')

_tok: dict[str, Any] = {'v': None, 'ts': 0.0}


def is_enabled() -> bool:
    return bool(ACCOUNT and PASSWORD)


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # 绕系统代理
    return s


def _token() -> str:
    if _tok['v'] and time.time() - _tok['ts'] < 1500:
        return _tok['v']
    r = _session().post(f'{BASE}/access/user/login',
                        json={'account': ACCOUNT, 'password': PASSWORD}, timeout=10)
    r.raise_for_status()
    d = r.json().get('data')
    tok = d if isinstance(d, str) else (d or {}).get('token')
    if not tok:
        raise RuntimeError(f'zapp 登录失败: {r.json()}')
    _tok.update(v=tok, ts=time.time())
    return tok


def _get(path: str, timeout: int = 12) -> Any:
    r = _session().get(f'{BASE}/{path}', headers={'Authorization': _token()}, timeout=timeout)
    r.raise_for_status()
    body = r.json()
    return body.get('data') if isinstance(body, dict) else body


def list_clusters() -> list[dict[str, Any]]:
    """[{id, name, provider}]。"""
    data = _get('k8s/clusters') or []
    return [{'id': c.get('id'), 'name': c.get('name'), 'provider': c.get('provider')}
            for c in data if isinstance(c, dict)]


def list_namespaces(cluster_id: int | str) -> list[str]:
    data = _get(f'k8s/cluster/{cluster_id}/namespaces') or []
    out = []
    for n in data:
        if isinstance(n, str):
            out.append(n)
        elif isinstance(n, dict):
            out.append(n.get('name') or n.get('namespace') or '')
    return [x for x in out if x]


def list_deployment_pods(cluster_id: int | str, namespace: str,
                         deployment: str) -> list[dict[str, Any]]:
    """某 deployment（=服务名）的实时 pod → [{pod, namespace, containers:[name], phase}]。
    containers 过滤掉 sidecar（fluent-bit 等），把业务容器（名 = 服务）排最前。"""
    data = _get(f'k8s/cluster/{cluster_id}/namespace/{namespace}'
                f'/deployment/{deployment}/pods') or []
    sidecars = {'fluent-bit', 'fluentbit', 'istio-proxy', 'istio-init', 'POD'}
    out = []
    for p in data:
        if not isinstance(p, dict):
            continue
        names = [c.get('name') for c in (p.get('containers') or [])
                 if isinstance(c, dict) and c.get('name')]
        biz = [n for n in names if n not in sidecars]
        # 业务容器优先（名等于 deployment 的排第一）
        biz.sort(key=lambda n: (n != deployment, n))
        out.append({
            'pod': p.get('name'),
            'namespace': p.get('namespace') or namespace,
            'phase': p.get('phase'),
            'containers': biz or names,
        })
    return out
