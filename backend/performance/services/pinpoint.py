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
