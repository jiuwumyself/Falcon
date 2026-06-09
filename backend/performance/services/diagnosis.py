"""服务诊断取数 + 终态快照。

同一套 builder 供两处共用：
- views 实时取数（run 进行中 / 老 run 无快照）
- executor 终态快照（snapshot_run → 写 RunServiceDiagnosis）

历史 run 读 DB 秒开，读不到/出错再回退实时连接（Pinpoint / Prometheus）。
Pinpoint 端点只用 run 时间窗，故终态快照对它们永远有效；Prometheus 仅快照 run 窗口
（前端「近 N 分」预设仍走实时）。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from django.utils import timezone

# Pod 时序需要的 Prometheus metric（与前端 usePrometheusMetrics 的 NEEDED 对齐）
_PROM_NEEDED = ['cpu_usage_by_pod', 'memory_usage_by_pod',
                'network_rx', 'network_tx', 'disk_read', 'disk_write']


def _window_ms(run) -> tuple[int, int] | None:
    if not run.started_at:
        return None
    from_ms = int(run.started_at.timestamp() * 1000)
    end = run.finished_at or timezone.now()
    return from_ms, int(end.timestamp() * 1000)


def build_servermap(run, service: str, inbound: int = 2, outbound: int = 2,
                    from_override: int | None = None,
                    to_override: int | None = None) -> dict[str, Any]:
    """单服务（深度 inbound×outbound）的 Pinpoint 服务拓扑。run 窗口拿不到 → 退近 30 分钟。
    from_override/to_override（ms）非空 → 用指定时间窗（前端「近 N 分/时」预设）而非 run 窗口。"""
    from . import pinpoint as pp  # noqa: PLC0415
    from ..models import Service  # noqa: PLC0415
    if not pp.is_enabled():
        return {'enabled': False, 'nodes': [], 'links': [], 'skipped': [],
                'window': None, 'pinpoint_base_url': ''}
    if from_override and to_override:
        from_ms, to_ms = int(from_override), int(to_override)
    else:
        win = _window_ms(run)
        if not win:
            return {'enabled': True, 'nodes': [], 'links': [], 'skipped': [],
                    'window': None, 'pinpoint_base_url': pp.base_url()}
        from_ms, to_ms = win

    app_types = pp.list_applications()  # {app: serviceType}
    svc = Service.objects.filter(name=service).first()
    app = (svc.pinpoint_app if svc and svc.pinpoint_app else service)
    st = app_types.get(app)
    targets, skipped = [], []
    if not st:
        skipped.append({'service': service, 'reason': '不是 Pinpoint 应用（需在 admin 配 pinpoint_app）'})
    else:
        targets.append((service, app, st))

    def _query(f_ms: int, t_ms: int):
        nd: dict[str, dict] = {}
        lk: dict[tuple, dict] = {}
        if not targets:
            return nd, lk
        with ThreadPoolExecutor(max_workers=min(6, len(targets))) as ex:
            for m in ex.map(lambda t: pp.query_server_map(
                    t[1], t[2], f_ms, t_ms, inbound=inbound, outbound=outbound), targets):
                for n in m['nodes']:
                    nd.setdefault(n['key'], n)
                for e in m['links']:
                    lk.setdefault((e['from'], e['to']), e)
        return nd, lk

    nodes, links = _query(from_ms, to_ms)
    window = {'from': from_ms, 'to': to_ms}
    fallback = False
    if len(nodes) <= 1 and not links:
        now_ms = int(timezone.now().timestamp() * 1000)
        rf, rt = now_ms - 30 * 60 * 1000, now_ms
        n2, l2 = _query(rf, rt)
        if len(n2) > 1 or l2:
            nodes, links, window, fallback = n2, l2, {'from': rf, 'to': rt}, True

    return {
        'enabled': True,
        'nodes': list(nodes.values()),
        'links': list(links.values()),
        'skipped': skipped,
        'window': window,
        'fallback_recent': fallback,
        'pinpoint_base_url': pp.base_url(),
    }


def build_diagnosis(run, service: str, brief: bool = False,
                    from_override: int | None = None,
                    to_override: int | None = None) -> dict[str, Any]:
    """单服务诊断聚合：Pinpoint 事务/异常/慢URL/活跃线程/连接池/agent。brief=只查事务概览。
    from_override/to_override（ms）非空 → 用指定时间窗（前端预设）而非 run 窗口。"""
    from . import pinpoint as pp  # noqa: PLC0415
    from ..models import Service  # noqa: PLC0415
    base = {'enabled': pp.is_enabled(), 'available': False, 'service': service,
            'window': None, 'pinpoint_base_url': pp.base_url()}
    win = (int(from_override), int(to_override)) if (from_override and to_override) else _window_ms(run)
    if not pp.is_enabled() or not win or not service:
        return base
    from_ms, to_ms = win
    base['window'] = {'from': from_ms, 'to': to_ms}

    svc = Service.objects.filter(name=service).first()
    app = (svc.pinpoint_app if svc and svc.pinpoint_app else service)
    app_types = pp.list_applications()
    if app not in app_types:
        base['reason'] = '不是 Pinpoint 应用（可在 admin 配 pinpoint_app）'
        return base
    code = pp.app_service_type_code(app) or 0

    if brief:
        tx = pp.query_transactions(app, code, from_ms, to_ms)
        base.update({'available': True, 'pinpoint_app': app, 'transactions': tx,
                     'pods': tx.get('pods') or []})
        return base

    jobs = {
        'transactions': lambda: pp.query_transactions(app, code, from_ms, to_ms),
        'active_threads': lambda: pp.query_inspector_chart(app, 'activeTrace', from_ms, to_ms),
        'datasource': lambda: pp.query_inspector_chart(app, 'dataSource', from_ms, to_ms),
        'tps_series': lambda: pp.query_inspector_chart(app, 'transaction', from_ms, to_ms),
        'uri_stat': lambda: pp.query_slow_uris(app, from_ms, to_ms),
        'exceptions': lambda: pp.query_error_groups(app, from_ms, to_ms),
        'error_uris': lambda: pp.query_error_uris(app, from_ms, to_ms),
        'agents': lambda: pp.query_agent_list(app, from_ms, to_ms),
        # JVM（应用级 inspector；CPU 走 Pod 时序、GC 这版应用级拿不到）
        'jvm_heap': lambda: pp.query_inspector_chart(app, 'heap', from_ms, to_ms),
        'jvm_non_heap': lambda: pp.query_inspector_chart(app, 'nonHeap', from_ms, to_ms),
        'jvm_threads': lambda: pp.query_inspector_chart(app, 'totalThreadCount', from_ms, to_ms),
        'jvm_loaded_class': lambda: pp.query_inspector_chart(app, 'loadedClass', from_ms, to_ms),
    }
    out: dict = {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futs = {ex.submit(fn): key for key, fn in jobs.items()}
        for f in as_completed(futs):
            try:
                out[futs[f]] = f.result()
            except Exception:  # noqa: BLE001
                out[futs[f]] = None

    tx = out.get('transactions') or {}
    base.update({
        'available': True,
        'pinpoint_app': app,
        'transactions': tx,
        'active_threads': out.get('active_threads') or {},
        'datasource': out.get('datasource') or {},
        'tps_series': out.get('tps_series') or {},
        'uri_stat': out.get('uri_stat') or [],
        'exceptions': out.get('exceptions') or [],
        'error_uris': out.get('error_uris') or [],
        'agents': (tx.get('agents') if tx.get('agents') else (out.get('agents') or [])),
        'pods': tx.get('pods') or [],
        'jvm': {
            'heap': out.get('jvm_heap') or {},
            'non_heap': out.get('jvm_non_heap') or {},
            'threads': out.get('jvm_threads') or {},
            'loaded_class': out.get('jvm_loaded_class') or {},
        },
    })

    # 单 pod JVM（堆 + Old GC）：agent 级 heap 一次查到，既给 by_pod（点单个 pod 看），
    # 又跨 agent 聚合出应用级 Old GC（应用级 inspector 没 GC 字段）。
    agents_for_jvm = [a for a in (tx.get('agents') or []) if a.get('agent_id')][:12]
    gc_total_c = gc_total_t = 0
    gc_series_map: dict[int, float] = {}
    by_pod: list[dict[str, Any]] = []
    if agents_for_jvm:
        with ThreadPoolExecutor(max_workers=min(8, len(agents_for_jvm))) as ex:
            pairs = list(ex.map(
                lambda a: (a, pp.query_agent_jvm(app, a['agent_id'], from_ms, to_ms)),
                agents_for_jvm))
        for a, j in pairs:
            g = j.get('gc') or {}
            gc_total_c += g.get('old_count', 0)
            gc_total_t += g.get('old_time_ms', 0)
            for ts_v, c in (g.get('series') or []):
                gc_series_map[ts_v] = gc_series_map.get(ts_v, 0) + c
            by_pod.append({
                'pod': a.get('pod') or a.get('agent_name') or a['agent_id'],
                'agent_id': a['agent_id'],
                'agent_name': a.get('agent_name') or a['agent_id'],
                'heap': j.get('heap') or {},
                'gc': g,
            })
    base['jvm']['gc'] = {
        'old_count': gc_total_c,
        'old_time_ms': gc_total_t,
        'series': sorted([k, v] for k, v in gc_series_map.items()),
    }
    base['jvm']['by_pod'] = by_pod
    return base


def brief_from_full(full: dict[str, Any], service: str) -> dict[str, Any]:
    """从全量 diagnosis 快照里抽事务概览（brief 模式用，免再查 Pinpoint）。"""
    if not full or not full.get('available'):
        return full or {'enabled': True, 'available': False, 'service': service,
                        'window': None, 'pinpoint_base_url': ''}
    return {
        'enabled': full.get('enabled', True), 'available': True, 'service': service,
        'window': full.get('window'), 'pinpoint_base_url': full.get('pinpoint_base_url', ''),
        'pinpoint_app': full.get('pinpoint_app'),
        'transactions': full.get('transactions') or {},
        'pods': full.get('pods') or [],
    }


def build_prometheus(run, service: str, source_override=None,
                     from_override: int | None = None,
                     to_override: int | None = None) -> dict[str, Any]:
    """Pod 时序：从 prometheus 源拉 NEEDED 指标，无数据 fallback 其他源。
    source_override / from_override / to_override 非空 → 脱离 run（task 级 / 预设窗口）。"""
    from .prometheus import PrometheusAPIError, query_service_metrics  # noqa: PLC0415
    from ..models import PrometheusDataSource  # noqa: PLC0415
    ds = source_override or (run.task.prometheus_source if run else None)
    if from_override and to_override:
        from_ms, to_ms = int(from_override), int(to_override)
    else:
        win = _window_ms(run) if run else None
        if not win:
            return {}
        from_ms, to_ms = win
    if not ds or not service:
        return {}
    start, end = str(from_ms // 1000), str(to_ms // 1000)
    span = max(1, to_ms // 1000 - from_ms // 1000)
    step = f'{max(15, span // 240)}s'

    def _q(source):
        try:
            return query_service_metrics(source.url, service, start, end, step,
                                         auth_token=source.auth_token,
                                         metric_keys=_PROM_NEEDED, use_cache=False)
        except PrometheusAPIError:
            return None

    def _has(d):
        return bool(d) and any(v.get('data') or v.get('pods') for v in d.values())

    data = _q(ds)
    if _has(data):
        return data
    for other in PrometheusDataSource.objects.filter(enabled=True).exclude(pk=ds.pk):
        fb = _q(other)
        if _has(fb):
            return fb
    return data or {}


def get_snapshot(run, service: str):
    from ..models import RunServiceDiagnosis  # noqa: PLC0415
    return RunServiceDiagnosis.objects.filter(run=run, service=service).first()


def snapshot_run(run) -> int:
    """run 终态：把每个被压测服务的 拓扑/Pinpoint/Pod时序 快照入库。返回服务数。"""
    from ..models import RunServiceDiagnosis  # noqa: PLC0415
    n = 0
    for service in list(run.task.service_names or []):
        try:
            sm = build_servermap(run, service)
        except Exception:  # noqa: BLE001
            sm = {}
        try:
            dg = build_diagnosis(run, service, brief=False)
        except Exception:  # noqa: BLE001
            dg = {}
        try:
            prom = build_prometheus(run, service)
        except Exception:  # noqa: BLE001
            prom = {}
        RunServiceDiagnosis.objects.update_or_create(
            run=run, service=service,
            defaults={'servermap': sm or {}, 'diagnosis': dg or {}, 'prometheus': prom or {}},
        )
        n += 1
    return n
