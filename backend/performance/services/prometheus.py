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

# 系统容器名黑名单：这些 container_name 值不是业务容器，不应出现在服务选择器里。
_SYSTEM_CONTAINER_NAMES = frozenset({
    '', 'POD', 'istio-proxy', 'istio-init', 'istio-validation',
    'fluent-bit', 'logtail', 'logtail-ds',
    'cmonitor-agent', 'cmonitor-plugin', 'node-exporter',
    'clearlog', 'csi-plugin', 'csi-provisioner', 'csi-fuse-ossfs',
    'ack-koordlet', 'ack-koord-manager', 'ahas-agent',
    'terway-eniip', 'kube-proxy-worker',
})


def list_jobs(base_url: str, auth_token: str = '') -> list[str]:
    """获取 Prometheus 中所有 job 名（旧接口，保留兼容）。

    对应 API: GET /api/v1/label/job/values
    返回: ["node-exporter", "cmonitor", ...]
    """
    values = _get(base_url, 'label/job/values', auth_token=auth_token)
    if isinstance(values, list):
        return sorted(values)
    return []


def list_services(base_url: str, auth_token: str = '') -> list[str]:
    """获取 Prometheus 中所有业务容器名（Step 2 服务多选下拉框）。

    优先查 container_name 标签（ali-k8s-new），为空时 fallback 查 container 标签（ali-k8s-online），
    兼容不同 ARMS 实例的 label 命名差异。
    过滤掉系统容器（POD、istio-proxy、node-exporter 等），只返回业务容器名。
    """
    for label in ('container_name', 'container'):
        values = _get(base_url, f'label/{label}/values', auth_token=auth_token)
        if isinstance(values, list) and values:
            return sorted(v for v in values if v not in _SYSTEM_CONTAINER_NAMES
                           and not v.startswith('csi-') and not v.startswith('ack-'))
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
#
# 两种模板格式：
# 1. 容器标签精确匹配（container_name / container）
#    promql 中 {label} 和 {service_name} 会被替换
#    例：{container="kg-ai-run"}
#
# 2. pod 标签正则匹配（pod）
#    promql 中 {service_name} 会被替换为 pod 前缀正则
#    例：{pod=~"kg-ai-run-.*"}

# per-pod 模板：不展开 avg 聚合，按 pod 分组，返回多条 series
# 返回结果中 metric 的 pod 标签即为 pod 名
_METRIC_TEMPLATES_PER_POD: dict[str, tuple[str, str]] = {
    'cpu_usage_by_pod': (
        'Pod CPU 使用率',
        # container 模式: {label} 被替换为 container_name 或 container
        'rate(container_cpu_usage_seconds_total{{container!="",container!="POD",{label}="{service_name}"}}[5m])'
        ' / on(pod) group_left clamp_min(container_spec_cpu_quota{{container!="",container!="POD",{label}="{service_name}"}} / 100000, 0.001)'
        ' * 100',
    ),
    'memory_usage_by_pod': (
        'Pod 内存 WSS 使用率',
        # container 模式
        'container_memory_working_set_bytes{{container!="",container!="POD",{label}="{service_name}"}}'
        ' / on(pod) group_left clamp_min(container_spec_memory_limit_bytes{{container!="",container!="POD",{label}="{service_name}"}}, 1)'
        ' * 100',
    ),
    'memory_rss_by_pod': (
        'Pod 内存 RSS 使用率',
        'container_memory_rss{{container!="",container!="POD",{label}="{service_name}"}}'
        ' / on(pod) group_left clamp_min(container_spec_memory_limit_bytes{{container!="",container!="POD",{label}="{service_name}"}}, 1)'
        ' * 100',
    ),
}

