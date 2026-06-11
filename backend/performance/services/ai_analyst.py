"""AI 压测分析：把一次 run 的全量终态数据组装成「按压测模式定制」的数据模板，
调用 OpenAI 兼容端点（qoder-proxy / 任何兼容网关，base_url+key 走 .env）产出分析结论。

设计要点：
- 数据全取自 DB 终态快照（RunSamplerStat / RunErrorAggregate / RunAnalysis /
  RunServiceDiagnosis / RunEventAnchor / RunArthasCapture），不依赖原始 JTL/InfluxDB。
- 数据模板「按场景」：基准/负载/压力/稳定性/峰值/吞吐量 各自带不同的关注点(focus) +
  对应时序，AI 才能对症分析（详见 SCENARIO_FOCUS）。
- 时序统一降采样到 ~20 点，控制 token，又保留趋势形状。
- 后端不绑死 qoder：只认 OpenAI 兼容 /chat/completions 协议。
"""
from __future__ import annotations

import json
from typing import Any

import requests
from django.conf import settings

# kind → 场景兜底（snapshot 无 scenario 字段时用；Stepping 既可能是 load 也可能 stress，
# 优先信 snapshot.scenario，这里只兜底成 load）
KIND_TO_SCENARIO = {
    'ThreadGroup': 'baseline',
    'SteppingThreadGroup': 'load',
    'ConcurrencyThreadGroup': 'soak',
    'UltimateThreadGroup': 'spike',
    'ArrivalsThreadGroup': 'throughput',
}

# 每个压测模式：中文名 + AI 该重点判什么（喂进 prompt，决定分析视角）
SCENARIO_FOCUS = {
    'baseline': ('基准', '轻负载下系统的"裸"稳定度。重点看 RPS 抖动(CV%)、P95/均值长尾比；'
                 '判断是否够格当回归基线。'),
    'load': ('负载', '阶梯加压找容量拐点。重点看并发-吞吐曲线在哪个并发档不再线性增长(拐点)、'
             '各并发档 P99 何时开始翘头，给出可承载并发上限。'),
    'stress': ('压力', '压过拐点看崩溃行为。重点看吞吐见顶后是否回落(容量悬崖)、'
               '错误率随并发的上升曲线、崩溃临界点，并对错误类型做根因归因。'),
    'soak': ('稳定性', '长时间恒定并发看劣化/泄漏。重点看 P95 RT 是否随时间缓慢爬升(斜率)、'
             'RPS 是否漂移、结合 Full GC 次数/堆趋势判断内存或连接池泄漏。'),
    'spike': ('峰值', '瞬时冲高看跟随与恢复。重点看 RPS 能否跟上 VU 尖峰(跟随率)、'
              '冲顶时延迟/错误的尖刺、峰值过后能否快速恢复。'),
    'throughput': ('吞吐量', '开环按目标 RPS 注入(并发非自变量)。重点看实际 RPS 对目标的达成率、'
                   '到哪个注入率开始饱和(延迟陡增/错误上升)。'),
}


def is_configured() -> bool:
    return bool(getattr(settings, 'AI_BASE_URL', '') and getattr(settings, 'AI_API_KEY', ''))


def _downsample(series: list, n: int = 20) -> list:
    """等间隔降采样 [[ts,v],...] 到至多 n 点（保留首尾）。"""
    if not series or len(series) <= n:
        return series
    step = len(series) / n
    out = [series[int(i * step)] for i in range(n)]
    if series[-1] is not out[-1]:
        out.append(series[-1])
    return out


def _scenario_of(tg_cfg: dict) -> str:
    return tg_cfg.get('scenario') or KIND_TO_SCENARIO.get(tg_cfg.get('kind', ''), 'load')


