"""多机调度器（v1.2）。

职责：
  1. 按 thread_groups_config + 选中 LoadGenerator 列表算分片（compute_shards）：
     - **精确拆分**每个可拆字段（step_users/users/target_concurrency/rps/rows.users），
       各 agent 份额之和恒 = task 配置值（_split_int，余数给容量最大的台）。旧实现对每个
       TG 各自 ceil(value × factor) 再 max(1,…) → N 台各下钳到 1 → 每步总增量翻 N 倍。
     - **自动减 agent**：粒度（如 step_users）不足以铺满所选 agent 时弃用多余台，
       返回 dropped 台数供上层提示用户。
  2. 给每个分片生成 jmx（build_shard_jmx）：
     - 复用 build_run_xml 拿到含 Step 2 完整配置的 xml
     - _apply_shard_split 按 (shard.index, total_shards) 把每个 enabled TG 改成本片份额；
       min=1 的字段（baseline users 等）拆成 0 时 **禁用** 该 TG（不能留全量 → 翻倍）
     - BackendListener 注入加 host=pod_name tag（InfluxDB 切片用）
  3. 切 CSV 到分片本地：按行偏移 (row_index % shards == shard_index) 写到 work_dir/csv/
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .jmx import (
    JmxParseError, _inject_backend_listener_per_tg, _inject_error_response_listener,
    _set_csv_filename_at_path,
    build_run_xml, replace_thread_group, toggle_component,
)

if TYPE_CHECKING:
    from ..models import LoadGenerator, Task


@dataclass
class Shard:
    """一台 agent 的分片配置。"""
    index: int                        # 0-based shard 序号
    load_generator_id: int            # LoadGenerator.id
    pod_name: str                     # 入 InfluxDB host tag
    base_url: str                     # http://<ip>:<port>，主控调 agent 用
    vusers: int                       # 该 agent 跑多少线程
    csv_files: list[Path] = field(default_factory=list)   # 已切好的 csv 绝对路径


# ── max_wall 估算（P0 #1）──────────────────────────────────────────────

def _estimate_tg_seconds(kind: str, params: dict) -> int:
    """单个 TG 估算实际跑时长（秒）。多 TG 时上层取 max（TG 在 JMeter 里并行）。

    各 kind 公式按用户在 Step 2 配置的语义：
      ThreadGroup        : duration（标准 baseline）
      SteppingThreadGroup: step_count × step_delay + hold + shutdown_dur
                           其中 shutdown_dur ≈ ceil(max_threads/stop_count) × stop_period
                           简化：用 step_count×step_users / max(stop_users_count, 1) × stop_users_period 上限
      ConcurrencyThreadGroup: ramp_up + hold + shutdown
      UltimateThreadGroup: max(rows: initial_delay + ramp_up + hold + shutdown)
      ArrivalsThreadGroup: ramp_up + hold + shutdown
    """
    p = params or {}

    def _i(key, default=0):
        try:
            return int(p.get(key) or default)
        except (TypeError, ValueError):
            return default

    if kind == 'ThreadGroup':
        return _i('duration')
    if kind == 'SteppingThreadGroup':
        ramp = _i('step_count') * _i('step_delay')
        # 用户的 `shutdown` 字段语义 = 「退出总时长」(从峰值到 0 的总秒数)。
        # jmx.py 已把它反算成 casutg Stop users period(=shutdown/(num_drops-1))，
        # 所以这里直接当总时长用即可，不用再 ceil-div 乘一次。
        shutdown_dur = _i('shutdown', 30)
        return ramp + _i('hold') + shutdown_dur
    if kind == 'ConcurrencyThreadGroup':
        return _i('ramp_up') + _i('hold') + _i('shutdown', 5)
    if kind == 'UltimateThreadGroup':
        rows = p.get('rows') or []
        if not isinstance(rows, list) or not rows:
            return _i('initial_delay') + _i('ramp_up') + _i('hold') + _i('shutdown')
        max_end = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            end = (
                int(row.get('initial_delay') or 0)
                + int(row.get('ramp_up') or 0)
                + int(row.get('hold') or 0)
                + int(row.get('shutdown') or 0)
            )
            max_end = max(max_end, end)
        return max_end
    if kind == 'ArrivalsThreadGroup':
        return _i('ramp_up') + _i('hold') + _i('shutdown', 5)
    # 未知 kind 兜底：duration 直接用，不合理时上层 +OVERRUN 仍能兜
    return _i('duration')


def estimate_phase_anchors_sec(thread_groups_config: list[dict]) -> dict[str, int]:
    """§ 12 S1：估算 run 内三个阶段切换的相对秒数（从 started_at 起）。

    多 TG 时取第一个 enabled TG（与 § 4 §12 决策一致：主场景由首个 TG 决定）。

    返回 {'ramp_done_sec', 'hold_start_sec', 'shutdown_start_sec'}；未知 kind /
    缺参数时返回空 dict（调用方按"无锚点"处理，不写事件）。
    """
    if not thread_groups_config:
        return {}
    tg = thread_groups_config[0]
    if not isinstance(tg, dict):
        return {}
    kind = tg.get('kind') or 'ThreadGroup'
    p = tg.get('params') or {}

    def _i(key, default=0):
        try:
            return int(p.get(key) or default)
        except (TypeError, ValueError):
            return default

    if kind == 'ThreadGroup':
        ramp = _i('ramp_up')
        duration = _i('duration')
        if duration <= 0:
            return {}
        return {
            'ramp_done_sec': ramp,
            'hold_start_sec': ramp,
            'shutdown_start_sec': duration,  # 标准 TG 没显式 shutdown，duration 结束就退
        }
    if kind == 'SteppingThreadGroup':
        ramp = _i('step_count') * _i('step_delay')
        hold = _i('hold')
        return {
            'ramp_done_sec': ramp,
            'hold_start_sec': ramp,
            'shutdown_start_sec': ramp + hold,
        }
    if kind == 'ConcurrencyThreadGroup':
        ramp = _i('ramp_up')
        hold = _i('hold')
        return {
            'ramp_done_sec': ramp,
            'hold_start_sec': ramp,
            'shutdown_start_sec': ramp + hold,
        }
    if kind == 'ArrivalsThreadGroup':
        ramp = _i('ramp_up')
        hold = _i('hold')
        return {
            'ramp_done_sec': ramp,
            'hold_start_sec': ramp,
            'shutdown_start_sec': ramp + hold,
        }
    if kind == 'UltimateThreadGroup':
        rows = p.get('rows') or []
        if not isinstance(rows, list) or not rows:
            return {}
        row = rows[0] if isinstance(rows[0], dict) else {}
        ramp = int(row.get('initial_delay') or 0) + int(row.get('ramp_up') or 0)
        hold = int(row.get('hold') or 0)
        return {
            'ramp_done_sec': ramp,
            'hold_start_sec': ramp,
            'shutdown_start_sec': ramp + hold,
        }
    return {}


def compute_planned_run_params(
    thread_groups_config: list[dict],
    *,
    fallback_vusers: int = 0,
    fallback_ramp: int = 0,
    fallback_duration: int = 0,
) -> tuple[int, int, int]:
    """Step 3 起 run 时算快照三元组 (virtual_users, ramp_up_seconds, duration_seconds)。

    为什么不直接 copy task.virtual_users / ramp_up_seconds / duration_seconds：这三个
    旧单字段只在「第一个标准 ThreadGroup」存在时才同步（见 views.thread_groups PATCH），
    用户在 Step 2 切到 plugin TG（Stepping / Concurrency / Ultimate / Arrivals）后它们
    停在旧值失真——例如 Stepping 实跑 220s，duration_seconds 仍是上传时的 125s，导致
    进度条 / Timeline / RunStatusCard 显示的时长跟真实场景对不上。这里统一从配置算，
    单一真相。

    语义（对齐 TaskRun.duration_seconds 注释「仅 steady 期」+ Timeline 端点 + 前端
    phaseSegments / RunStatusCard，三者都按 total = ramp + duration 用）：
      ramp_up_seconds  = 加压段秒数（爬到峰值并发）
      duration_seconds = 加压之后（稳态 + 收尾）秒数，**不含 ramp**
      整 run 估算时长 = ramp_up_seconds + duration_seconds = estimate_max_wall_sec

    多 TG：total 取最长 TG（JMeter 并行），ramp 取首个 enabled TG 锚点——单字段模型对
    多 TG 天然有损，精确时间轴另走 executor 写的真实事件锚点（first_sample / ramp_done /
    shutdown_start）。
    """
    if not thread_groups_config:
        return fallback_vusers, fallback_ramp, fallback_duration
    total = estimate_max_wall_sec(thread_groups_config, fallback_duration)
    anchors = estimate_phase_anchors_sec(thread_groups_config)
    ramp = int(anchors.get('ramp_done_sec') or 0)
    if ramp < 0 or ramp > total:
        ramp = 0  # 防御：ramp 不应超过总时长
    steady = max(1, total - ramp)
    vusers = compute_planned_vusers_total(thread_groups_config, fallback_vusers)
    return vusers, ramp, steady


def _planned_vusers_for_tg(kind: str, params: dict) -> int:
    """单个 TG 的"计划线程数"（thread 驱动 TG 的并发上限）。

    跟 views._compute_tg_planned_users 同源：前端 ConcurrencyChart 拿这个画计划线，
    后端 compute_shards 拿 sum 做分片。

      ThreadGroup            : users
      SteppingThreadGroup    : initial_threads + step_users × step_count
      ConcurrencyThreadGroup : target_concurrency
      UltimateThreadGroup    : sum(rows.users)（多峰错峰也是总线程数）
      ArrivalsThreadGroup    : 0（RPS 驱动，不按 vusers 分；由 _scale_thread_groups_to_shard
                                按 target_rps 比例缩放）
    """
    p = params or {}

    def _i(key, default=0):
        try:
            return int(p.get(key) or default)
        except (TypeError, ValueError):
            return default

    if kind == 'ThreadGroup':
        return _i('users')
    if kind == 'SteppingThreadGroup':
        return _i('initial_threads') + _i('step_users') * _i('step_count')
    if kind == 'ConcurrencyThreadGroup':
        return _i('target_concurrency')
    if kind == 'UltimateThreadGroup':
        rows = p.get('rows') or []
        if isinstance(rows, list) and rows:
            return sum(int(r.get('users') or 0) for r in rows if isinstance(r, dict))
        return _i('users')
    # ArrivalsThreadGroup / 未知 kind → 0
    return 0


def compute_planned_vusers_total(
    thread_groups_config: list[dict],
    fallback: int = 0,
) -> int:
    """所有 enabled thread-driven TG 的 planned vusers 之和。

    JMeter 行为：多 TG 并行 → 总线程数 = 各 TG 之和（不是 max）。多机分片要按这个
    总数除以 agent 台数派活，否则像 task.virtual_users（jmx parse 时的初值）会把
    "3 个 TG 各 5 线程"误读成 1，分片永远只塞第一台。

    fallback：sum=0 时（纯 ArrivalsTG 或配置全空）返 fallback，最少 1。
    """
    if not thread_groups_config:
        return max(1, fallback)
    total = 0
    for tg in thread_groups_config:
        if not isinstance(tg, dict):
            continue
        kind = tg.get('kind') or 'ThreadGroup'
        params = tg.get('params') or {}
        total += _planned_vusers_for_tg(kind, params)
    if total <= 0:
        return max(1, fallback)
    return total


def estimate_max_wall_sec(
    thread_groups_config: list[dict],
    fallback_seconds: int = 0,
) -> int:
    """
    所有启用 TG（PATCH 时禁用 TG 已剔除，只剩启用项）取 max(单 TG 估算)。
    JMeter 默认行为：多 TG 并行，整 run 持续到最后退出的 TG。

    Args:
      thread_groups_config: task.thread_groups_config，每项 {path, scenario, kind, params}
      fallback_seconds: 配置全空 / 解析失败时的兜底（一般传 task.duration_seconds）

    返回：最长 TG 估算秒数，最少 1 秒（避免 0 max_wall 让 _heartbeat_loop 无超时检查）
    """
    if not thread_groups_config:
        return max(1, fallback_seconds)
    longest = 0
    for tg in thread_groups_config:
        if not isinstance(tg, dict):
            continue
        kind = tg.get('kind') or 'ThreadGroup'
        params = tg.get('params') or {}
        longest = max(longest, _estimate_tg_seconds(kind, params))
    if longest <= 0:
        return max(1, fallback_seconds)
    return longest


# ── 分配 ────────────────────────────────────────────────────────────────

def _split_int(value: int, n: int) -> list[int]:
    """把整数 value 平均拆成 n 份，**余数压到前几份**（前 = 容量最大的 agent，调用方
    已按 max_vusers 降序排好）。和恒等于 value（不向上取整、不丢余数）。

    这是根治"翻倍 bug"的核心：旧实现对每个 TG 各自 ceil(value × factor) 再 max(1,…)，
    N 台各自下钳到 1 → 每步总增量 = N × step_users 而非 step_users。改成精确拆分后
    各 agent 份额之和恒 = task 配置值。

      _split_int(1, 2)   → [1, 0]      （3VU 2agent、S=1：只第一台加，第二台 0）
      _split_int(10, 3)  → [4, 3, 3]   （101VU 3agent、S=10：每步跨 agent 共加 10）
      _split_int(0, 3)   → [0, 0, 0]
    """
    if n <= 0:
        return []
    if value <= 0:
        return [0] * n
    base, rem = divmod(value, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def _tg_i(params: dict, key: str, default: int = 0) -> int:
    try:
        return int(params.get(key) or default)
    except (TypeError, ValueError):
        return default


def _useful_agents_for_tg(kind: str, params: dict) -> int:
    """该 TG 最多能"铺满"几台 agent —— 每台至少分到 1 个不可再分的工作单元。

    决定自动减 agent：所选 agent 数 > 所有 TG useful 上限时，多出来的 agent 分不到活，
    自动弃用并提示用户。

      ThreadGroup            : users（每台 ≥1 线程）
      SteppingThreadGroup    : max(step_users, initial_threads)
                               （每步增量按 step_users 拆，最细每台 1；initial 也各占 1）
      ConcurrencyThreadGroup : target_concurrency
      ArrivalsThreadGroup    : target_rps（每台 ≥1 RPS，rps 是整数）
      UltimateThreadGroup    : max(rows.users)（线程最多的那行决定能铺几台）
    """
    p = params or {}
    if kind == 'ThreadGroup':
        return max(0, _tg_i(p, 'users') or _tg_i(p, 'num_threads'))
    if kind == 'SteppingThreadGroup':
        return max(_tg_i(p, 'step_users'), _tg_i(p, 'initial_threads'))
    if kind == 'ConcurrencyThreadGroup':
        return max(0, _tg_i(p, 'target_concurrency'))
    if kind == 'ArrivalsThreadGroup':
        return max(0, _tg_i(p, 'target_rps'))
    if kind == 'UltimateThreadGroup':
        rows = p.get('rows')
        if isinstance(rows, list) and rows:
            return max((int(r.get('users') or 0) for r in rows if isinstance(r, dict)),
                       default=0)
        return max(0, _tg_i(p, 'users'))
    return 0


def _shard_thread_peak(kind: str, params: dict, i: int, n: int) -> int:
    """第 i 片在该 TG 上的线程峰值（用作 num_threads cap + 容量校验）。
    Arrivals 是 RPS 驱动、不按线程数计 → 返 0。"""
    p = params or {}
    if kind == 'ThreadGroup':
        return _split_int(_tg_i(p, 'users') or _tg_i(p, 'num_threads'), n)[i]
    if kind == 'SteppingThreadGroup':
        su = _split_int(_tg_i(p, 'step_users'), n)[i]
        ini = _split_int(_tg_i(p, 'initial_threads'), n)[i]
        return ini + su * _tg_i(p, 'step_count')
    if kind == 'ConcurrencyThreadGroup':
        return _split_int(_tg_i(p, 'target_concurrency'), n)[i]
    if kind == 'UltimateThreadGroup':
        rows = p.get('rows')
        if isinstance(rows, list) and rows:
            return sum(_split_int(int(r.get('users') or 0), n)[i]
                       for r in rows if isinstance(r, dict))
        return _split_int(_tg_i(p, 'users'), n)[i]
    return 0  # Arrivals / 未知


def compute_shards(
    thread_groups_config: list[dict],
    available_lgs: list['LoadGenerator'],
    *,
    fallback_vusers: int = 1,
) -> tuple[list[Shard], int]:
    """按 thread_groups_config 把任务精确拆到各 agent，返回 (shards, dropped_agents)。

    精确拆分（不翻倍）：每个可拆字段（step_users / users / target_concurrency / rps /
    ultimate rows.users）用 _split_int 拆，各 agent 份额之和恒 = task 配置值。

    自动减 agent（点 2）：n_eff = min(选中 agent 数, 所有 TG useful 上限的最大值)。
    多出来的 agent 分不到活 → 弃用，dropped_agents 返回弃用台数供上层提示用户。
      - 3VU 2agent、S=1 → useful=1 → n_eff=1，dropped=1
      - 101VU 3agent、S=10 → useful=10 → n_eff=3，dropped=0

    余数给容量最大的台（点 3：sorted desc 后 _split_int 余数压前几份）。
    每片线程峰值 = 各 TG 拆分后线程数之和（derived），即 num_threads cap，再做容量校验
    —— 不能像旧实现独立拆 peak，否则 cap 会比真实峰值小、把最大那台截短（101/3 时
    旧法给 [34,34,33]，真实峰值 [41,30,30]，第一台被截到 34）。
    """
    if not available_lgs:
        raise ValueError('no available load generators')
    tgs = [t for t in (thread_groups_config or []) if isinstance(t, dict)]

    # 容量校验（总量）：所选 agent 合计要装得下总线程数
    total_planned = compute_planned_vusers_total(tgs, fallback=fallback_vusers)
    total_capacity = sum(lg.max_vusers for lg in available_lgs)
    if total_capacity < total_planned:
        raise ValueError(
            f'insufficient capacity: need {total_planned}, available {total_capacity} '
            f'across {len(available_lgs)} agents',
        )

    # 容量大的优先（扛余数 + 单台 cap 不够时早暴露）
    sorted_lgs = sorted(available_lgs, key=lambda lg: (-lg.max_vusers, lg.id))

    # n_eff：所有 TG useful 上限的最大值（任一 TG 能给某台派活 → 该台有用）
    governing = 0
    for t in tgs:
        governing = max(governing, _useful_agents_for_tg(
            t.get('kind') or 'ThreadGroup', t.get('params') or {},
        ))
    if governing <= 0:
        governing = 1  # 纯 Arrivals 且 rps 解析不出等极端兜底
    n_eff = max(1, min(len(sorted_lgs), governing))

    shards: list[Shard] = []
    for i in range(n_eff):
        lg = sorted_lgs[i]
        peak = sum(
            _shard_thread_peak(t.get('kind') or 'ThreadGroup', t.get('params') or {}, i, n_eff)
            for t in tgs
        )
        if peak > lg.max_vusers:
            raise ValueError(
                f'agent {lg.pod_name} cap={lg.max_vusers} 装不下 share={peak}：'
                f'拆分后该台超容量，建议加机器或减 vusers',
            )
        shards.append(Shard(
            index=i,
            load_generator_id=lg.id,
            pod_name=lg.pod_name,
            base_url=lg.base_url,
            vusers=peak,
        ))
    dropped = len(available_lgs) - n_eff
    return shards, dropped


# ── jmx 切片 ────────────────────────────────────────────────────────────

def _split_tg_params(kind: str, params: dict, i: int, n: int) -> tuple[dict, bool]:
    """算第 i 片（共 n 片）某 TG 的参数。返回 (new_params, disable)。

    disable=True 表示该片分不到这个 TG（min=1 的字段被拆成 0）→ 调用方禁用该 TG，
    **不能留原配置**（否则 base xml 里的全量 TG 会照跑 = 翻倍 bug 重现）。
    Stepping 的 step_users/initial 允许 0（min=0），拆成 0 也合法（0 线程），不禁用。
    """
    p = params or {}
    if kind == 'ThreadGroup':
        u = _split_int(_tg_i(p, 'users') or _tg_i(p, 'num_threads'), n)[i]
        if u <= 0:
            return {}, True
        return {
            'users': u,
            'ramp_up': _tg_i(p, 'ramp_up') or _tg_i(p, 'ramp_time'),
            'duration': _tg_i(p, 'duration'),
        }, False
    if kind == 'SteppingThreadGroup':
        return {
            'initial_threads': _split_int(_tg_i(p, 'initial_threads'), n)[i],
            'step_users': _split_int(_tg_i(p, 'step_users'), n)[i],
            'step_delay': _tg_i(p, 'step_delay'),
            'step_count': _tg_i(p, 'step_count'),
            'hold': _tg_i(p, 'hold'),
            'shutdown': _tg_i(p, 'shutdown'),
        }, False
    if kind == 'ConcurrencyThreadGroup':
        tc = _split_int(_tg_i(p, 'target_concurrency'), n)[i]
        if tc <= 0:
            return {}, True
        return {
            'target_concurrency': tc,
            'ramp_up': _tg_i(p, 'ramp_up'),
            'steps': _tg_i(p, 'steps') or 1,
            'hold': _tg_i(p, 'hold'),
            'unit': p.get('unit') or 'S',
        }, False
    if kind == 'ArrivalsThreadGroup':
        rps = _split_int(_tg_i(p, 'target_rps'), n)[i]
        if rps <= 0:
            return {}, True
        return {
            'target_rps': rps,
            'ramp_up': _tg_i(p, 'ramp_up'),
            'steps': _tg_i(p, 'steps') or 1,
            'hold': _tg_i(p, 'hold'),
            'unit': p.get('unit') or 'M',
        }, False
    if kind == 'UltimateThreadGroup':
        rows = p.get('rows')
        if isinstance(rows, list) and rows:
            new_rows = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                ru = _split_int(int(r.get('users') or 0), n)[i]
                if ru <= 0:
                    continue  # users 不能为 0：这片分不到这行 → 丢掉该行
                new_rows.append({
                    'users': ru,
                    'initial_delay': int(r.get('initial_delay') or 0),
                    'ramp_up': int(r.get('ramp_up') or 0),
                    'hold': int(r.get('hold') or 0),
                    'shutdown': int(r.get('shutdown') or 0),
                })
            if not new_rows:
                return {}, True
            return {'rows': new_rows}, False
        # 老单行兼容
        u = _split_int(_tg_i(p, 'users'), n)[i]
        if u <= 0:
            return {}, True
        return {
            'users': u,
            'initial_delay': _tg_i(p, 'initial_delay'),
            'ramp_up': _tg_i(p, 'ramp_up'),
            'hold': _tg_i(p, 'hold'),
            'shutdown': _tg_i(p, 'shutdown'),
        }, False
    return {}, False  # 未知 kind：不动（disable=False + 空 params → 原样保留）


def _apply_shard_split(
    xml_bytes: bytes,
    thread_groups_config: list[dict],
    shard_index: int,
    n_shards: int,
) -> bytes:
    """把 base xml（已含 Step 2 全量 TG 配置）里每个 enabled TG 改写成第 shard_index 片的
    精确份额。n_shards<=1 时不动（单 agent 跑全量 = 与非分布式完全一致）。

    驱动数据 = task.thread_groups_config（build_run_xml 同源），不再 re-parse xml。
    """
    if n_shards <= 1:
        return xml_bytes
    out = xml_bytes
    for tg in thread_groups_config:
        if not isinstance(tg, dict):
            continue
        path = tg.get('path')
        if not path:
            continue
        kind = tg.get('kind') or 'ThreadGroup'
        new_params, disable = _split_tg_params(kind, tg.get('params') or {}, shard_index, n_shards)
        try:
            if disable:
                out = toggle_component(out, path=path, enabled=False)
            elif new_params:
                out = replace_thread_group(out, path=path, kind=kind, params=new_params)
            # new_params 空且未 disable（未知 kind）→ 原样保留
        except JmxParseError:
            # path 在 build_run_xml 之后理论上一定有效；脏数据跳过（保留原配置）
            continue
    return out


def build_shard_jmx(
    task: 'Task',
    *,
    run_id: str,
    shard: Shard,
    total_shards: int,
    influxdb_url: str,
    influxdb_db: str,
) -> bytes:
    """
    生成本分片的可执行 JMX：
      Step 2 完整 xml → 按 (shard.index, total_shards) 精确拆 TG 到本分片
      → 注入 BackendListener（带 host tag）

    total_shards 由 _run_distributed 传 len(shards)，也是 _apply_shard_split 拆分的分母。
    """
    # 先拿基础 xml（含 Step 2 thread-groups + csv-bindings + DNS 注入）
    # 不让 build_run_xml 注入 BackendListener，scheduler 自己加（要带 host tag）
    base = build_run_xml(
        task,
        inject_environment_dns=True,
        inject_backend_listener=False,
    )
    # 按分片精确拆 TG（驱动数据 = task.thread_groups_config，与 base 同源）
    sliced = _apply_shard_split(
        base, task.thread_groups_config or [], shard.index, total_shards,
    )

    # 阶段 3：CSVDataSet filename 改写到 agent 端相对路径 csv/<filename>。
    # build_run_xml 第 2 步已经 patch 成宿主 scripts/ 的绝对路径（LOCAL_FALLBACK 用），
    # 这里覆盖回相对路径；JMeter 按 jmx 所在目录解析 → agent 把 csv 写到
    # <work_dir>/csv/<filename>，正好对得上。executor 配套作 multipart 上传 csv_files。
    for binding in task.csv_bindings.all():
        if not binding.component_path or not binding.filename:
            continue
        try:
            sliced = _set_csv_filename_at_path(
                sliced, binding.component_path, f'csv/{binding.filename}',
            )
        except JmxParseError:
            # path 在 build_run_xml 之后理论上一定有效；脏数据跳过
            continue

    # 每个 enabled TG 各注入一个 BackendListener（详见 jmx._inject_backend_listener_per_tg
    # 的注释）；每个 listener 额外带 host/shard tag，前端"按主机"切线时仍能区分 pod。
    sliced = _inject_backend_listener_per_tg(
        sliced,
        run_id=run_id,
        task_id=task.id,
        influxdb_url=influxdb_url,
        influxdb_db=influxdb_db,
        extra_tags={
            'host': shard.pod_name,
            'shard': str(shard.index),
            'shard_count': str(max(1, total_shards)),
        },
    )
    # 注入 SimpleDataWriter（仅失败样本带 body）→ agent 端 work_dir/errors.xml；
    # 相对路径，JMeter cwd=jmx 所在目录，写到 work_dir 根下。主控拉回合并给前端
    # ErrorByEndpointTable 的 message 列拿真实 response body。
    final = _inject_error_response_listener(sliced, errors_xml_path='errors.xml')
    return final


# ── CSV 切片 ────────────────────────────────────────────────────────────

def slice_csv_by_offset(
    src_path: Path,
    shard_index: int,
    shard_count: int,
    *,
    encoding: str = 'utf-8',
    has_header: bool = True,
) -> bytes:
    """
    按行号取模分片：第 N 个 shard 拿 (row_index % shard_count == N) 的数据行。
    - has_header=True 时第一行 header 各 shard 都保留
    - 用户在 CSVDataSet 里设的 ignoreFirstLine 决定 header 是否跳过——这里只管切，
      不管语义；主控写 jmx 时保持原 ignoreFirstLine 设置即可
    """
    if shard_count < 1:
        raise ValueError('shard_count must be ≥ 1')
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError(f'shard_index {shard_index} out of range [0, {shard_count})')

    out = io.BytesIO()
    with src_path.open('r', encoding=encoding, newline='') as f:
        reader = csv.reader(f)
        writer = csv.writer(io.TextIOWrapper(out, encoding=encoding, newline='', write_through=True))
        for row_idx, row in enumerate(reader):
            if has_header and row_idx == 0:
                writer.writerow(row)
                continue
            data_idx = row_idx - (1 if has_header else 0)
            if data_idx % shard_count == shard_index:
                writer.writerow(row)
    return out.getvalue()
