"""
Pinpoint HTTP client（v1.3 接入 v0）。

设计模式参考 `influxdb.py` —— 模块级 singleton + fail-fast cache，连不上的 client
不重复重试。所有 query 失败静默返 None / [] 不抛异常，调用方按"无数据"处理。

接入策略：
  - 客户已有 Pinpoint 平台（§ 6.1 L1 #2）；URL / token 配在 PinpointConfig admin
  - run 终态时拉一次慢 trace 列表（按 P99 阈值 filter），存 RunPinpointTrace 表
  - span tree 不存（体积大），用户点 "看 Pinpoint" 外链跳到原生界面看

API endpoint 路径（按 Pinpoint 通用约定，客户实例不一致时调整 _build_url）：
  - GET /api/transactionmetadata?applicationName=X&from=...&to=...&offset=0&limit=N
    返回 trace 列表 metadata（traceId / startTime / elapsed / exceptionType 等）
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode


# 模块级 client / 失败缓存。PinpointConfig 改了之后调 reset_client_cache。
_CONFIG_CACHE: dict[str, Any] | None = None
_FAILED: bool = False


def _load_config() -> dict[str, Any] | None:
    """从 PinpointConfig 单例拿配置；enabled=False 或 base_url 空时返 None。"""
    global _CONFIG_CACHE, _FAILED
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    if _FAILED:
        return None
    try:
        from ..models import PinpointConfig  # noqa: PLC0415
        cfg = PinpointConfig.get_config()
        if not cfg.enabled or not cfg.base_url:
            _FAILED = True  # 静默：当作不可用，别每次重试
            return None
        _CONFIG_CACHE = {
            'base_url': cfg.base_url.rstrip('/'),
            'auth_token': cfg.auth_token or '',
            'timeout': cfg.request_timeout_sec or 10,
        }
        return _CONFIG_CACHE
    except Exception:  # noqa: BLE001
        _FAILED = True
        return None


def reset_client_cache() -> None:
    """admin 改 PinpointConfig 后或单测调用，清掉模块级 cache。"""
    global _CONFIG_CACHE, _FAILED
    _CONFIG_CACHE = None
    _FAILED = False


def _headers(cfg: dict[str, Any]) -> dict[str, str]:
    h = {'Accept': 'application/json'}
    if cfg.get('auth_token'):
        h['Authorization'] = f'Bearer {cfg["auth_token"]}'
    return h


def ping() -> bool:
    """快速联通性检查；admin 配完调一次确认 base_url / token 可用。

    Pinpoint 没有标准 /health endpoint；用 GET /applications.pinpoint 探测
    （所有版本都有的应用列表页，403/200 都算"通"，连不上就当不通）。
    """
    cfg = _load_config()
    if cfg is None:
        return False
    try:
        import requests  # noqa: PLC0415
        r = requests.get(
            f'{cfg["base_url"]}/applications.pinpoint',
            headers=_headers(cfg),
            timeout=min(cfg['timeout'], 5),
        )
        return r.status_code < 500
    except Exception:  # noqa: BLE001
        return False


def query_slow_traces(
    application: str,
    from_ts: int,
    to_ts: int,
    p99_threshold_ms: int,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """
    按 application + 时间窗 query Pinpoint，filter elapsed > p99_threshold_ms 的
    trace 100% 留，常态 trace 丢弃。

    Args:
      application: Pinpoint application name（来自 Service.pinpoint_app）
      from_ts / to_ts: 毫秒 epoch
      p99_threshold_ms: 阈值，elapsed 大于此值的 trace 才留
      limit: 每个 service 最多留多少条（按 elapsed desc 排前 N）

    返回：[{trace_id, elapsed_ms, start_ts_ms, exception_type, detail_url}, ...]
    失败 / 无数据返 []。
    """
    cfg = _load_config()
    if cfg is None:
        return []

    # 实测 query 上界：按 limit×3 去拿，本地按 elapsed 排序后取前 limit
    # （Pinpoint 默认按时间排，不按 elapsed；本地 filter 后才好取慢 top-N）
    fetch_limit = max(limit * 3, 100)
    params = {
        'applicationName': application,
        'from': from_ts,
        'to': to_ts,
        'offset': 0,
        'limit': fetch_limit,
    }
    url = f'{cfg["base_url"]}/api/transactionmetadata?{urlencode(params)}'

    try:
        import requests  # noqa: PLC0415
        r = requests.get(url, headers=_headers(cfg), timeout=cfg['timeout'])
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:  # noqa: BLE001
        return []

    # Pinpoint 返回结构（不同版本字段名略有差异，这里按通用约定 + 容错）：
    #   { metadata: [{ traceId, startTime, elapsed, exceptionType, ... }, ...] }
    raw = data.get('metadata') or data.get('transactions') or []
    if not isinstance(raw, list):
        return []

    out = []
    for item in raw:
        try:
            elapsed = int(item.get('elapsed') or item.get('elapsedTime') or 0)
            if elapsed <= p99_threshold_ms:
                continue
            trace_id = str(item.get('traceId') or item.get('transactionId') or '').strip()
            if not trace_id:
                continue
            start = int(item.get('startTime') or item.get('collectorAcceptTime') or 0)
            exc = str(item.get('exceptionType') or item.get('exceptionName') or '').strip()
            # Pinpoint 详情页 URL 模式（按通用约定，带 traceId + focusTimestamp）
            detail = (
                f'{cfg["base_url"]}/transactionView?traceId={trace_id}'
                f'&focusTimestamp={start}&applicationName={application}'
            )
            out.append({
                'trace_id': trace_id,
                'elapsed_ms': elapsed,
                'start_ts_ms': start,
                'exception_type': exc,
                'detail_url': detail,
            })
        except (TypeError, ValueError):
            continue

    # elapsed desc 排序，取前 limit
    out.sort(key=lambda x: x['elapsed_ms'], reverse=True)
    return out[:limit]


# ── serverMap 服务拓扑（v1.4：链路面板拓扑图 + 依赖表）────────────────────────
# 新版 Pinpoint（React SPA + Spring Boot）REST API（实测 ppoint.zhihuishu.com）：
#   GET /api/applications → [{applicationName, serviceType, code}, ...]
#   GET /api/getServerMapDataV2?applicationName=X&serviceTypeName=Y&from=ms&to=ms
#       &calleeRange=1&callerRange=1&bidirectional=true&wasOnly=false&useStatisticsAgentState=true
#     → {applicationMapData:{nodeDataArray:[{applicationName,serviceType,totalCount,
#        errorCount,slowCount,key}], linkDataArray:[{from,to,totalCount,errorCount,
#        slowCount,responseStatistics:{Avg,Max,Sum,Tot}}]}}
# ⚠ 内网 Pinpoint 域名走宿主代理(Clash 等)会 502，这里 trust_env=False 直连。

_APP_TYPE_CACHE: dict[str, str] | None = None
_APP_CODE_CACHE: dict[str, int] = {}   # {app: serviceTypeCode}（histogram 用数字 code）


def is_enabled() -> bool:
    """PinpointConfig 是否启用且 base_url 非空。"""
    return _load_config() is not None


def base_url() -> str:
    cfg = _load_config()
    return cfg['base_url'] if cfg else ''


def _direct_session():
    """直连 session：忽略环境代理。内网 Pinpoint 走代理会 502，直连可达。"""
    import requests  # noqa: PLC0415
    s = requests.Session()
    s.trust_env = False
    return s


def list_applications() -> dict[str, str]:
    """拉 Pinpoint 应用列表 → {applicationName: serviceType}（进程级缓存）。失败返 {}。"""
    global _APP_TYPE_CACHE
    if _APP_TYPE_CACHE is not None:
        return _APP_TYPE_CACHE
    cfg = _load_config()
    if cfg is None:
        return {}
    try:
        r = _direct_session().get(
            f'{cfg["base_url"]}/api/applications',
            headers=_headers(cfg), timeout=cfg['timeout'],
        )
        if r.status_code != 200:
            return {}
        apps = r.json()
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, str] = {}
    for a in apps if isinstance(apps, list) else []:
        name, st = a.get('applicationName'), a.get('serviceType')
        if name and st:
            out[name] = st
            if a.get('code') is not None:
                _APP_CODE_CACHE[name] = int(a['code'])
    _APP_TYPE_CACHE = out
    return out


def app_service_type_code(app: str) -> int | None:
    """应用的 serviceTypeCode（数字，histogram 端点需要）。"""
    if not _APP_CODE_CACHE:
        list_applications()  # 顺手填 code 缓存
    return _APP_CODE_CACHE.get(app)


def reset_app_cache() -> None:
    global _APP_TYPE_CACHE
    _APP_TYPE_CACHE = None
    _APP_CODE_CACHE.clear()


def _parse_nodes(arr: Any) -> list[dict[str, Any]]:
    out = []
    for n in arr if isinstance(arr, list) else []:
        try:
            total = int(n.get('totalCount') or 0)
            err = int(n.get('errorCount') or 0)
            out.append({
                'key': n.get('key') or f"{n.get('applicationName')}^{n.get('serviceType')}",
                'name': n.get('applicationName') or '',
                'service_type': n.get('serviceType') or '',
                'total_count': total,
                'error_count': err,
                'slow_count': int(n.get('slowCount') or 0),
                'error_rate': round(err / total * 100, 2) if total else 0.0,
            })
        except (TypeError, ValueError):
            continue
    return out


def _parse_links(arr: Any) -> list[dict[str, Any]]:
    out = []
    for lk in arr if isinstance(arr, list) else []:
        try:
            total = int(lk.get('totalCount') or 0)
            err = int(lk.get('errorCount') or 0)
            rs = lk.get('responseStatistics') or {}
            out.append({
                'from': lk.get('from') or '',
                'to': lk.get('to') or '',
                'total_count': total,
                'error_count': err,
                'slow_count': int(lk.get('slowCount') or 0),
                'error_rate': round(err / total * 100, 2) if total else 0.0,
                'avg_ms': int(rs.get('Avg') or 0),
                'max_ms': int(rs.get('Max') or 0),
            })
        except (TypeError, ValueError):
            continue
    return out


def query_server_map(application: str, service_type: str,
                     from_ts: int, to_ts: int,
                     inbound: int = 2, outbound: int = 2) -> dict[str, list]:
    """查一个应用在 [from_ts, to_ts]（毫秒窗口）的 serverMap 拓扑。
    inbound/outbound = 上下游展开跳数（默认 2，中心服务前后各 2 层）。
    返回 {'nodes': [...], 'links': [...]}；失败 / 无数据返空。"""
    cfg = _load_config()
    if cfg is None:
        return {'nodes': [], 'links': []}
    params = {
        'applicationName': application,
        'serviceTypeName': service_type,
        'from': from_ts,
        'to': to_ts,
        'inbound': inbound,
        'outbound': outbound,
        'bidirectional': 'false',
        'wasOnly': 'false',
        'useStatisticsAgentState': 'true',
    }
    url = f'{cfg["base_url"]}/api/getServerMapDataV2?{urlencode(params)}'
    try:
        # serverMap 聚合较慢，超时放宽到 40s
        r = _direct_session().get(url, headers=_headers(cfg),
                                  timeout=max(cfg['timeout'], 40))
        if r.status_code != 200:
            return {'nodes': [], 'links': []}
        amd = (r.json() or {}).get('applicationMapData', {})
    except Exception:  # noqa: BLE001
        return {'nodes': [], 'links': []}
    return {
        'nodes': _parse_nodes(amd.get('nodeDataArray', [])),
        'links': _parse_links(amd.get('linkDataArray', [])),
    }


# ── 单服务诊断（v1.4：服务诊断 tab）─────────────────────────────────────────
# 各端点 JSON 字段已 curl 实测（ppoint.zhihuishu.com，2026-06）：
#   getResponseTimeHistogramDataV2 → {responseStatistics:{Tot,Avg,Max}, histogram:{1s,3s,5s,Slow,Error}, serverList:{pod:{instanceList:{agentId:{agentName,hasInspector}}}}}
#   uriStat/summary → [{uri,totalCount,failureCount,maxTimeMs,avgTimeMs,apdex}]
#   inspector/applicationStat/chart → {timestamp:[ms], title, metricValues:[{fieldName:MIN/AVG/MAX, valueList:[]}]}
#   getAgentList / errors/errorList/groupBy

def _get_json(path_qs: str, timeout: int | None = None):
    """GET base_url/api/<path_qs> → JSON；失败返 None。"""
    cfg = _load_config()
    if cfg is None:
        return None
    try:
        r = _direct_session().get(
            f'{cfg["base_url"]}/api/{path_qs}',
            headers=_headers(cfg), timeout=timeout or cfg['timeout'],
        )
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:  # noqa: BLE001
        return None


def query_transactions(application: str, service_type_code: int,
                       from_ts: int, to_ts: int) -> dict[str, Any]:
    """事务概览 + 响应时间分布（getResponseTimeHistogramDataV2）。
    返回 {tps,total,ok_count,error_count,error_rate,avg_ms,max_ms,histogram:[{label,count}],
          pods:[name], agents:[{agent_id,agent_name,pod}]}。"""
    d = _get_json(
        f'getResponseTimeHistogramDataV2?applicationName={application}'
        f'&serviceTypeCode={service_type_code}&from={from_ts}&to={to_ts}',
        timeout=35,
    )
    if not isinstance(d, dict):
        return {}
    rs = d.get('responseStatistics') or {}
    hg = d.get('histogram') or {}
    total = int(rs.get('Tot') or 0)
    err = int(hg.get('Error') or 0)
    # Pinpoint 标准 5 桶：1s=<1s, 3s=1~3s, 5s=3~5s, Slow=>5s, Error
    histogram = [
        {'label': '<1s', 'count': int(hg.get('1s') or 0)},
        {'label': '1~3s', 'count': int(hg.get('3s') or 0)},
        {'label': '3~5s', 'count': int(hg.get('5s') or 0)},
        {'label': '>5s', 'count': int(hg.get('Slow') or 0)},
        {'label': '错误', 'count': err},
    ]
    win_sec = max(1, (to_ts - from_ts) / 1000)
    pods, agents = [], []
    for pod_name, pod in (d.get('serverList') or {}).items():
        pods.append(pod_name)
        for aid, inst in (pod.get('instanceList') or {}).items():
            agents.append({'agent_id': aid, 'agent_name': inst.get('agentName') or aid,
                           'pod': pod_name})
    return {
        'tps': round(total / win_sec, 1),
        'total': total,
        'ok_count': total - err,
        'error_count': err,
        'error_rate': round(err / total * 100, 2) if total else 0.0,
        'avg_ms': int(rs.get('Avg') or 0),
        'max_ms': int(rs.get('Max') or 0),
        'histogram': histogram,
        'pods': pods,
        'agents': agents,
    }


def query_inspector_chart(application: str, metric_id: str,
                          from_ts: int, to_ts: int) -> dict[str, Any]:
    """inspector 应用级时序（一个 metricDefinitionId）→ {title, avg, max, last,
    series:[[ts,avg_val]]}。metric_id ∈ transaction/activeTrace/dataSource/heap/... 。"""
    d = _get_json(
        f'inspector/applicationStat/chart?applicationName={application}'
        f'&metricDefinitionId={metric_id}&from={from_ts}&to={to_ts}',
        timeout=25,
    )
    if not isinstance(d, dict):
        return {}
    ts = d.get('timestamp') or []
    by_field = {mv.get('fieldName'): (mv.get('valueList') or [])
                for mv in (d.get('metricValues') or []) if isinstance(mv, dict)}
    avg_vals = by_field.get('AVG') or by_field.get('SUM') or []
    max_vals = by_field.get('MAX') or avg_vals

    def _clean(vals):
        return [v for v in vals if isinstance(v, (int, float)) and v >= 0]
    avg_clean, max_clean = _clean(avg_vals), _clean(max_vals)
    series = [[ts[i], avg_vals[i]] for i in range(min(len(ts), len(avg_vals)))
              if isinstance(avg_vals[i], (int, float)) and avg_vals[i] >= 0]
    return {
        'title': d.get('title') or metric_id,
        'avg': round(sum(avg_clean) / len(avg_clean), 1) if avg_clean else 0,
        'max': round(max(max_clean), 1) if max_clean else 0,
        'last': round(avg_clean[-1], 1) if avg_clean else 0,
        'series': series,
    }


def query_agent_gc(application: str, agent_id: str,
                   from_ts: int, to_ts: int) -> dict[str, Any]:
    """agent 级 heap 指标里带 gcOldCount / gcOldTime（应用级 inspector 没有这俩字段，
    所以 GC 只能在 agent 级拿）→ 区间内 Old GC 次数 / 耗时 + 稀疏时序（只在发生 GC 的点有值）。
    gcOldCount 按桶 delta 累加（Pinpoint agent stat 每采样间隔上报本区间内的 GC 增量）。
    """
    d = _get_json(
        f'inspector/agentStat/chart?applicationName={application}&agentId={agent_id}'
        f'&metricDefinitionId=heap&from={from_ts}&to={to_ts}',
        timeout=20,
    )
    empty = {'old_count': 0, 'old_time_ms': 0, 'series': []}
    if not isinstance(d, dict):
        return empty
    ts = d.get('timestamp') or []
    by_field = {mv.get('fieldName'): (mv.get('valueList') or [])
                for mv in (d.get('metricValues') or []) if isinstance(mv, dict)}
    counts = by_field.get('gcOldCount') or []
    times = by_field.get('gcOldTime') or []
    total_c = total_t = 0.0
    series: list[list] = []
    for i in range(min(len(ts), len(counts))):
        c = counts[i]
        if isinstance(c, (int, float)) and c > 0:
            total_c += c
            series.append([ts[i], c])
        t = times[i] if i < len(times) else None
        if isinstance(t, (int, float)) and t > 0:
            total_t += t
    return {'old_count': int(total_c), 'old_time_ms': int(total_t), 'series': series}


def query_slow_uris(application: str, from_ts: int, to_ts: int,
                    count: int = 6, orderby: str = 'avgTimeMs') -> list[dict[str, Any]]:
    """慢 URL top-N（uriStat/summary）→ [{uri,avg_ms,max_ms,count,failure_count}]。"""
    d = _get_json(
        f'uriStat/summary?applicationName={application}&from={from_ts}&to={to_ts}'
        f'&orderby={orderby}&isDesc=true&count={count}',
    )
    if not isinstance(d, list):
        return []
    out = []
    for u in d:
        try:
            out.append({
                'uri': u.get('uri') or '',
                'avg_ms': round(float(u.get('avgTimeMs') or 0), 1),
                'max_ms': round(float(u.get('maxTimeMs') or 0), 1),
                'count': int(float(u.get('totalCount') or 0)),
                'failure_count': int(float(u.get('failureCount') or 0)),
            })
        except (TypeError, ValueError):
            continue
    # API 的 count 参数有时不生效，本地按 orderby（默认 avgTimeMs desc）取前 N
    out.sort(key=lambda x: x['avg_ms'], reverse=True)
    return out[:count]


def query_error_groups(application: str, from_ts: int, to_ts: int,
                       limit: int = 6) -> list[dict[str, Any]]:
    """Top 异常分组（errors/errorList/groupBy by Error Class Name）→
    [{exception_class, count}]。无错误返 []。"""
    from urllib.parse import quote  # noqa: PLC0415
    d = _get_json(
        f'errors/errorList/groupBy?applicationName={application}'
        f'&from={from_ts}&to={to_ts}&groupBy={quote("Error Class Name")}',
        timeout=20,
    )
    if not isinstance(d, list):
        return []
    out = []
    for e in d:
        if not isinstance(e, dict):
            continue
        name = (e.get('groupedFieldName') or e.get('errorClassName')
                or e.get('name') or e.get('value') or '')
        cnt = int(e.get('count') or e.get('totalCount') or 0)
        if name:
            out.append({'exception_class': str(name), 'count': cnt})
    out.sort(key=lambda x: x['count'], reverse=True)
    return out[:limit]


def query_agent_list(application: str, from_ts: int, to_ts: int) -> list[dict[str, Any]]:
    """应用的 agent 列表（getAgentList）→ [{agent_id, agent_name, hostname}]。
    Arthas 选择器 / 线程 dump 用。"""
    d = _get_json(f'getAgentList?application={application}&from={from_ts}&to={to_ts}')
    out: list[dict[str, Any]] = []
    # 返回常见两种形态：{groupName:[{agentId,agentName,hostName}]} 或 [{...}]
    items: list = []
    if isinstance(d, dict):
        for v in d.values():
            if isinstance(v, list):
                items.extend(v)
    elif isinstance(d, list):
        items = d
    seen = set()
    for a in items:
        if not isinstance(a, dict):
            continue
        aid = a.get('agentId') or a.get('agentName') or ''
        if not aid or aid in seen:
            continue
        seen.add(aid)
        out.append({
            'agent_id': aid,
            'agent_name': a.get('agentName') or aid,
            'hostname': a.get('hostName') or a.get('hostname') or '',
        })
    return out