def _service_findings(diag: dict, prom: dict) -> dict[str, Any]:
    """从 RunServiceDiagnosis 的 diagnosis(DiagnosisResponse) + prometheus 抽关键诊断指标。"""
    out: dict[str, Any] = {}
    jvm = (diag or {}).get('jvm') or {}
    gc = jvm.get('gc') or {}
    if gc.get('old_count'):
        out['full_gc'] = {'count': gc.get('old_count'), 'time_ms': gc.get('old_time_ms')}
    at = (diag or {}).get('active_threads') or {}
    if at.get('max'):
        out['active_threads_max'] = at.get('max')
    uri_slow = [u for u in (diag or {}).get('uri_stat', []) if (u.get('max_ms') or 0) >= 1000]
    if uri_slow:
        out['slow_uris'] = [{'uri': u.get('uri'), 'max_ms': u.get('max_ms')} for u in uri_slow[:5]]
    err_uris = (diag or {}).get('error_uris') or []
    if err_uris:
        out['error_uris'] = [{'uri': u.get('uri'), 'fail': u.get('fail_count')} for u in err_uris[:5]]
    ds = (diag or {}).get('datasource') or {}
    if ds.get('max'):
        out['datasource'] = {'active_max': ds.get('max')}
    # CPU 峰值（跨 pod 跨时间 max）
    cpu = (prom or {}).get('cpu_usage_by_pod') or {}
    peak = None
    for pts in (cpu.get('pods') or {}).values():
        for p in pts:
            v = p.get('value')
            if v is not None and (peak is None or v > peak):
                peak = v
    if peak is not None:
        out['cpu_peak_pct'] = round(peak, 1)
    return out


def build_ai_payload(run) -> dict[str, Any]:
    """组装「按场景」的完整数据模板。"""
    from ..models import (  # noqa: PLC0415
        RunArthasCapture, RunErrorAggregate, RunEventAnchor, RunSamplerStat, RunServiceDiagnosis,
    )
    task = run.task
    started_ms = int(run.started_at.timestamp() * 1000) if run.started_at else None

    # 线程组 + 场景（snapshot 优先，回退 task 当前配置）
    tg_cfgs = run.thread_groups_config_snapshot or task.thread_groups_config or []
    thread_groups = []
    for c in tg_cfgs:
        scn = _scenario_of(c)
        label, focus = SCENARIO_FOCUS.get(scn, ('', ''))
        thread_groups.append({
            'scenario': scn, 'scenario_cn': label, 'kind': c.get('kind'),
            'params': c.get('params', {}), 'focus': focus,
        })

    # 接口红黑榜（DB）
    stats = list(RunSamplerStat.objects.filter(run=run).exclude(label='all'))
    slowest = sorted(stats, key=lambda s: s.p99_ms, reverse=True)[:6]
    most_err = sorted([s for s in stats if s.error > 0], key=lambda s: s.error, reverse=True)[:6]

    # 错误聚合（DB）
    errs = list(RunErrorAggregate.objects.filter(run=run).order_by('-count')[:8])

    # 事件锚点（DB）
    events = []
    for e in RunEventAnchor.objects.filter(run=run).order_by('ts_ms'):
        events.append({
            'type': e.event_type,
            'offset_sec': round((e.ts_ms - started_ms) / 1000, 1) if started_ms else None,
            'metadata': e.metadata or {},
        })

    # 服务诊断（DB 快照）
    svc_diag = []
    for sd in RunServiceDiagnosis.objects.filter(run=run):
        f = _service_findings(sd.diagnosis, sd.prometheus)
        if f:
            svc_diag.append({'service': sd.service, **f})

    # Arthas 实锤（DB）
    arthas = [{
        'command': c.command, 'service': c.service, 'note': c.note,
        'output_excerpt': (c.output or '')[:800],
    } for c in RunArthasCapture.objects.filter(run=run)[:10]]

    # 时序（RunAnalysis，降采样）
    ts: dict[str, Any] = {}
    analysis = getattr(run, 'analysis', None)
    if analysis:
        conc = analysis.concurrency or {}
        if conc.get('overall'):
            ts['concurrency'] = _downsample(conc['overall'])
        lat = analysis.latency_overall or {}
        for k in ('p95_ms', 'p99_ms'):
            if lat.get(k):
                ts[k] = _downsample(lat[k])
        ebt = analysis.error_breakdown_ts or {}
        ts['error_breakdown_ts'] = {k: _downsample(v) for k, v in ebt.items() if v}

    return {
        'meta': {
            'task': task.title,
            'thread_groups': thread_groups,
            'duration_sec': run.duration_seconds,
            'planned_vusers': run.virtual_users,
            'environment': getattr(task.environment, 'name', None) if task.environment_id else None,
            'services': task.service_names or [],
            'status': run.status,
        },
        'overall_kpi': {
            'total_requests': run.total_requests,
            'avg_rps': run.avg_rps,
            'p99_ms': run.p99_ms,
            'error_rate_pct': run.error_rate,
        },
        'endpoints': {
            'slowest': [{'label': s.label, 'p99_ms': s.p99_ms, 'avg_ms': s.avg_ms, 'rps': s.avg_rps} for s in slowest],
            'most_errors': [{'label': s.label, 'errors': s.error,
                             'error_rate_pct': round(s.error / max(1, s.total) * 100, 2)} for s in most_err],
        },
        'errors': {
            'breakdown': {k: v for k, v in (run.error_breakdown or {}).items() if v},
            'samples': [{'code': e.response_code, 'label': e.label, 'message': e.sample_message
                         or e.sample_failure_message, 'count': e.count} for e in errs],
        },
        'events': events,
        'service_diagnosis': svc_diag,
        'arthas': arthas,
        'timeseries': ts,
    }