_METRIC_TEMPLATES_PER_POD_POD_MODE: dict[str, tuple[str, str]] = {
    'cpu_usage_by_pod': (
        'Pod CPU 使用率',
        # pod 模式: 用 pod=~前缀正则
        'rate(container_cpu_usage_seconds_total{{container!="",container!="POD",pod=~"{service_name}-.*"}}[5m])'
        ' / on(pod) group_left clamp_min(container_spec_cpu_quota{{container!="",container!="POD",pod=~"{service_name}-.*"}} / 100000, 0.001)'
        ' * 100',
    ),
    'memory_usage_by_pod': (
        'Pod 内存 WSS 使用率',
        'container_memory_working_set_bytes{{container!="",container!="POD",pod=~"{service_name}-.*"}}'
        ' / on(pod) group_left clamp_min(container_spec_memory_limit_bytes{{container!="",container!="POD",pod=~"{service_name}-.*"}}, 1)'
        ' * 100',
    ),
    'memory_rss_by_pod': (
        'Pod 内存 RSS 使用率',
        'container_memory_rss{{container!="",container!="POD",pod=~"{service_name}-.*"}}'
        ' / on(pod) group_left clamp_min(container_spec_memory_limit_bytes{{container!="",container!="POD",pod=~"{service_name}-.*"}}, 1)'
        ' * 100',
    ),
}

_METRIC_TEMPLATES_CONTAINER: dict[str, tuple[str, str]] = {
    'cpu_usage': (
        '微服务(容器名)整体CPU使用率(最大100%)',
        'avg(rate(container_cpu_usage_seconds_total{{container!="",container!="POD",{label}="{service_name}"}}[5m]))'  # noqa: E501
        ' / avg(clamp_min(container_spec_cpu_quota{{container!="",container!="POD",{label}="{service_name}"}}, 1)'  # noqa: E501
        '   / 100000) * 100',
    ),
    'memory_usage': (
        '微服务(容器名)整体内存 WSS 使用率(最大100%)',
        'avg(container_memory_working_set_bytes{{container!="",container!="POD",{label}="{service_name}"}}) / clamp_min(avg(container_spec_memory_limit_bytes{{container!="",container!="POD",{label}="{service_name}"}}), 1) * 100',
    ),
    'memory_rss_usage': (
        '微服务(容器名)整体内存 RSS 使用率(最大100%)',
        'avg(container_memory_rss{{container!="",container!="POD",{label}="{service_name}"}}) / clamp_min(avg(container_spec_memory_limit_bytes{{container!="",container!="POD",{label}="{service_name}"}}), 1) * 100',
    ),
    'network_rx': (
        '网络接收速率 (KB/s)',
        'avg(rate(container_network_receive_bytes_total{{pod=~"{service_name}-.*"}}[5m])) / 1024',
    ),
    'network_tx': (
        '网络发送速率 (KB/s)',
        'avg(rate(container_network_transmit_bytes_total{{pod=~"{service_name}-.*"}}[5m])) / 1024',
    ),
    'disk_read': (
        '磁盘读取速率 (KB/s)',
        'avg(rate(container_fs_reads_bytes_total{{container!="",container!="POD",{label}="{service_name}"}}[5m])) / 1024',
    ),
    'disk_write': (
        '磁盘写入速率 (KB/s)',
        'avg(rate(container_fs_writes_bytes_total{{container!="",container!="POD",{label}="{service_name}"}}[5m])) / 1024',
    ),
}

_METRIC_TEMPLATES_POD: dict[str, tuple[str, str]] = {
    'cpu_usage': (
        '微服务(容器名)整体CPU使用率(最大100%)',
        'avg(rate(container_cpu_usage_seconds_total{{container!="",container!="POD",pod=~"{service_name}-.*"}}[5m]))'  # noqa: E501
        ' / avg(clamp_min(container_spec_cpu_quota{{container!="",container!="POD",pod=~"{service_name}-.*"}}, 1)'  # noqa: E501
        '   / 100000) * 100',
    ),
    'memory_usage': (
        '微服务(容器名)整体内存 WSS 使用率(最大100%)',
        'avg(container_memory_working_set_bytes{{container!="",container!="POD",pod=~"{service_name}-.*"}}) / clamp_min(avg(container_spec_memory_limit_bytes{{container!="",container!="POD",pod=~"{service_name}-.*"}}), 1) * 100',
    ),
    'memory_rss_usage': (
        '微服务(容器名)整体内存 RSS 使用率(最大100%)',
        'avg(container_memory_rss{{container!="",container!="POD",pod=~"{service_name}-.*"}}) / clamp_min(avg(container_spec_memory_limit_bytes{{container!="",container!="POD",pod=~"{service_name}-.*"}}), 1) * 100',
    ),
    'network_rx': (
        '网络接收速率 (KB/s)',
        'avg(rate(container_network_receive_bytes_total{{pod=~"{service_name}-.*"}}[5m])) / 1024',
    ),
    'network_tx': (
        '网络发送速率 (KB/s)',
        'avg(rate(container_network_transmit_bytes_total{{pod=~"{service_name}-.*"}}[5m])) / 1024',
    ),
    'disk_read': (
        '磁盘读取速率 (KB/s)',
        'avg(rate(container_fs_reads_bytes_total{{container!="",container!="POD",pod=~"{service_name}-.*"}}[5m])) / 1024',
    ),
    'disk_write': (
        '磁盘写入速率 (KB/s)',
        'avg(rate(container_fs_writes_bytes_total{{container!="",container!="POD",pod=~"{service_name}-.*"}}[5m])) / 1024',
    ),
}

