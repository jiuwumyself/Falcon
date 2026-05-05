"""
InfluxDB v1.x 查询封装 —— 只读，写入由 JMeter Backend Listener 直接做。

为什么选 v1.x：JMeter 5.6.3 内置的 InfluxdbBackendListenerClient 走 v1 协议
（POST /write?db=...），InfluxDB v1.8 OSS 原生支持。v2.x 也可用 v1 兼容 API
但要额外配 DBRP mapping，运维负担更大。

写入路径：JMX 注入 BackendListener → InfluxDB measurement=jmeter，每条数据点
带 tag run_id / task_id / threadName。本模块按 run_id 切片查询。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from django.conf import settings


# influxdb 5.x 客户端是同步的；用模块级单例缓存。
_CLIENT: Any | None = None
_CLIENT_FAILED: bool = False  # 已知连不上时跳过重试，避免每次请求都 hang


def _build_client():
    """构造客户端；连接失败返 None 并记缓存。"""
    global _CLIENT, _CLIENT_FAILED
    if _CLIENT is not None:
        return _CLIENT
    if _CLIENT_FAILED:
        return None
    try:
        from influxdb import InfluxDBClient
        url = getattr(settings, 'INFLUXDB_URL', 'http://localhost:8086')
        # 解析 URL → host/port/ssl
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = parsed.hostname or 'localhost'
        port = parsed.port or (8086 if parsed.scheme != 'https' else 443)
        ssl = parsed.scheme == 'https'

        client = InfluxDBClient(
            host=host,
            port=port,
            ssl=ssl,
            username=getattr(settings, 'INFLUXDB_USER', '') or None,
            password=getattr(settings, 'INFLUXDB_PASSWORD', '') or None,
            database=getattr(settings, 'INFLUXDB_DB', 'jmeter'),
            timeout=5,
        )
        # 主动 ping 一次确认连通
        client.ping()
        _CLIENT = client
        return client
    except Exception:  # noqa: BLE001
        _CLIENT_FAILED = True
        return None


def get_client():
    """返回缓存的 InfluxDB 客户端；连不上返 None。"""
    return _build_client()


def reset_client_cache() -> None:
    """单元测试 / 配置变更后用；清掉单例缓存。"""
    global _CLIENT, _CLIENT_FAILED
    _CLIENT = None
    _CLIENT_FAILED = False


def ping() -> bool:
    """pre_check 用：InfluxDB 是否可达 + 数据库是否存在。"""
    client = get_client()
    if client is None:
        return False
    try:
        client.ping()
        # 顺便校验目标库存在
        target_db = getattr(settings, 'INFLUXDB_DB', 'jmeter')
        existing = {db['name'] for db in client.get_list_database()}
        return target_db in existing
    except Exception:  # noqa: BLE001
        return False


def _empty_series() -> dict:
    return {
        'rps': [],
        'p99_ms': [],
        'error_rate': [],
        'active_users': [],
    }


def query_run_realtime(run_id: str, since: datetime | None = None) -> dict:
    """
    返回结构（全空时各 series 为空 list，表示 InfluxDB 无该 run 数据）：

    {
      'overall': {'rps': [[ts_ms, val], ...], 'p99_ms': [...], 'error_rate': [...], 'active_users': [...]},
      'by_tg': {'<threadName>': {同上四组}, ...},
      'last_ts': '2026-04-30T12:00:00Z'  # 前端下次轮询的 since
    }

    InfluxDB 测量结构（JMeter Backend Listener 默认）：
      measurement = 'jmeter'
        fields: count, hit, error, avg, min, max, pct90.0, pct95.0, pct99.0
        tags: application, statut(all/ok/ko), transaction, run_id, task_id

    我们查 statut='ok' + 'ko' 算 RPS / error_rate；查 transaction='all' 拿总分位
    数；分 TG 时按 transaction（实际为 threadName/sample label）切片。
    """
    client = get_client()
    if client is None:
        return {'overall': _empty_series(), 'by_tg': {}, 'last_ts': ''}

    where_time = ''
    if since is not None:
        # InfluxDB 接受 RFC3339 + 'Z' 或纳秒 epoch
        where_time = f" AND time > '{since.isoformat().replace('+00:00', 'Z')}'"

    safe_run = run_id.replace("'", "''")

    # 总览：按 transaction='all' 拿全局分位 + 按 statut 切片算 rps/error
    overall_q = (
        "SELECT mean(\"count\") AS rps, mean(\"pct99.0\") AS p99_ms, "
        "mean(\"avg\") AS avg_ms "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='all' AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s) fill(none)"
    )
    err_q = (
        "SELECT sum(\"count\") AS errors "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='all' AND \"statut\"='ko'{where_time} "
        "GROUP BY time(1s) fill(0)"
    )
    total_q = (
        "SELECT sum(\"count\") AS total "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='all' AND \"statut\"!='all'{where_time} "
        "GROUP BY time(1s) fill(0)"
    )
    # 活跃用户数 (JMeter Backend Listener 输出 measurement=virtualUsers，但
    # 不同版本 measurement 名可能不同；用 events 兜底)
    users_q = (
        "SELECT mean(\"maxAT\") AS active_users "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s) fill(none)"
    )

    overall = _empty_series()
    last_ts = ''

    try:
        # 总览查询
        for r in client.query(overall_q).get_points():
            ts = _ts_to_ms(r['time'])
            if r.get('rps') is not None:
                overall['rps'].append([ts, float(r['rps'])])
            if r.get('p99_ms') is not None:
                overall['p99_ms'].append([ts, float(r['p99_ms'])])
            last_ts = r['time']

        errors_by_ts = {
            _ts_to_ms(r['time']): float(r.get('errors') or 0)
            for r in client.query(err_q).get_points()
        }
        for r in client.query(total_q).get_points():
            ts = _ts_to_ms(r['time'])
            total = float(r.get('total') or 0)
            errors = errors_by_ts.get(ts, 0)
            rate = (errors / total * 100) if total > 0 else 0
            overall['error_rate'].append([ts, rate])

        for r in client.query(users_q).get_points():
            if r.get('active_users') is not None:
                overall['active_users'].append([_ts_to_ms(r['time']), float(r['active_users'])])
    except Exception:  # noqa: BLE001
        pass

    # 按 transaction（=sample label / TG 分组）切片
    by_tg: dict[str, dict] = {}
    by_tg_q = (
        "SELECT mean(\"count\") AS rps, mean(\"pct99.0\") AS p99_ms "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"!='all' AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s), \"transaction\" fill(none)"
    )
    try:
        result = client.query(by_tg_q)
        for (measurement, tags), points in result.items():
            tx = (tags or {}).get('transaction', 'unknown')
            series = by_tg.setdefault(tx, _empty_series())
            for r in points:
                ts = _ts_to_ms(r['time'])
                if r.get('rps') is not None:
                    series['rps'].append([ts, float(r['rps'])])
                if r.get('p99_ms') is not None:
                    series['p99_ms'].append([ts, float(r['p99_ms'])])
    except Exception:  # noqa: BLE001
        pass

    return {'overall': overall, 'by_tg': by_tg, 'last_ts': last_ts}


def query_run_summary(run_id: str) -> dict:
    """
    整 run 总结：avg_rps / p99 / error_rate / total_requests。跑完后填 TaskRun 用。
    """
    client = get_client()
    if client is None:
        return {'avg_rps': 0, 'p99_ms': 0, 'error_rate': 0, 'total_requests': 0}

    safe_run = run_id.replace("'", "''")
    summary_q = (
        "SELECT sum(\"count\") AS total, mean(\"pct99.0\") AS p99_ms "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        "AND \"transaction\"='all' AND \"statut\"='all'"
    )
    err_q = (
        "SELECT sum(\"count\") AS errors "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        "AND \"transaction\"='all' AND \"statut\"='ko'"
    )
    elapsed_q = (
        "SELECT (last(time) - first(time)) AS span "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        "AND \"transaction\"='all' AND \"statut\"='all'"
    )

    summary = {'avg_rps': 0.0, 'p99_ms': 0.0, 'error_rate': 0.0, 'total_requests': 0}
    try:
        for r in client.query(summary_q).get_points():
            if r.get('total') is not None:
                summary['total_requests'] = int(r['total'])
            if r.get('p99_ms') is not None:
                summary['p99_ms'] = float(r['p99_ms'])
        errors = 0
        for r in client.query(err_q).get_points():
            if r.get('errors') is not None:
                errors = int(r['errors'])
        if summary['total_requests'] > 0:
            summary['error_rate'] = errors / summary['total_requests'] * 100

        # avg_rps：JMeter Backend Listener 报的 count 已经是每秒的请求计数；
        # 平均 = 总请求数 / 持续秒数。用 InfluxQL 拿不到 elapsed_seconds，
        # 我们改用 SHOW SERIES 风格简化：先按 1s GROUP BY 算每秒 rps 再取均值。
        rps_q = (
            "SELECT sum(\"count\") AS rps "
            f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
            "AND \"transaction\"='all' AND \"statut\"!='all' "
            "GROUP BY time(1s) fill(0)"
        )
        rps_values = [
            float(r.get('rps') or 0)
            for r in client.query(rps_q).get_points()
        ]
        rps_values = [v for v in rps_values if v > 0]
        if rps_values:
            summary['avg_rps'] = sum(rps_values) / len(rps_values)
    except Exception:  # noqa: BLE001
        pass

    return summary


def delete_run_data(run_id: str) -> bool:
    """删 InfluxDB 中对应 run_id 的全部数据点（task 软删 / 归档清理时调）。"""
    client = get_client()
    if client is None:
        return False
    safe_run = run_id.replace("'", "''")
    try:
        client.query(f"DELETE FROM \"jmeter\" WHERE \"run_id\"='{safe_run}'")
        return True
    except Exception:  # noqa: BLE001
        return False


# ── helpers ──────────────────────────────────────────────────────────────


def _ts_to_ms(iso_ts: str) -> int:
    """InfluxDB 返回的 RFC3339 时间戳 → 毫秒 epoch。"""
    # 处理 'Z' 后缀（fromisoformat 在 3.11+ 支持）
    s = iso_ts.replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(s)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return 0