def build_messages(run) -> list[dict[str, str]]:
    payload = build_ai_payload(run)
    scns = '、'.join(f"{t['scenario_cn']}({t['scenario']})" for t in payload['meta']['thread_groups']) or '未知'
    system = (
        '你是一名资深性能测试专家 + 性能工程师。下面是一次 JMeter 压测的全量终态数据(JSON)，'
        '请基于数据给出专业分析。要求：\n'
        '① 一句话裁决（通过 / 有风险 / 不通过）\n'
        '② 根因分析：把指标连成因果链，例如「Full GC 14 次 → 线程堆积 210 → P99 2.4s → 503」\n'
        '③ 瓶颈定位：指出最可能的瓶颈点（应用/JVM/DB连接池/网络/压力机）\n'
        '④ 优化建议：可执行的下一步\n'
        '务必结合「压测模式」的关注点(每个线程组的 focus 字段)来解读，不同模式看的指标不同。'
        '用中文，结论先行，简洁有力，不要逐条复述数据。'
    )
    user = (
        f'本次压测模式：{scns}。\n'
        f'各线程组的 focus 字段写明了该模式应重点判断什么，请据此分析。\n\n'
        f'压测数据：\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```'
    )
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]


def generate_summary(run) -> str:
    """调用 OpenAI 兼容端点产出分析文本。未配置 / 失败抛异常，由 view 兜友好错误。"""
    if not is_configured():
        raise RuntimeError('未配置 AI 端点：请在 backend/.env 设 AI_BASE_URL / AI_API_KEY / AI_MODEL')
    base = settings.AI_BASE_URL.rstrip('/')
    url = base + ('/chat/completions' if base.endswith('/v1') else '/v1/chat/completions')
    resp = requests.post(
        url,
        headers={'Authorization': f'Bearer {settings.AI_API_KEY}', 'Content-Type': 'application/json'},
        json={
            'model': settings.AI_MODEL,
            'messages': build_messages(run),
            'temperature': 0.3,
            'max_tokens': 1500,
        },
        timeout=settings.AI_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return (data.get('choices') or [{}])[0].get('message', {}).get('content', '').strip()