# 兼容旧引用
METRIC_TEMPLATES = _METRIC_TEMPLATES_CONTAINER


def _detect_service_label(base_url: str, auth_token: str = '') -> str:
    """探测 cAdvisor 指标中用于标识容器的标签名（带缓存 5 分钟）。

    不同 ARMS 实例的 cAdvisor 版本不同：
    - ali-k8s-new：cAdvisor 指标用 container 标签
    - ali-k8s-online：cAdvisor 指标没有 container/container_name，只有 pod 标签

    返回值：'container_name' | 'container' | 'pod'
    - container_name / container：精确匹配，PromQL 用 {label="xxx"}
    - pod：正则匹配，PromQL 用 {pod=~"xxx-.*"}
    
    缓存机制：
    - 数据源 URL 作为 cache_key，缓存 5 分钟（数据源配置极少变动）
    - 使用 Django 的 locmem 缓存，无需 Redis
    """
    from django.core.cache import cache as django_cache
    
    cache_key = f'prometheus_label:{base_url}'
    cached = django_cache.get(cache_key)
    if cached:
        return cached
    
    try:
        # 加 container!="",container!="POD" 过滤，确保只探测真实业务容器，
        # 避免 POD 级别聚合指标干扰导致误判为 pod 模式
        result = instant_query(
            base_url,
            'container_cpu_usage_seconds_total{container!="",container!="POD"}',
            auth_token=auth_token,
        )
        # 遍历多条 series 检测标签
        for series in result[:50]:
            labels = series.get('metric', {})
            if 'container_name' in labels and labels.get('container_name', '') not in ('', 'POD'):
                django_cache.set(cache_key, 'container_name', 300)
                return 'container_name'
            if 'container' in labels and labels.get('container', '') not in ('', 'POD'):
                django_cache.set(cache_key, 'container', 300)
                return 'container'
        # 所有 series 都没有 container/container_name → 用 pod 正则
        if result and 'pod' in result[0].get('metric', {}):
            django_cache.set(cache_key, 'pod', 300)
            return 'pod'
    except PrometheusAPIError:
        pass

    # instant query 失败时 fallback 到 label values API
    for label in ('container_name', 'container'):
        values = _get(base_url, f'label/{label}/values', auth_token=auth_token)
        if isinstance(values, list) and any(v not in _SYSTEM_CONTAINER_NAMES for v in values):
            django_cache.set(cache_key, label, 300)
            return label
    
    # 缓存标签探测结果（5 分钟）
    result = 'container_name'  # 兜底
    django_cache.set(cache_key, result, 300)
    return result


def _build_promql(service_name: str, label: str, template: str) -> str:
    """根据标签类型构建 PromQL。
    
    Args:
        service_name: 服务名（容器名）
        label: 'container_name' | 'container' | 'pod'
        template: PromQL 模板，含 {service_name} 和 {label} 占位符
    
    Returns:
        填充后的 PromQL 字符串
    """
    if label == 'pod':
        return template.format(service_name=service_name)
    else:
        return template.format(service_name=service_name, label=label)


