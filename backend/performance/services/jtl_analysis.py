"""终态分析：从 JTL / errors.xml 算出接口统计 / 错误聚合 / 并发 / 延迟拆解 / 错误时序。

纯计算函数,无 Django ORM 依赖(只用 csv / lxml / re)。两处复用,单一真相:
- `executor._on_finish` 终态一次性算 → 写 DB(RunSamplerStat / RunErrorAggregate / RunAnalysis)。
- `views` 显示端点在 DB 无数据时(老 run / 终态前)做文件兜底。

内存有界:用定长直方图(`LatencyHistogram`)算分位,不收集全部 elapsed —— 大 JTL
(几千万样本)收集 list 会 OOM。
"""
import csv
import re
from pathlib import Path

# ── 定长延迟直方图：1ms 桶覆盖 0~_HIST_MAX_MS,溢出归末桶。O(1) 内存算分位/极值/均值 ──
_HIST_MAX_MS = 60_000


class LatencyHistogram:
    __slots__ = ('buckets', 'count', 'total', 'min', 'max')

    def __init__(self) -> None:
        self.buckets = [0] * (_HIST_MAX_MS + 1)
        self.count = 0
        self.total = 0
        self.min: int | None = None
        self.max = 0

    def add(self, ms: int) -> None:
        if ms < 0:
            ms = 0
        self.count += 1
        self.total += ms
        if self.min is None or ms < self.min:
            self.min = ms
        if ms > self.max:
            self.max = ms
        self.buckets[ms if ms <= _HIST_MAX_MS else _HIST_MAX_MS] += 1

    def percentile(self, p: float) -> float:
        """nearest-rank:跟旧 sorted 实现 elapsed[int(N*p/100)-1] 等价(±1ms)。"""
        if self.count == 0:
            return 0.0
        target = max(1, int(self.count * p / 100.0))
        cum = 0
        for ms, c in enumerate(self.buckets):
            if c:
                cum += c
                if cum >= target:
                    return float(ms)
        return float(self.max)

    @property
    def avg(self) -> float:
        return self.total / self.count if self.count else 0.0

    @property
    def min_val(self) -> float:
        return float(self.min) if self.min is not None else 0.0


# ── threadName → 线程组名(标准 TG "Name 1-1" / 插件 TG "Name-ThreadStarter 1-1")──
_THREAD_NAME_RE = re.compile(r'^(.*?)(?:-ThreadStarter)?\s+\d+-\d+$')


def tg_from_thread_name(tn: str) -> str:
    m = _THREAD_NAME_RE.match(tn or '')
    return m.group(1) if m else (tn or '')


def err_bucket(code: str, msg: str) -> str:
    """error-samples 的 code_bucket 粗过滤分类(4xx/5xx/assertion/timeout/other)。"""
    if code.startswith('Non HTTP'):
        return 'timeout'
    if (msg or '').startswith('Assertion'):
        return 'assertion'
    if code.startswith('5'):
        return '5xx'
    if code.startswith('4'):
        return '4xx'
    return 'other'


