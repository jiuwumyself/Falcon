"""Prometheus HTTP API 查询封装。

支持阿里云 ARMS Prometheus 兼容 API 和标准 Prometheus。
所有方法接收数据源 URL（到 /api/v1 之前的部分），自动拼路径查询。
"""

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

# HTTP 请求超时（秒）—— Prometheus range_query 在大数据量下可能慢
_REQUEST_TIMEOUT = 30


# ── 基础 HTTP ──────────────────────────────────────────

def _get(base_url: str, path: str, params: dict | None = None,
         auth_token: str = '') -> dict[str, Any]:
    """向 Prometheus 兼容 API 发 GET 请求，返回 JSON data 部分。

    base_url: 数据源根地址（到 /api/v1 之前的部分）
    path:     /api/v1/ 之后的路径，如 'query'、'query_range'、'label/job/values'
    params:   查询参数
    auth_token: Bearer token（可选）
    """
    url = f'{base_url.rstrip("/")}/api/v1/{path.lstrip("/")}'
    headers = {}
    if auth_token:
        headers['Authorization'] = f'Bearer {auth_token}'

    try:
        resp = requests.get(url, params=params, headers=headers,
                            timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
    except requests.RequestException as exc:
        logger.warning('Prometheus API 请求失败 %s: %s', url, exc)
        raise PrometheusAPIError(f'Prometheus API 请求失败: {exc}') from exc

    if body.get('status') != 'success':
        msg = body.get('error', '') or body.get('errorType', '') or 'unknown'
        raise PrometheusAPIError(f'Prometheus 返回错误: {msg}')

    return body.get('data', {})


class PrometheusAPIError(Exception):
    """Prometheus API 调用失败时抛出。"""


# ── 服务发现 ──────────────────────────────────────────

def list_jobs(base_url: str, auth_token: str = '') -> list[str]:
    """获取 Prometheus 中所有 job 名（用于 Step 2 服务多选下拉框）。

    对应 API: GET /api/v1/label/job/values
    返回: ["node-exporter", "cmonitor", ...]
    """
    values = _get(base_url, 'label/job/values', auth_token=auth_token)
    if isinstance(values, list):
        return sorted(values)
    return []


def list_label_values(base_url: str, label: str, auth_token: str = '') -> list[str]:
    """获取指定 label 的所有值（通用版本，list_jobs 的扩展）。

    对应 API: GET /api/v1/label/{label}/values
    """
    values = _get(base_url, f'label/{label}/values', auth_token=auth_token)
    if isinstance(values, list):
        return sorted(values)
    return []


# ── 即时查询 ──────────────────────────────────────────

def instant_query(base_url: str, query: str, time: str | None = None,
                  auth_token: str = '') -> list[dict]:
    """Prometheus 即时查询（GET /api/v1/query）。

    返回 result 列表，每项含 metric dict + value[list]。
    """
    params: dict[str, Any] = {'query': query}
    if time is not None:
        params['time'] = time
    data = _get(base_url, 'query', params=params, auth_token=auth_token)
    return data.get('result', [])


# ── 范围查询 ──────────────────────────────────────────

def range_query(base_url: str, query: str,
                start: str, end: str, step: str = '15s',
                auth_token: str = '') -> list[dict]:
    """Prometheus 范围查询（GET /api/v1/query_range）。

    start/end: RFC3339 或 Unix 时间戳字符串
    step:      查询步长
    返回: result 列表，每项含 metric dict + values[list[list]]
    """
    params: dict[str, Any] = {
        'query': query,
        'start': start,
        'end': end,
        'step': step,
    }
    data = _get(base_url, 'query_range', params=params, auth_token=auth_token)
    return data.get('result', [])


# ── 预置查询模板（Step 3 面板用）────────────────────

# 每个模板 key → (display_name, promql_template)
# promql_template 中 {job} 会被替换为实际 job 名
METRIC_TEMPLATES: dict[str, tuple[str, str]] = {
    'cpu_usage': (
        'CPU 使用率 %',
        '100 - (avg by(job) (irate(node_cpu_seconds_total{{mode="idle",job="{job}"}}[5m])) * 100)',
    ),
    'memory_usage': (
        '内存使用率 %',
        '(1 - avg by(job) (node_memory_MemAvailable_bytes{{job="{job}"}}'
        ' / node_memory_MemTotal_bytes{{job="{job}"}})) * 100',
    ),
    'cpu_usage_cadvisor': (
        '容器 CPU 使用率 %',
        'sum by(container) (rate(container_cpu_usage_seconds_total{{job="{job}"}}[5m])) * 100',
    ),
    'memory_usage_cadvisor': (
        '容器内存使用 MB',
        'sum by(container) (container_memory_working_set_bytes{{job="{job}"}}) / 1024 / 1024',
    ),
}


def query_service_metrics(base_url: str, job: str,
                          start: str, end: str, step: str = '15s',
                          auth_token: str = '',
                          metric_keys: list[str] | None = None) -> dict[str, dict]:
    """查一个服务（job）的多项指标时序数据。

    返回: {metric_key: {"display_name": ..., "data": [{"ts": ..., "value": ...}, ...]}}
    """
    if metric_keys is None:
        metric_keys = list(METRIC_TEMPLATES.keys())

    results: dict[str, dict] = {}
    for key in metric_keys:
        if key not in METRIC_TEMPLATES:
            continue
        display_name, promql_tpl = METRIC_TEMPLATES[key]
        promql = promql_tpl.format(job=job)
        try:
            series = range_query(base_url, promql, start, end, step,
                                 auth_token=auth_token)
        except PrometheusAPIError:
            series = []

        # 取第一条 series 的 values（大多数聚合查询只有一条）
        values = []
        if series:
            raw_vals = series[0].get('values', [])
            values = [
                {'ts': float(v[0]), 'value': float(v[1])}
                for v in raw_vals
                if len(v) >= 2
            ]

        results[key] = {
            'display_name': display_name,
            'data': values,
        }

    return results