def _query_single_metric(base_url: str, promql: str, start: str, end: str, 
                         step: str, auth_token: str, is_per_pod: bool) -> tuple[str, dict]:
    """查询单个指标（用于并行执行）。
    
    Returns:
        (metric_key, result_dict) 元组
    """
    try:
        series_list = range_query(base_url, promql, start, end, step, auth_token=auth_token)
    except PrometheusAPIError:
        series_list = []
    
    if is_per_pod:
        # 返回多条 series，每条以 pod 名为 key
        pods: dict[str, list] = {}
        for s in series_list:
            pod_name = s.get('metric', {}).get('pod', '')
            if not pod_name:
                continue
            raw_vals = s.get('values', [])
            pods[pod_name] = [
                {'ts': float(v[0]), 'value': float(v[1])}
                for v in raw_vals
                if len(v) >= 2
            ]
        return (promql, {
            'data': [],
            'pods': pods,
        })
    else:
        # 取第一条 series 的 values（大多数聚合查询只有一条）
        values = []
        if series_list:
            raw_vals = series_list[0].get('values', [])
            values = [
                {'ts': float(v[0]), 'value': float(v[1])}
                for v in raw_vals
                if len(v) >= 2
            ]
        return (promql, {
            'data': values,
        })


from django.conf import settings
from django.core.cache import cache as django_cache
import hashlib

def query_service_metrics(base_url: str, service_name: str,
                          start: str, end: str, step: str = '15s',
                          auth_token: str = '',
                          metric_keys: list[str] | None = None,
                          use_cache: bool = True) -> dict[str, dict]:
    """查一个服务（容器）的多项指标时序数据（支持并行查询+缓存）。

    service_name: 容器名（如 "kg-ai-run"）
    自动探测数据源 cAdvisor 指标的标签类型，选用匹配的 PromQL 模板：
    - container_name / container 标签 → 精确匹配 {label="xxx"}
    - pod 标签（无容器标签）→ 正则匹配 {pod=~"xxx-.*"}
    返回: {metric_key: {"display_name": ..., "data": [{"ts": ..., "value": ...}, ...]}}
    
    性能优化：
    - 标签探测结果缓存 5 分钟
    - 多个指标并行查询（ThreadPoolExecutor）
    - 查询结果缓存 15 秒（按 cache_key）
    - 支持 use_cache=False 强制绕过缓存（调试用）
    """
    if metric_keys is None:
        metric_keys = (
            list(_METRIC_TEMPLATES_CONTAINER.keys())
            + list(_METRIC_TEMPLATES_PER_POD.keys())
        )

    # 自动探测标签类型，选择对应模板（已缓存 5 分钟）
    label = _detect_service_label(base_url, auth_token=auth_token)
    templates = _METRIC_TEMPLATES_POD if label == 'pod' else _METRIC_TEMPLATES_CONTAINER

    # per-pod 模板选择
    per_pod_templates = (
        _METRIC_TEMPLATES_PER_POD_POD_MODE if label == 'pod'
        else _METRIC_TEMPLATES_PER_POD
    )

    # 构建查询列表（并行执行）
    queries = []
    for key in metric_keys:
        if key in per_pod_templates:
            display_name, promql_tpl = per_pod_templates[key]
            promql = _build_promql(service_name, label, promql_tpl)
            queries.append((key, display_name, promql, True))
        elif key in templates:
            display_name, promql_tpl = templates[key]
            promql = _build_promql(service_name, label, promql_tpl)
            queries.append((key, display_name, promql, False))

    # 并行查询所有指标
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    results: dict[str, dict] = {}
    
    with ThreadPoolExecutor(max_workers=min(8, len(queries))) as executor:
        future_to_key = {}
        for key, display_name, promql, is_per_pod in queries:
            # 检查缓存
            cache_key = f"prom:{hashlib.md5(f'{base_url}:{service_name}:{promql}:{start}:{end}:{step}'.encode()).hexdigest()[:16]}"
            
            if use_cache:
                cached = django_cache.get(cache_key)
                if cached is not None:
                    results[key] = {
                        'display_name': display_name,
                        **cached,
                    }
                    continue
            
            # 提交异步查询
            future = executor.submit(
                _query_single_metric, base_url, promql, start, end, step, auth_token, is_per_pod
            )
            future_to_key[future] = (key, display_name, cache_key)
        
        # 收集结果
        for future in as_completed(future_to_key):
            key, display_name, cache_key = future_to_key[future]
            try:
                promql_result, metric_data = future.result()
                # 缓存结果（15 秒）
                if use_cache:
                    ttl = getattr(settings, 'PROMETHEUS_QUERY_CACHE_TTL', 15)
                    django_cache.set(cache_key, metric_data, ttl)
                results[key] = {
                    'display_name': display_name,
                    **metric_data,
                }
            except Exception as e:
                # 查询失败，返回空结果
                results[key] = {
                    'display_name': display_name,
                    'data': [],
                }

    return results
