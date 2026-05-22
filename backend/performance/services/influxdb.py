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
        # P0 #2：OK/KO 拆双轨——overall 的分位数包含 KO 样本（401/403 快速返回会把
        # 业务真实延迟分布拉低）。给 AI 喂数据时要看 OK 单独的分布。
        'p50_ok_ms': [],
        'p95_ok_ms': [],
        'p99_ok_ms': [],
        'p50_ko_ms': [],
        'p95_ko_ms': [],
        'p99_ko_ms': [],
        'error_rate': [],
        'error_count': [],
        'bytes_recv': [],
        'bytes_sent': [],
        # OK-only bytes：NetworkChart 剔除失败样本 toggle 用；同分位数策略不拆 KO
        'bytes_recv_ok': [],
        'bytes_sent_ok': [],
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
      'by_host': {'<pod_name>': {同上 9 组}, ...},  # v1.2 多机切线，单机时只有 1 个 key
      'totals': {'total_count', 'total_errors', 'total_bytes_recv', 'total_bytes_sent'},  # 累计 KPI（不带 since 过滤）
      'last_ts': '2026-04-30T12:00:00Z'  # 前端下次轮询的 since
    }

    InfluxDB 测量结构（JMeter Backend Listener 默认）：
      measurement = 'jmeter'
        fields: count, hit, error, avg, min, max, pct50.0, pct90.0, pct95.0, pct99.0,
                rb (receivedBytes), sb (sentBytes), minAT/meanAT/maxAT
        tags: application, statut(all/ok/ko), transaction, run_id, task_id, host (v1.2)

    我们查 statut='ok' + 'ko' 算 RPS / error_rate；查 transaction='all' 拿总分位
    数；分 TG 时按 transaction（实际为 threadName/sample label）切片。
    bytes 走 statut='all' 拿（每条 sample 都写 rb/sb，all 行已聚合）。

    多 host 聚合策略（v1.2）：
      - count / rb / sb / maxAT 用 sum 跨 host 加总（多机正确性，单机 sum=值不变）
      - p50/p95/p99 用 mean 跨 host 平均（per-host 分位数无法直接 sum；JMeter-Influx
        业界惯例。要严格全局分位数得拉原始 sample，超出 InfluxDB 数据粒度）
    """
    client = get_client()
    if client is None:
        return {
            'overall': _empty_series(),
            'by_tg': {},
            'by_sampler': {},
            'by_sampler_by_tg': {},
            'sampler_thread_group': {},
            'by_host': {},
            'totals': _empty_totals(),
            'totals_by_tg': {},
            'last_ts': '',
        }

    where_time = ''
    if since is not None:
        # InfluxDB 接受 RFC3339 + 'Z' 或纳秒 epoch
        where_time = f" AND time > '{since.isoformat().replace('+00:00', 'Z')}'"

    safe_run = run_id.replace("'", "''")

    # 总览：按 transaction='all' 拿全局分位 + 按 statut 切片算 rps/error/bytes
    # 多 host 聚合：count / rb / sb / maxAT 用 sum（每秒每 host 一行 → 跨 host
    # 加总）；分位数用 mean（per-host p99 不能 sum，按业界惯例平均近似）。
    overall_q = (
        "SELECT sum(\"count\") AS rps, "
        "mean(\"pct50.0\") AS p50_ms, "
        "mean(\"pct95.0\") AS p95_ms, "
        "mean(\"pct99.0\") AS p99_ms, "
        "mean(\"avg\") AS avg_ms "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='all' AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s) fill(none)"
    )
    bytes_q = (
        "SELECT sum(\"rb\") AS rb, sum(\"sb\") AS sb "
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
    # 活跃用户数：JMeter Backend Listener 在 transaction='internal' 行写 maxAT。
    # **重要**：单进程多 listener 时 maxAT 是 JMeter 全局 active thread count
    # （ThreadCounts.getActiveThreadCount 共享 context），各 listener 写出来都一样 →
    # sum(maxAT) 会把同一全局值加 N 倍（N=listener 数=enabled TG 数）。
    # 实测：21 个总线程，3 TG → 三个 listener 每条 maxAT=21，sum=63。
    # 修法：每 host 取 max（去 listener 重复）→ Python 端跨 host sum（多机时各跑自己一部分）。
    users_per_host_q = (
        "SELECT max(\"maxAT\") AS users_per_host "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='internal'{where_time} "
        "GROUP BY time(1s), \"host\" fill(none)"
    )

    # P0 #2：OK / KO 单独的分位数查询——业务侧 sample（success=true）vs 失败 sample
    # 各自 P99 分布，AI 分析用 OK 才能看出真实业务延迟分布。
    # 注意：JMeter BackendListener 只对 statut='all' 写 transaction='all' 的累计行；
    # statut='ok' / 'ko' 没有 transaction='all' 聚合，每个 sampler 单独写一行。
    # 故这里去掉 transaction='all' 过滤 + 排除 internal，跨 sampler 取 mean 近似全局
    # OK / KO p99（不是数学严格的全局 p99，是 JMeter-Influx 的天然限制）。
    # 字节用 sum（跨 sampler 可加），延迟分位用 mean（跨 sampler 只能近似，JMeter
    # 没有 transaction='all' AND statut='ok' 的预聚合行；详见本函数 226 行注释）。
    # 早期 rb/sb 也用 mean 是 bug：3 个 OK sampler 字节率 63+4.4+5.4=73 KB/s 被算成
    # 均值 24.3，剔除失败后 network 'all' 线缩水成真值的 ~1/N。
    overall_ok_q = (
        "SELECT mean(\"pct50.0\") AS p50_ok_ms, "
        "mean(\"pct95.0\") AS p95_ok_ms, "
        "mean(\"pct99.0\") AS p99_ok_ms, "
        "sum(\"rb\") AS rb_ok, sum(\"sb\") AS sb_ok "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"!='internal' AND \"statut\"='ok'{where_time} "
        "GROUP BY time(1s) fill(none)"
    )
    overall_ko_q = (
        "SELECT mean(\"pct50.0\") AS p50_ko_ms, "
        "mean(\"pct95.0\") AS p95_ko_ms, "
        "mean(\"pct99.0\") AS p99_ko_ms "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"!='internal' AND \"statut\"='ko'{where_time} "
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

        # OK 单独分位数 + OK 字节速率（剔除 KO 样本，给 AI 看真实业务延迟 / 网络流量）
        for r in client.query(overall_ok_q).get_points():
            ts = _ts_to_ms(r['time'])
            if r.get('p50_ok_ms') is not None:
                overall['p50_ok_ms'].append([ts, float(r['p50_ok_ms'])])
            if r.get('p95_ok_ms') is not None:
                overall['p95_ok_ms'].append([ts, float(r['p95_ok_ms'])])
            if r.get('p99_ok_ms') is not None:
                overall['p99_ok_ms'].append([ts, float(r['p99_ok_ms'])])
            if r.get('rb_ok') is not None:
                overall['bytes_recv_ok'].append([ts, float(r['rb_ok'])])
            if r.get('sb_ok') is not None:
                overall['bytes_sent_ok'].append([ts, float(r['sb_ok'])])

        # KO 单独分位数（看错误样本的延迟特征——快速 4xx 还是慢超时）
        for r in client.query(overall_ko_q).get_points():
            ts = _ts_to_ms(r['time'])
            if r.get('p50_ko_ms') is not None:
                overall['p50_ko_ms'].append([ts, float(r['p50_ko_ms'])])
            if r.get('p95_ko_ms') is not None:
                overall['p95_ko_ms'].append([ts, float(r['p95_ko_ms'])])
            if r.get('p99_ko_ms') is not None:
                overall['p99_ko_ms'].append([ts, float(r['p99_ko_ms'])])

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

        # 跨 host sum（同 host 内 listener 重复已被 max 去重）
        ts_bucket: dict[int, float] = {}
        for (_meas, _tags), points in client.query(users_per_host_q).items():
            for r in points:
                if r.get('users_per_host') is None:
                    continue
                ts = _ts_to_ms(r['time'])
                ts_bucket[ts] = ts_bucket.get(ts, 0) + float(r['users_per_host'])
        overall['active_users'] = sorted([[ts, v] for ts, v in ts_bucket.items()])
    except Exception:  # noqa: BLE001
        pass

    # 按 thread_group（真 TG 名）切片。jmx._inject_backend_listener_per_tg 给每个
    # 启用的 TG 各注入一个 listener，附加 TAG_thread_group=<TG name>。每个 listener
    # 写 transaction='all' 那条行的 count/分位数 = 该 TG 内所有 sampler 的合计 →
    # 这里直接吃 transaction='all' + GROUP BY thread_group，得到 TG 级聚合
    # （而不是 sample label 级别 —— 那会把一个 TG 内 N 个 sampler 切成 N 条 chip）。
    by_tg: dict[str, dict] = {}
    by_tg_q = (
        "SELECT mean(\"count\") AS rps, "
        "mean(\"pct50.0\") AS p50_ms, "
        "mean(\"pct95.0\") AS p95_ms, "
        "mean(\"pct99.0\") AS p99_ms, "
        "mean(\"rb\") AS rb, mean(\"sb\") AS sb "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='all' AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s), \"thread_group\" fill(none)"
    )
    try:
        result = client.query(by_tg_q)
        for (_measurement, tags), points in result.items():
            tg = (tags or {}).get('thread_group') or ''
            if not tg:
                continue  # 旧 run 没 thread_group tag 的合计行（transaction='all'）会被这里跳过
            series = by_tg.setdefault(tg, _empty_series())
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

    # by_tg 的 OK-only 分位 + OK 字节速率（statut='ok' 切片）——
    # LatencyChart / NetworkChart 剔除失败样本 toggle 用。
    # ⚠ 不能用 transaction='all'：JMeter Backend Listener 只对 statut='all' 写
    # transaction='all' 聚合行，statut='ok'/'ko' 每个 sampler 单独写一行。
    # 故跨 sampler 取 mean 近似 TG 级 OK p99（不是数学严格的全局 p99，是
    # JMeter-Influx 的天然限制；同 overall_ok_q 同款 workaround）。
    # 字节 sum（TG 内跨 sampler 可加），分位 mean（同 overall_ok_q 限制）
    by_tg_ok_q = (
        "SELECT mean(\"pct50.0\") AS p50_ok_ms, "
        "mean(\"pct95.0\") AS p95_ok_ms, "
        "mean(\"pct99.0\") AS p99_ok_ms, "
        "sum(\"rb\") AS rb_ok, sum(\"sb\") AS sb_ok "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"!='all' AND \"transaction\"!='internal' "
        f"AND \"statut\"='ok'{where_time} "
        "GROUP BY time(1s), \"thread_group\" fill(none)"
    )
    try:
        for (_meas, tags), points in client.query(by_tg_ok_q).items():
            tg = (tags or {}).get('thread_group') or ''
            if not tg:
                continue
            series = by_tg.setdefault(tg, _empty_series())
            for r in points:
                ts = _ts_to_ms(r['time'])
                if r.get('p50_ok_ms') is not None:
                    series['p50_ok_ms'].append([ts, float(r['p50_ok_ms'])])
                if r.get('p95_ok_ms') is not None:
                    series['p95_ok_ms'].append([ts, float(r['p95_ok_ms'])])
                if r.get('p99_ok_ms') is not None:
                    series['p99_ok_ms'].append([ts, float(r['p99_ok_ms'])])
                if r.get('rb_ok') is not None:
                    series['bytes_recv_ok'].append([ts, float(r['rb_ok'])])
                if r.get('sb_ok') is not None:
                    series['bytes_sent_ok'].append([ts, float(r['sb_ok'])])
    except Exception:  # noqa: BLE001
        pass

    # by_tg 错误数 + error_rate：用 cumulated 'all' 行的 countError 字段。
    # 之前用 statut='ko' 拿不到数据——JMeter 对 cumulated（transaction='all'）行
    # **只写 statut='all'**，包含 count=total + countError=failures；没有 'ko' 的 cumulated 行。
    # 实测 dump：该 query 能拿到 578/95/0 三 TG 的累计错误数。
    by_tg_err_q = (
        "SELECT sum(\"countError\") AS errors "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='all' AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s), \"thread_group\" fill(0)"
    )
    by_tg_total_q = (
        "SELECT sum(\"count\") AS total "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='all' AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s), \"thread_group\" fill(0)"
    )
    try:
        err_map: dict[str, dict[int, float]] = {}
        for (_meas, tags), points in client.query(by_tg_err_q).items():
            tg = (tags or {}).get('thread_group') or ''
            if not tg:
                continue
            slot = err_map.setdefault(tg, {})
            for r in points:
                slot[_ts_to_ms(r['time'])] = float(r.get('errors') or 0)
        for (_meas, tags), points in client.query(by_tg_total_q).items():
            tg = (tags or {}).get('thread_group') or ''
            if not tg:
                continue
            series = by_tg.setdefault(tg, _empty_series())
            tg_errs = err_map.get(tg, {})
            for r in points:
                ts = _ts_to_ms(r['time'])
                total = float(r.get('total') or 0)
                errs = tg_errs.get(ts, 0)
                rate = (errs / total * 100) if total > 0 else 0
                series['error_rate'].append([ts, rate])
                series['error_count'].append([ts, errs])
    except Exception:  # noqa: BLE001
        pass

    # **不再查 per-TG active_users**：实测 InfluxDB 内 transaction='internal' 行
    # 即使带 thread_group tag，maxAT 也是 JMeter 全局值（ThreadCounts 共享 context）。
    # 三个 listener 都写同样 21（全局活跃），按 thread_group GROUP BY 拿到的还是 21
    # 而不是该 TG 自己分摊的线程数。
    # → per-TG 并发改前端按 task.thread_groups_config_snapshot 的配置静态填一条水平线，
    #   并加小字提示「计划值（per-TG 实测不可拆）」。

    # 按 sample label（接口）切片：趋势曲线 hero 区想看到接口级别多线（哪个接口慢、
    # 哪个接口出错）。两份聚合 + 一份映射，配合前端 effectiveTrendSplit 三种场景：
    #   1. by_sampler  → 全部模式（不分 TG）：只按 transaction GROUP BY，同名 sampler
    #      跨 TG 时 count/bytes mean 合一（旧版双维 GROUP BY 会让同 ts 出多点 → 折线
    #      渲染异常，这里顺手修掉）
    #   2. by_sampler_by_tg → 切 TG 模式：按 (transaction, thread_group) 双维 GROUP BY，
    #      lookup [label][tg] 拿到该 TG 内该接口的真实切片
    #   3. sampler_thread_group → label → 所属 TG 名列表，KpiBar 切 TG 后前端按
    #      includes(tg) 过滤哪些 sampler 显示
    # 实测：用户 jmx 里"基准测试_学生端"和"压力拐点测试_学生端"两个 TG 共享相同
    # 4 个 sample label（登录-学生端 / 当前班级任务列表-学生端 等）。这是 2026-05-17
    # 修复："切 TG 后趋势图仍显示全部数据"的根因。
    by_sampler: dict[str, dict] = {}
    by_sampler_by_tg: dict[str, dict[str, dict]] = {}
    sampler_thread_group: dict[str, list[str]] = {}
    # — 全部模式聚合：单维 GROUP BY transaction，同 ts 一条值
    by_sampler_q = (
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
        for (_meas, tags), points in client.query(by_sampler_q).items():
            tx = (tags or {}).get('transaction') or ''
            if not tx:
                continue
            series = by_sampler.setdefault(tx, _empty_series())
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
    # — by_sampler 错误数：statut='ko' 行 per-sampler count
    # 没这查询时 RpsChart 剔除失败样本会退到 scaleByErrorRate(rps, overall.error_rate)，
    # 把整体错误率（如 25%）无差别砍到每个 sampler——100% 失败的 sampler 没被剔完，
    # 0% 失败的 sampler 反被误砍 25%。前端 1 接口全错时所有接口都缩水即此原因。
    by_sampler_err_q = (
        "SELECT sum(\"count\") AS errors "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"!='all' AND \"transaction\"!='internal' "
        f"AND \"statut\"='ko'{where_time} "
        "GROUP BY time(1s), \"transaction\" fill(none)"
    )
    try:
        for (_meas, tags), points in client.query(by_sampler_err_q).items():
            tx = (tags or {}).get('transaction') or ''
            if not tx:
                continue
            series = by_sampler.setdefault(tx, _empty_series())
            for r in points:
                ts = _ts_to_ms(r['time'])
                errs = r.get('errors')
                if errs is not None and errs > 0:
                    series['error_count'].append([ts, float(errs)])
    except Exception:  # noqa: BLE001
        pass

    # — by_sampler OK 切片：LatencyChart / NetworkChart 全部模式剔除失败样本 toggle 用
    by_sampler_ok_q = (
        "SELECT mean(\"pct50.0\") AS p50_ok_ms, "
        "mean(\"pct95.0\") AS p95_ok_ms, "
        "mean(\"pct99.0\") AS p99_ok_ms, "
        "mean(\"rb\") AS rb_ok, mean(\"sb\") AS sb_ok "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"!='all' AND \"transaction\"!='internal' "
        f"AND \"statut\"='ok'{where_time} "
        "GROUP BY time(1s), \"transaction\" fill(none)"
    )
    try:
        for (_meas, tags), points in client.query(by_sampler_ok_q).items():
            tx = (tags or {}).get('transaction') or ''
            if not tx:
                continue
            series = by_sampler.setdefault(tx, _empty_series())
            for r in points:
                ts = _ts_to_ms(r['time'])
                if r.get('p50_ok_ms') is not None:
                    series['p50_ok_ms'].append([ts, float(r['p50_ok_ms'])])
                if r.get('p95_ok_ms') is not None:
                    series['p95_ok_ms'].append([ts, float(r['p95_ok_ms'])])
                if r.get('p99_ok_ms') is not None:
                    series['p99_ok_ms'].append([ts, float(r['p99_ok_ms'])])
                if r.get('rb_ok') is not None:
                    series['bytes_recv_ok'].append([ts, float(r['rb_ok'])])
                if r.get('sb_ok') is not None:
                    series['bytes_sent_ok'].append([ts, float(r['sb_ok'])])
    except Exception:  # noqa: BLE001
        pass
    # — 切 TG 模式聚合：双维 GROUP BY (transaction, thread_group)，同时落 sampler→TG 映射
    by_sampler_by_tg_q = (
        "SELECT mean(\"count\") AS rps, "
        "mean(\"pct50.0\") AS p50_ms, "
        "mean(\"pct95.0\") AS p95_ms, "
        "mean(\"pct99.0\") AS p99_ms, "
        "mean(\"rb\") AS rb, mean(\"sb\") AS sb "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"!='all' AND \"transaction\"!='internal' "
        f"AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s), \"transaction\", \"thread_group\" fill(none)"
    )
    try:
        for (_meas, tags), points in client.query(by_sampler_by_tg_q).items():
            tx = (tags or {}).get('transaction') or ''
            tg = (tags or {}).get('thread_group') or ''
            if not tx or not tg:
                continue
            tg_list = sampler_thread_group.setdefault(tx, [])
            if tg not in tg_list:
                tg_list.append(tg)
            series = by_sampler_by_tg.setdefault(tx, {}).setdefault(tg, _empty_series())
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
    # — by_sampler_by_tg 错误数：切 TG 模式 RpsChart 剔除失败样本要 per-(sampler,TG) error_count
    by_sampler_by_tg_err_q = (
        "SELECT sum(\"count\") AS errors "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"!='all' AND \"transaction\"!='internal' "
        f"AND \"statut\"='ko'{where_time} "
        "GROUP BY time(1s), \"transaction\", \"thread_group\" fill(none)"
    )
    try:
        for (_meas, tags), points in client.query(by_sampler_by_tg_err_q).items():
            tx = (tags or {}).get('transaction') or ''
            tg = (tags or {}).get('thread_group') or ''
            if not tx or not tg:
                continue
            series = by_sampler_by_tg.setdefault(tx, {}).setdefault(tg, _empty_series())
            for r in points:
                ts = _ts_to_ms(r['time'])
                errs = r.get('errors')
                if errs is not None and errs > 0:
                    series['error_count'].append([ts, float(errs)])
    except Exception:  # noqa: BLE001
        pass

    # — by_sampler_by_tg OK 切片：切 TG 模式下 LatencyChart / NetworkChart 剔除失败 toggle 用
    by_sampler_by_tg_ok_q = (
        "SELECT mean(\"pct50.0\") AS p50_ok_ms, "
        "mean(\"pct95.0\") AS p95_ok_ms, "
        "mean(\"pct99.0\") AS p99_ok_ms, "
        "mean(\"rb\") AS rb_ok, mean(\"sb\") AS sb_ok "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"!='all' AND \"transaction\"!='internal' "
        f"AND \"statut\"='ok'{where_time} "
        "GROUP BY time(1s), \"transaction\", \"thread_group\" fill(none)"
    )
    try:
        for (_meas, tags), points in client.query(by_sampler_by_tg_ok_q).items():
            tx = (tags or {}).get('transaction') or ''
            tg = (tags or {}).get('thread_group') or ''
            if not tx or not tg:
                continue
            series = by_sampler_by_tg.setdefault(tx, {}).setdefault(tg, _empty_series())
            for r in points:
                ts = _ts_to_ms(r['time'])
                if r.get('p50_ok_ms') is not None:
                    series['p50_ok_ms'].append([ts, float(r['p50_ok_ms'])])
                if r.get('p95_ok_ms') is not None:
                    series['p95_ok_ms'].append([ts, float(r['p95_ok_ms'])])
                if r.get('p99_ok_ms') is not None:
                    series['p99_ok_ms'].append([ts, float(r['p99_ok_ms'])])
                if r.get('rb_ok') is not None:
                    series['bytes_recv_ok'].append([ts, float(r['rb_ok'])])
                if r.get('sb_ok') is not None:
                    series['bytes_sent_ok'].append([ts, float(r['sb_ok'])])
    except Exception:  # noqa: BLE001
        pass

    # 按 host（v1.2 多机）切片。单机时 by_host 只有 1 个 key（agent pod_name），
    # 多机时每台 agent 一组曲线 → 前端可叠加 / 切线对比。
    # 单 host 维度内：count/rb/sb 不再跨 host 加总，所以用 sum (host) ≡ host 自己的值；
    # 分位数 mean 也是 host 自己（每秒一条数据）。
    by_host: dict[str, dict] = {}
    by_host_main_q = (
        "SELECT sum(\"count\") AS rps, "
        "mean(\"pct50.0\") AS p50_ms, "
        "mean(\"pct95.0\") AS p95_ms, "
        "mean(\"pct99.0\") AS p99_ms, "
        "sum(\"rb\") AS rb, sum(\"sb\") AS sb "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='all' AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s), \"host\" fill(none)"
    )
    by_host_users_q = (
        # 多 listener 重复写同一全局 maxAT，必须 max() 去重（不能 sum）。
        "SELECT max(\"maxAT\") AS active_users "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='internal'{where_time} "
        "GROUP BY time(1s), \"host\" fill(none)"
    )
    by_host_err_q = (
        "SELECT sum(\"countError\") AS errors "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='all' AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s), \"host\" fill(0)"
    )
    by_host_total_q = (
        "SELECT sum(\"count\") AS total "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='all' AND \"statut\"='all'{where_time} "
        "GROUP BY time(1s), \"host\" fill(0)"
    )
    try:
        for (_meas, tags), points in client.query(by_host_main_q).items():
            host = (tags or {}).get('host') or 'unknown'
            series = by_host.setdefault(host, _empty_series())
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
        for (_meas, tags), points in client.query(by_host_users_q).items():
            host = (tags or {}).get('host') or 'unknown'
            series = by_host.setdefault(host, _empty_series())
            for r in points:
                if r.get('active_users') is not None:
                    series['active_users'].append(
                        [_ts_to_ms(r['time']), float(r['active_users'])],
                    )
        # error_rate / error_count by host：与 by_tg 同样的 host→ts→errors 中转
        host_err_map: dict[str, dict[int, float]] = {}
        for (_meas, tags), points in client.query(by_host_err_q).items():
            host = (tags or {}).get('host') or 'unknown'
            slot = host_err_map.setdefault(host, {})
            for r in points:
                slot[_ts_to_ms(r['time'])] = float(r.get('errors') or 0)
        for (_meas, tags), points in client.query(by_host_total_q).items():
            host = (tags or {}).get('host') or 'unknown'
            series = by_host.setdefault(host, _empty_series())
            host_errs = host_err_map.get(host, {})
            for r in points:
                ts = _ts_to_ms(r['time'])
                total = float(r.get('total') or 0)
                errs = host_errs.get(ts, 0)
                rate = (errs / total * 100) if total > 0 else 0
                series['error_rate'].append([ts, rate])
                series['error_count'].append([ts, errs])
    except Exception:  # noqa: BLE001
        pass

    # 累计 KPI（永远全量算，不带 since 过滤）
    totals = _query_totals(client, safe_run)
    totals_by_tg = _query_totals_by_tg(client, safe_run)

    # —— 单位归一：JMeter InfluxdbBackendListenerClient 默认 5s flush 一次，每条记录的
    # count/rb/sb 是过去 5 秒**累计值**，不是 per-second 速率。但 chart 标签是 "req/s"
    # 和 "KB/s"，直接展示会读高 ~5 倍（target_rps=5/s × 4 sampler = 20/s，原始查询
    # 返回 ~94，÷5s 才是 19/s 对得上）。这里按 overall.rps 时间戳中位间隔自适应除掉
    # flush 窗口，让 rps / bytes_recv / bytes_sent / error_count 真正变成 per-second。
    flush_sec = _detect_flush_window_sec(overall.get('rps') or [])
    if flush_sec > 1.5:   # ≤ 1s 无需归一（已是 per-second）
        _normalize_rates(overall, flush_sec)
        for s in by_tg.values():
            _normalize_rates(s, flush_sec)
        for s in by_sampler.values():
            _normalize_rates(s, flush_sec)
        for per_tg in by_sampler_by_tg.values():
            for s in per_tg.values():
                _normalize_rates(s, flush_sec)
        for s in by_host.values():
            _normalize_rates(s, flush_sec)

    return {
        'overall': overall,
        'by_tg': by_tg,
        'by_sampler': by_sampler,
        'by_sampler_by_tg': by_sampler_by_tg,
        'sampler_thread_group': sampler_thread_group,
        'by_host': by_host,
        'totals': totals,
        'totals_by_tg': totals_by_tg,
        'last_ts': last_ts,
    }


# —— 把每个 series 的"per-flush 累计"字段除以 flush_sec 改成 per-second 速率 ——
# 影响 rps（→ req/s）/ bytes_recv,bytes_sent,*_ok（→ B/s）/ error_count（→ err/s）。
# 不动 percentile（延迟天然非速率）、active_users（峰值并发本身就不是速率）、
# error_rate（百分比本身已无量纲）。
_RATE_FIELDS = (
    'rps',
    'bytes_recv', 'bytes_sent',
    'bytes_recv_ok', 'bytes_sent_ok',
    'error_count',
)


def _normalize_rates(series: dict, flush_sec: float) -> None:
    """in-place 把累计字段除以 flush_sec，转成 per-second 速率"""
    if flush_sec <= 0:
        return
    for k in _RATE_FIELDS:
        arr = series.get(k)
        if not arr:
            continue
        series[k] = [[ts, v / flush_sec] for ts, v in arr]


def _detect_flush_window_sec(rps_points: list) -> float:
    """根据 overall.rps 时间戳的中位间隔猜 JMeter 实际 flush 周期（秒）。
    默认 5s（JMeter InfluxdbBackendListenerClient.SEND_INTERVAL 默认值）。"""
    if not rps_points or len(rps_points) < 2:
        return 5.0
    deltas = []
    prev = rps_points[0][0]
    for ts, _ in rps_points[1:]:
        d = (ts - prev) / 1000.0
        if d > 0:
            deltas.append(d)
        prev = ts
    if not deltas:
        return 5.0
    deltas.sort()
    return deltas[len(deltas) // 2]


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


def _query_totals_by_tg(client, safe_run: str) -> dict:
    """按 thread_group（真 TG 名）切片的累计 KPI。

    返回 {tg_name: {total_count, total_errors, total_bytes_recv, total_bytes_sent}}
    key 跟 by_tg series 完全对齐（前端 KpiBar chip 切换时直接 lookup）。
    用 listener 的 transaction='all', statut='all' 那条合计行的 count/countError/rb/sb
    —— 它本身就是这个 TG（这个 listener）的全部 sample 累计，GROUP BY thread_group 一次取齐。
    """
    out: dict[str, dict] = {}
    q = (
        "SELECT sum(\"count\") AS total, sum(\"countError\") AS errors, "
        "sum(\"rb\") AS rb, sum(\"sb\") AS sb "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        "AND \"statut\"='all' AND \"transaction\"='all' "
        "GROUP BY \"thread_group\""
    )
    try:
        rs = client.query(q)
        for (_meas, tags), points in rs.items():
            tg = (tags or {}).get('thread_group') or ''
            if not tg:
                continue  # 旧 run（没 thread_group tag）跳过；新 run 每条都带
            for r in points:
                t = _empty_totals()
                if r.get('total') is not None:
                    t['total_count'] = int(r['total'])
                if r.get('errors') is not None:
                    t['total_errors'] = int(r['errors'])
                if r.get('rb') is not None:
                    t['total_bytes_recv'] = int(r['rb'])
                if r.get('sb') is not None:
                    t['total_bytes_sent'] = int(r['sb'])
                out[tg] = t
                break  # GROUP BY 每个 tag 组只 1 行（没 time bucket）
    except Exception:  # noqa: BLE001
        pass
    return out


def query_recent_window_error_rate(
    run_id: str, window_sec: int = 30,
) -> tuple[int, int, float] | None:
    """
    最近 window_sec 秒的 (total, errors, error_rate) 元组；连不上 InfluxDB 返 None。

    P0 #3 early abort gate 用：30s 后每 5s 调一次，error_rate > 80% 且 total > 50
    时主控自动 cancel 无效 run，避免 100% 错误的脏数据污染 baseline pool。
    """
    client = get_client()
    if client is None:
        return None
    safe_run = run_id.replace("'", "''")
    q_total = (
        "SELECT sum(\"count\") AS total "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='all' AND \"statut\"='all' "
        f"AND time > now() - {window_sec}s"
    )
    q_err = (
        "SELECT sum(\"countError\") AS errors "
        f"FROM \"jmeter\" WHERE \"run_id\"='{safe_run}' "
        f"AND \"transaction\"='all' AND \"statut\"='all' "
        f"AND time > now() - {window_sec}s"
    )
    try:
        total = 0
        for r in client.query(q_total).get_points():
            total = int(r.get('total') or 0)
        errors = 0
        for r in client.query(q_err).get_points():
            errors = int(r.get('errors') or 0)
        if total <= 0:
            return (0, 0, 0.0)
        return (total, errors, errors / total)
    except Exception:  # noqa: BLE001
        return None


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
