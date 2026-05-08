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
        'p50_ms': [],
        'p95_ms': [],
        'p99_ms': [],
        'error_rate': [],
        'error_count': [],
        'bytes_recv': [],
        'bytes_sent': [],
        'active_users': [],
    }


def _empty_totals() -> dict:
    return {
        'total_count': 0,
        'total_errors': 0,
        'total_bytes_recv': 0,
        'total_bytes_sent': 0,
    }


def query_run_realtime(run_id: str, since: datetime | None = None) -> dict:
    """
    返回结构（全空时各 series 为空 list，表示 InfluxDB 无该 run 数据）：

    {
      'overall': {'rps': [[ts_ms, val], ...], 'p50_ms': [...], 'p95_ms': [...],
                  'p99_ms': [...], 'error_rate': [...], 'error_count': [...],
                  'bytes_recv': [...], 'bytes_sent': [...], 'active_users': [...]},
      'by_tg': {'<threadName>': {同上 9 组}, ...},
      'totals': {'total_count', 'total_errors', 'total_bytes_recv', 'total_bytes_sent'},  # 累计 KPI（不带 since 过滤）
      'last_ts': '2026-04-30T12:00:00Z'  # 前端下次轮询的 since
    }

    InfluxDB 测量结构（JMeter Backend Listener 默认）：
      measurement = 'jmeter'
        fields: count, hit, error, avg, min, max, pct50.0, pct90.0, pct95.0, pct99.0,
                rb (receivedBytes), sb (sentBytes), minAT/meanAT/maxAT
        tags: application, statut(all/ok/ko), transaction, run_id, task_id

    我们查 statut='ok' + 'ko' 算 RPS / error_rate；查 transaction='all' 拿总分位
    数；分 TG 时按 transaction（实际为 threadName/sample label）切片。
    bytes 走 statut='all' 拿（每条 sample 都写 rb/sb，all 行已聚合）。
    """
    client = get_client()
    if client is None:
        return {
            'overall': _empty_series(),
            'by_tg': {},
            'totals': _empty_totals(),
            'last_ts': '',
        }

    where_time = ''
    if since is not None:
        # InfluxDB 接受 RFC3339 + 'Z' 或纳秒 epoch
        where_time = f" AND time > '{since.isoformat().replace('+00:00', 'Z')}'"

    safe_run = run_id.replace("'", "''")

    # 总览：按 transaction='all' 拿全局分位 + 按 statut 切片算 rps/error/bytes
    overall_q = (
        "SELECT mean(\"count\") AS rps, "
        "mean(\"pct50.0\") AS p50_ms, "
        "mean(\"pct95.0\") AS p95_ms, "
        "mean(\"pct99.0\") AS p99_ms, "
        "mean(\"avg\") AS avg_ms "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='all' AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s) fill(none)"
    )
    bytes_q = (
        "SELECT mean(\"rb\") AS rb, mean(\"sb\") AS sb "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='all' AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s) fill(none)"
    )
    # 失败数走 CUMULATED 行（transaction='all' AND statut='all'）的 "countError"
    # 字段。JMeter 5.6.3 InfluxdbBackendListenerClient.addCumulatedMetrics 每秒
    # 写这条行，包含 count=total / countError=failures。
    # 不要用 statut='ko' 行的 count：addMetric 在 count<=0 时直接跳过，全部成功
    # 的 run / 窗口拿不到任何点。
    err_q = (
        "SELECT sum(\"countError\") AS errors "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='all' AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s) fill(0)"
    )
    # statut='all' 行的 count 字段 = 该窗口总请求数（含失败）。
    # 不能用 statut!='all'：InfluxDB 1.x 对 tag 的 != 比较在某些索引模式下不可靠。
    total_q = (
        "SELECT sum(\"count\") AS total "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='all' AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s) fill(0)"
    )
    # 活跃用户数：JMeter Backend Listener 把 minAT/meanAT/maxAT 写在
    # transaction='internal' 行（不是 sampler 维度），且这些行 statut 字段为空。
    # 不能用 statut='all' 过滤，要按 transaction='internal' 拿。
    users_q = (
        "SELECT mean(\"maxAT\") AS active_users "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='internal'{where_time} "
        "GROUP BY time(1s) fill(none)"
    )

    overall = _empty_series()
    last_ts = ''

    try:
        # 总览查询（含 P50/P95/P99）
        for r in client.query(overall_q).get_points():
            ts = _ts_to_ms(r['time'])
            if r.get('rps') is not None:
                overall['rps'].append([ts, float(r['rps'])])
            if r.get('p50_ms') is not None:
                overall['p50_ms'].append([ts, float(r['p50_ms'])])
            if r.get('p95_ms') is not None:
                overall['p95_ms'].append([ts, float(r['p95_ms'])])
            if r.get('p99_ms') is not None:
                overall['p99_ms'].append([ts, float(r['p99_ms'])])
            last_ts = r['time']

        # 字节速率
        for r in client.query(bytes_q).get_points():
            ts = _ts_to_ms(r['time'])
            if r.get('rb') is not None:
                overall['bytes_recv'].append([ts, float(r['rb'])])
            if r.get('sb') is not None:
                overall['bytes_sent'].append([ts, float(r['sb'])])

        errors_by_ts = {
            _ts_to_ms(r['time']): float(r.get('errors') or 0)
            for r in client.query(err_q).get_points()
        }
        # 错误时间序列直接出（前端总错误曲线用）
        for ts, val in sorted(errors_by_ts.items()):
            overall['error_count'].append([ts, val])

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
        "SELECT mean(\"count\") AS rps, "
        "mean(\"pct50.0\") AS p50_ms, "
        "mean(\"pct95.0\") AS p95_ms, "
        "mean(\"pct99.0\") AS p99_ms, "
        "mean(\"rb\") AS rb, mean(\"sb\") AS sb "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"!='all' AND \"transaction\"!='internal' "
        f"AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s), \"transaction\" fill(none)"
    )
    try:
        result = client.query(by_tg_q)
        for (_measurement, tags), points in result.items():
            tx = (tags or {}).get('transaction', 'unknown')
            series = by_tg.setdefault(tx, _empty_series())
            for r in points:
                ts = _ts_to_ms(r['time'])
                if r.get('rps') is not None:
                    series['rps'].append([ts, float(r['rps'])])
                if r.get('p50_ms') is not None:
                    series['p50_ms'].append([ts, float(r['p50_ms'])])
                if r.get('p95_ms') is not None:
                    series['p95_ms'].append([ts, float(r['p95_ms'])])
                if r.get('p99_ms') is not None:
                    series['p99_ms'].append([ts, float(r['p99_ms'])])
                if r.get('rb') is not None:
                    series['bytes_recv'].append([ts, float(r['rb'])])
                if r.get('sb') is not None:
                    series['bytes_sent'].append([ts, float(r['sb'])])
    except Exception:  # noqa: BLE001
        pass

    # by_tg 的错误数：用单接口 statut='ko' 行的 count 字段（addMetric 写入；
    # 该窗口 count<=0 时不写，没失败的接口完全不出现在结果里——前端 fill(0) 也
    # 补不上，但前端 RunMetricsSeries 默认空数组，等价于 0 错误，可接受）。
    by_tg_err_q = (
        "SELECT sum(\"count\") AS errors "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"!='all' AND \"transaction\"!='internal' "
        f"AND \"statut\"='ko'{where_time} "
        "GROUP BY time(1s), \"transaction\" fill(0)"
    )
    by_tg_total_q = (
        "SELECT sum(\"count\") AS total "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"!='all' AND \"transaction\"!='internal' "
        f"AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s), \"transaction\" fill(0)"
    )
    try:
        # tx -> ts -> errors
        err_map: dict[str, dict[int, float]] = {}
        for (_meas, tags), points in client.query(by_tg_err_q).items():
            tx = (tags or {}).get('transaction', 'unknown')
            slot = err_map.setdefault(tx, {})
            for r in points:
                slot[_ts_to_ms(r['time'])] = float(r.get('errors') or 0)
        for (_meas, tags), points in client.query(by_tg_total_q).items():
            tx = (tags or {}).get('transaction', 'unknown')
            series = by_tg.setdefault(tx, _empty_series())
            tx_errs = err_map.get(tx, {})
            for r in points:
                ts = _ts_to_ms(r['time'])
                total = float(r.get('total') or 0)
                errs = tx_errs.get(ts, 0)
                rate = (errs / total * 100) if total > 0 else 0
                series['error_rate'].append([ts, rate])
                series['error_count'].append([ts, errs])
    except Exception:  # noqa: BLE001
        pass

    # 累计 KPI（永远全量算，不带 since 过滤）
    totals = _query_totals(client, safe_run)

    return {
        'overall': overall,
        'by_tg': by_tg,
        'totals': totals,
        'last_ts': last_ts,
    }


