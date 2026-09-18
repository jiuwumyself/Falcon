"""缺 hosts 映射时的候选 IP 推荐 + 校验。

为什么不能"全自动查 IP"：主控 pod 自己也解析不了这些内网域名（实测 ppoint /
api-exp-platform-* 在 pod 里都是 Name or service not known），平台没有可用的
解析源。但主控**能用 IP + Host 头去探测**——上次正是靠这个方法发现环境里
配的 120.55.144.100 其实不服务该域名（HTTPS 落到默认 vhost 返回 openresty 404），
而 121.40.157.158 才是对的。

所以这里做的是"推荐 + 校验"而不是"自动发现"：
  1. 候选来自已有数据（同环境其它条目的 IP、别的环境里同域名的条目）
  2. 逐个用 Host 头探测，带回真实状态码
  3. 按可信度排序，前端让用户一键加入
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests
import urllib3

# 用 IP + Host 头探测时证书 SNI 必然对不上，verify=False 是刻意的；
# 关掉 urllib3 的 InsecureRequestWarning，免得刷满日志。
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_TIMEOUT = 4
_IP_RE = re.compile(r'^\d{1,3}(?:\.\d{1,3}){3}$')


def _session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # 绕系统代理，同 pinpoint/zapp
    return s


def _probe_one(ip: str, domain: str, scheme: str, path: str) -> dict[str, Any]:
    """用 Host 头打一次，带回状态码。连不上返回 ok=False + 原因。"""
    url = f'{scheme}://{ip}{path if path.startswith("/") else "/" + path}'
    try:
        r = _session().get(
            url, headers={'Host': domain}, timeout=_TIMEOUT,
            verify=False, allow_redirects=False,
        )
        return {'scheme': scheme, 'status': r.status_code, 'ok': True}
    except Exception as e:  # noqa: BLE001
        return {'scheme': scheme, 'status': None, 'ok': False,
                'error': f'{type(e).__name__}'}


def _confidence(results: list[dict]) -> tuple[str, str]:
    """把多次探测结果归纳成 (置信度, 人话说明)。

    判读依据（对齐实际踩过的坑）：
      2xx/3xx → 该 IP 确实在服务这个域名
      401/403 → 站点在，只是要鉴权，同样算可用
      404     → 有 HTTP 响应但很可能落到了默认 vhost（IP 配错的典型表现）
      连不上   → 不可用
    """
    oks = [r for r in results if r.get('ok')]
    if not oks:
        return 'unreachable', '连不上（网络不通或该 IP 不监听）'
    codes = [r['status'] for r in oks]
    if any(200 <= c < 400 for c in codes):
        return 'good', f'正常响应 {min(c for c in codes if 200 <= c < 400)}'
    if any(c in (401, 403) for c in codes):
        return 'good', '返回鉴权错误（站点存在，需要凭据）'
    if all(c == 404 for c in codes):
        return 'doubtful', '只返回 404 —— 可能落到了默认 vhost，该 IP 未必服务此域名'
    return 'doubtful', f'返回 {codes[0]}'


_RANK = {'good': 0, 'doubtful': 1, 'unreachable': 2}


def suggest_for_domains(
    domains: list[str],
    candidate_ips: list[tuple[str, str]],
    sample_paths: dict[str, tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """为每个域名探测候选 IP。

    candidate_ips: [(ip, 来源说明)]，调用方从已有 Environment 条目里收集。
    sample_paths:  {domain: (scheme, path)}，用脚本里真实的接口路径去探，比打根路径
                   更能区分"站点在不在"（根路径经常是 404/403 反而看不出）。
    """
    sample_paths = sample_paths or {}
    out: list[dict[str, Any]] = []
    jobs: list[tuple[str, str, str, str, str]] = []
    for domain in domains:
        scheme, path = sample_paths.get(domain, ('https', '/'))
        for ip, source in candidate_ips:
            if not _IP_RE.match(ip):
                continue
            jobs.append((domain, ip, source, scheme, path))

    results: dict[tuple[str, str], list[dict]] = {}
    if jobs:
        with ThreadPoolExecutor(max_workers=min(8, len(jobs) * 2)) as ex:
            futs = {}
            for domain, ip, _src, scheme, path in jobs:
                # 两种协议都试：脚本用 https，但有些内网站点只开 http
                for sch in dict.fromkeys([scheme, 'http']):
                    futs[ex.submit(_probe_one, ip, domain, sch, path)] = (domain, ip)
            for f, key in futs.items():
                try:
                    results.setdefault(key, []).append(f.result(timeout=_TIMEOUT + 2))
                except Exception:  # noqa: BLE001
                    results.setdefault(key, []).append({'ok': False, 'status': None})

    for domain in domains:
        cands = []
        for ip, source in candidate_ips:
            if not _IP_RE.match(ip):
                continue
            level, note = _confidence(results.get((domain, ip), []))
            cands.append({'ip': ip, 'source': source, 'confidence': level, 'note': note})
        cands.sort(key=lambda c: _RANK.get(c['confidence'], 9))
        scheme, path = sample_paths.get(domain, ('https', '/'))
        out.append({'domain': domain, 'probe_path': f'{scheme}://<ip>{path}',
                    'candidates': cands})
    return out