# ── 接口统计 ───────────────────────────────────────────────────────────────
def compute_sampler_stats(jtl_path: Path) -> list[dict]:
    """扫 results.jtl,每接口聚合(对齐前端 SamplerStat / statistics.json 同形状)。
    分位用定长直方图(内存有界)。"""
    if not jtl_path.exists() or jtl_path.stat().st_size == 0:
        return []
    hist: dict[str, LatencyHistogram] = {}
    agg: dict[str, dict] = {}

    # 'all' 汇总行：所有样本进同一个直方图,p50/p90/p99 是**真·整体分位**(不能由
    # 各接口分位平均得到)。预置在最前,前端固定置顶显示。
    ALL = 'all'

    def _ensure(key: str) -> dict:
        rec = agg.get(key)
        if rec is None:
            rec = {'total': 0, 'success': 0, 'error': 0, 'bytes_sum': 0,
                   'first_ts': None, 'last_ts': None, 'top_errors': {}}
            agg[key] = rec
            hist[key] = LatencyHistogram()
        return rec

    _ensure(ALL)  # 占位,保证 'all' 排在 agg 最前

    try:
        with jtl_path.open('r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                label = row.get('label') or ''
                ok = (row.get('success') or '').lower() == 'true'
                # 错误归因 = HTTP 响应码优先(用户要"有错误代码就行"),无码再退到 message
                code = (row.get('responseCode') or '').strip()
                emsg = (row.get('failureMessage') or row.get('responseMessage') or '').strip()
                reason = code or emsg or '(unknown)'
                try:
                    elapsed = int(row.get('elapsed') or 0)
                except (TypeError, ValueError):
                    elapsed = 0
                try:
                    ts = int(row.get('timeStamp') or 0)
                except (TypeError, ValueError):
                    ts = 0
                try:
                    nbytes = int(row.get('bytes') or 0)
                except (TypeError, ValueError):
                    nbytes = 0
                # 同步累加到「该接口」+「all」两个桶
                for key in (label, ALL):
                    rec = _ensure(key)
                    rec['total'] += 1
                    if ok:
                        rec['success'] += 1
                    else:
                        rec['error'] += 1
                        rec['top_errors'][reason] = rec['top_errors'].get(reason, 0) + 1
                    hist[key].add(elapsed)
                    if ts:
                        rec['first_ts'] = ts if rec['first_ts'] is None else min(rec['first_ts'], ts)
                        rec['last_ts'] = ts if rec['last_ts'] is None else max(rec['last_ts'], ts)
                    rec['bytes_sum'] += nbytes
    except OSError:
        return []

    # 没有任何样本 → 不返回孤零零的空 'all' 行
    if agg[ALL]['total'] == 0:
        return []

    out = []
    for label, r in agg.items():
        h = hist[label]
        span = max((r['last_ts'] - r['first_ts']) / 1000.0, 0.001) if r['first_ts'] else 1
        top = sorted(r['top_errors'].items(), key=lambda x: -x[1])[:3]
        out.append({
            'label': label,
            'total': r['total'],
            'success': r['success'],
            'error': r['error'],
            'avg_ms': h.avg,
            'min_ms': h.min_val,
            'max_ms': float(h.max),
            'p50_ms': h.percentile(50),
            'p90_ms': h.percentile(90),
            'p99_ms': h.percentile(99),
            'avg_rps': r['total'] / span if span > 0 else 0,
            'avg_bytes': r['bytes_sum'] / r['total'] if r['total'] else 0,
            'top_errors': [{'reason': k, 'count': v} for k, v in top],
        })
    return out


# ── errors.xml 代表 body ───────────────────────────────────────────────────
def scan_errors_xml_bodies(
    run_dir: Path, *, max_keys: int = 500, max_scan: int = 100_000, max_len: int = 500,
) -> dict[tuple[str, str], str]:
    """扫 errors*.xml 抽每 (label, code) 首条 responseData(代表 body)。
    早退:unique key 满 max_keys 或扫满 max_scan 即止,避免全量 iterparse 大文件卡死。"""
    body_index: dict[tuple[str, str], str] = {}
    if not run_dir.exists():
        return body_index
    from lxml import etree  # noqa: PLC0415
    scanned = 0
    done = False
    for errors_xml in sorted(run_dir.glob('errors*.xml')):
        if done:
            break
        try:
            if errors_xml.stat().st_size == 0:
                continue
        except OSError:
            continue
        try:
            ctx = etree.iterparse(str(errors_xml), events=('end',), recover=True)
            for _ev, el in ctx:
                if el.tag not in ('sample', 'httpSample'):
                    continue
                if (el.get('s') or '').lower() != 'true':
                    key = (el.get('lb') or '', el.get('rc') or '')
                    if key not in body_index:
                        body_el = el.find('responseData')
                        if body_el is not None:
                            txt = (body_el.text or '').strip()
                            if txt:
                                body_index[key] = txt[:max_len]
                el.clear()
                parent = el.getparent()
                if parent is not None:
                    parent.remove(el)
                scanned += 1
                if len(body_index) >= max_keys or scanned >= max_scan:
                    done = True
                    break
        except OSError:
            continue
    return body_index


# ── 错误聚合 ───────────────────────────────────────────────────────────────
def compute_error_aggregates(jtl_path: Path, run_dir: Path) -> list[dict]:
    """扫 results.jtl 把失败样本按 (code, label) 聚合 + errors.xml 代表 body。
    返回 list[dict](对齐前端 ErrorAggregateRow);不做过滤/limit(那是端点的事)。"""
    if not jtl_path.exists() or jtl_path.stat().st_size == 0:
        return []
    body_index = scan_errors_xml_bodies(run_dir)
    agg: dict[tuple[str, str], dict] = {}
    try:
        with jtl_path.open('r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get('success') or '').lower() == 'true':
                    continue
                label = row.get('label') or ''
                code = row.get('responseCode') or ''
                key = (code, label)
                existing = agg.get(key)
                if existing is None:
                    agg[key] = {
                        'response_code': code,
                        'label': label,
                        'count': 1,
                        'sample_message': row.get('responseMessage') or '',
                        'sample_failure_message': row.get('failureMessage') or '',
                        'sample_url': row.get('URL') or '',
                        'sample_response_body': body_index.get((label, code), ''),
                    }
                else:
                    existing['count'] += 1
    except OSError:
        return []
    return sorted(agg.values(), key=lambda r: r['count'], reverse=True)


# ── 并发(allThreads 总 / grpThreads per-TG,分布式跨 agent 求和)──────────────
def compute_concurrency(run_dir: Path) -> dict:
    """每秒真实并发。allThreads/grpThreads 是每台 agent 本地值 → 分布式分别扫各 agent
    jtl(<pod>.jtl)每秒取峰值再跨 agent 相加;单机退到 results.jtl。"""
    merged = run_dir / 'results.jtl'
    agent_jtls = sorted(p for p in run_dir.glob('*.jtl') if p.name != 'results.jtl')
    sources = agent_jtls or ([merged] if merged.exists() else [])
    overall: dict[int, int] = {}
    by_tg: dict[str, dict[int, int]] = {}
    for src in sources:
        try:
            if not src.exists() or src.stat().st_size == 0:
                continue
        except OSError:
            continue
        a_overall: dict[int, int] = {}
        a_by_tg: dict[str, dict[int, int]] = {}
        try:
            with src.open('r', encoding='utf-8', errors='replace') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        ts = int(row.get('timeStamp') or 0)
                        at = int(row.get('allThreads') or 0)
                        gt = int(row.get('grpThreads') or 0)
                    except ValueError:
                        continue
                    if ts <= 0:
                        continue
                    b = (ts // 1000) * 1000
                    if at > a_overall.get(b, 0):
                        a_overall[b] = at
                    tg = tg_from_thread_name(row.get('threadName') or '')
                    if tg:
                        slot = a_by_tg.setdefault(tg, {})
                        if gt > slot.get(b, 0):
                            slot[b] = gt
        except OSError:
            continue
        for b, v in a_overall.items():
            overall[b] = overall.get(b, 0) + v
        for tg, slots in a_by_tg.items():
            dst = by_tg.setdefault(tg, {})
            for b, v in slots.items():
                dst[b] = dst.get(b, 0) + v
    return {
        'overall': [[ts, overall[ts]] for ts in sorted(overall)],
        'by_tg': {tg: [[ts, slot[ts]] for ts in sorted(slot)] for tg, slot in by_tg.items()},
    }


# ── 真·分位数延迟时序(整体 all + 仅成功 ok),按 window_ms 窗口聚合 ──────────────
# 为什么不用 InfluxDB:JMeter 推到 InfluxDB 的是每 agent 每 flush **预聚合好的**分位数,
# 分位数**不能跨 agent / 跨 flush 平均**——尤其 p99,每个小窗口 p99 偏高,mean 起来更高
# (实测 overall p99 虚高到 518,真值 355)。这里从 results.jtl 直接重算真分位。
# 为什么窗口 = 5s 不是 1s:分位数需要足够样本才稳。低 RPS 下每秒样本太少(如某接口
# 6 req/s → 每秒 p95 ≈ 那秒最大值,线疯狂尖刺,是统计噪声不是真信号)。5s 窗口(对齐
# JMeter flush 粒度)样本够,线稳且仍诚实(真窗口真分位)。时间分辨率降一点可接受。
# 内存有界:results.jtl 大体按时间戳排序(merge by timeStamp,仅局部逆序在 tol_ms 内),
# 滚动直方图任意时刻只留几个窗口的直方图。
def compute_latency_timeseries(
    jtl_path: Path, window_ms: int = 5000, tol_ms: int = 5000,
) -> dict:
    keys = ('p50_ms', 'p95_ms', 'p99_ms', 'p50_ok_ms', 'p95_ok_ms', 'p99_ok_ms')
    out: dict[str, list] = {k: [] for k in keys}
    if not jtl_path.exists() or jtl_path.stat().st_size == 0:
        return out

    win_all: dict[int, LatencyHistogram] = {}
    win_ok: dict[int, LatencyHistogram] = {}

    def finalize(b: int) -> None:
        h = win_all.pop(b, None)
        if h and h.count:
            out['p50_ms'].append([b, h.percentile(50)])
            out['p95_ms'].append([b, h.percentile(95)])
            out['p99_ms'].append([b, h.percentile(99)])
        hk = win_ok.pop(b, None)
        if hk and hk.count:
            out['p50_ok_ms'].append([b, hk.percentile(50)])
            out['p95_ok_ms'].append([b, hk.percentile(95)])
            out['p99_ok_ms'].append([b, hk.percentile(99)])

    max_ts = 0
    try:
        with jtl_path.open('r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ts = int(row.get('timeStamp') or 0)
                    el = int(row.get('elapsed') or 0)
                except ValueError:
                    continue
                if ts <= 0:
                    continue
                b = (ts // window_ms) * window_ms
                win_all.setdefault(b, LatencyHistogram()).add(el)
                if (row.get('success') or '').lower() == 'true':
                    win_ok.setdefault(b, LatencyHistogram()).add(el)
                if ts > max_ts:
                    max_ts = ts
                    # 窗口尾 + 容差都过去了才收齐,finalize + 释放(win_ok 键 ⊆ win_all 键)
                    cutoff = ((max_ts - tol_ms) // window_ms) * window_ms
                    for s in sorted(s for s in win_all if s < cutoff):
                        finalize(s)
    except OSError:
        return {k: [] for k in keys}

    for s in sorted(win_all):
        finalize(s)
    for k in out:
        out[k].sort()
    return out


# ── 延迟拆解(Connect / 服务端 / 客户端接收 三段,按秒均值)────────────────────
def compute_latency_breakdown(jtl_path: Path, exclude_ko: bool = False) -> dict:
    empty = {'connect_ms': [], 'server_ms': [], 'receive_ms': []}
    if not jtl_path.exists() or jtl_path.stat().st_size == 0:
        return empty
    buckets: dict[int, list[float]] = {}  # bucket -> [connect, server, receive, n]
    try:
        with jtl_path.open('r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if exclude_ko and (row.get('success') or '').lower() != 'true':
                    continue
                try:
                    ts = int(row.get('timeStamp') or 0)
                    elapsed = float(row.get('elapsed') or 0)
                    latency = float(row.get('Latency') or 0)
                    connect = float(row.get('Connect') or 0)
                except ValueError:
                    continue
                if ts <= 0:
                    continue
                if connect > latency:
                    connect = latency
                if latency > elapsed:
                    latency = elapsed
                server = max(0.0, latency - connect)
                receive = max(0.0, elapsed - latency)
                b = (ts // 1000) * 1000
                slot = buckets.get(b)
                if slot is None:
                    buckets[b] = [connect, server, receive, 1]
                else:
                    slot[0] += connect
                    slot[1] += server
                    slot[2] += receive
                    slot[3] += 1
    except OSError:
        return empty
    connect_pts, server_pts, receive_pts = [], [], []
    for ts in sorted(buckets):
        c, s, r, n = buckets[ts]
        connect_pts.append([ts, round(c / n, 2)])
        server_pts.append([ts, round(s / n, 2)])
        receive_pts.append([ts, round(r / n, 2)])
    return {'connect_ms': connect_pts, 'server_ms': server_pts, 'receive_ms': receive_pts}


# ── 错误类型时序(5 桶,按秒计数)──────────────────────────────────────────────
def compute_error_breakdown_ts(jtl_path: Path) -> dict:
    from .jmeter_runner import classify_jtl_error, empty_error_breakdown  # noqa: PLC0415
    template = empty_error_breakdown()
    if not jtl_path.exists() or jtl_path.stat().st_size == 0:
        return {k: [] for k in template}
    per_sec: dict[int, dict[str, int]] = {}
    try:
        with jtl_path.open('r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get('success') or '').lower() == 'true':
                    continue
                try:
                    ts = int(row.get('timeStamp') or 0)
                except ValueError:
                    continue
                if ts <= 0:
                    continue
                bname = classify_jtl_error(row)
                sec = (ts // 1000) * 1000
                slot = per_sec.get(sec)
                if slot is None:
                    slot = dict(template)
                    per_sec[sec] = slot
                slot[bname] = slot.get(bname, 0) + 1
    except OSError:
        return {k: [] for k in template}
    out: dict[str, list] = {k: [] for k in template}
    for ts in sorted(per_sec):
        slot = per_sec[ts]
        for bname in out:
            out[bname].append([ts, slot.get(bname, 0)])
    return out