def _query_totals(client, safe_run: str) -> dict:
    """全 run 累计 KPI：总请求数 / 失败数 / 接收字节 / 发送字节。"""
    totals = _empty_totals()
    # JMeter v1 BackendListener 三种 statut 行的 count 字段含义不同：
    #   statut='all' → 该窗口总样本数
    #   statut='ok'  → 该窗口成功数
    #   statut='ko'  → 该窗口失败数
    # 用 statut='all' 直接拿总数；不能用 statut!='all'，InfluxDB 1.x 对 tag !=
    # 在某些索引模式下不可靠（用户报告过"总请求数没数据"就是踩这个）。
    total_q = (
        "SELECT sum(\"count\") AS total "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        "AND \"transaction\"='all' AND \"statut\"='all'"
    )
    err_q = (
        "SELECT sum(\"countError\") AS errors "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        "AND \"transaction\"='all' AND \"statut\"='all'"
    )
    bytes_q = (
        "SELECT sum(\"rb\") AS rb, sum(\"sb\") AS sb "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        "AND \"transaction\"='all' AND \"statut\"='all'"
    )
    try:
        for r in client.query(total_q).get_points():
            if r.get('total') is not None:
                totals['total_count'] = int(r['total'])
        for r in client.query(err_q).get_points():
            if r.get('errors') is not None:
                totals['total_errors'] = int(r['errors'])
        for r in client.query(bytes_q).get_points():
            if r.get('rb') is not None:
                totals['total_bytes_recv'] = int(r['rb'])
            if r.get('sb') is not None:
                totals['total_bytes_sent'] = int(r['sb'])
    except Exception:  # noqa: BLE001
        pass
    return totals


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
        "SELECT sum(\"countError\") AS errors "
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
            "AND \"transaction\"='all' AND \"statut\"='all' "
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
