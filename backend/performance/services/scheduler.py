"""多机调度器（v1.2）。

职责：
  1. 按 vusers + 选中 LoadGenerator 列表算分片（每台一份）
  2. 给每个分片生成 jmx：
     - 复用 build_run_xml 拿到含 Step 2 完整配置的 xml
     - 把每个 enabled TG 的 num_threads 改成本分片对应数
     - BackendListener 注入加 host=pod_name tag（InfluxDB 切片用）
  3. 切 CSV 到分片本地：按行偏移 (row_index % shards == shard_index) 写到 work_dir/csv/
"""
from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .jmx import (
    JmxParseError, _inject_backend_listener, _set_csv_filename_at_path,
    build_run_xml, list_thread_groups, replace_thread_group,
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
        max_threads = _i('initial_threads') + _i('step_count') * _i('step_users')
        stop_users = _i('Stop users count', 1) or _i('stop_users_count', 1) or 1
        stop_period = _i('Stop users period') or _i('stop_users_period') or _i('shutdown', 5)
        # plugin 用驼峰；Step 2 表单可能给 'shutdown' 字段映射成 stop period
        shutdown_dur = -(-max_threads // max(stop_users, 1)) * stop_period  # ceil div
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

def compute_shards(
    vusers: int,
    available_lgs: list['LoadGenerator'],
) -> list[Shard]:
    """
    平均分配 vusers 到各 agent：floor(vusers/n) 平摊，余数压到容量最大的那台。

    - vusers=3, n=2 → [2, 1]  （base=1，余 1 给第一台）
    - vusers=10, n=3 → [4, 3, 3]
    - vusers=2, n=3 → [2, 0, 0]  （base=0，余 2 全给第一台；后两台不建 shard）
    - 异构容量 cap=[100, 50]、vusers=150 → 按容量降序后排成 [100,50]，
      base=75,余 0 → [75, 75]，但第二台 cap=50 不够 → 抛 ValueError 让用户加机器

    旧"贪心填充"会把 3 vusers 全塞第一台，第二台闲着——多机验证场景退化为单机。
    """
    if vusers <= 0:
        raise ValueError(f'vusers must be positive, got {vusers}')
    if not available_lgs:
        raise ValueError('no available load generators')

    total_capacity = sum(lg.max_vusers for lg in available_lgs)
    if total_capacity < vusers:
        raise ValueError(
            f'insufficient capacity: need {vusers}, available {total_capacity} '
            f'across {len(available_lgs)} agents',
        )

    # 容量大的优先（让"第一台"扛得住余数 + 单 agent cap 不够时早暴露）
    sorted_lgs = sorted(available_lgs, key=lambda lg: (-lg.max_vusers, lg.id))
    n = len(sorted_lgs)
    base = vusers // n
    remainder = vusers % n
    # 余数全给第一台
    shares = [base + remainder if i == 0 else base for i in range(n)]

    # 容量校验：异构 cap 时某台 share 可能超它自己的 max_vusers
    for lg, sh in zip(sorted_lgs, shares):
        if sh > lg.max_vusers:
            raise ValueError(
                f'agent {lg.pod_name} cap={lg.max_vusers} 装不下 share={sh}：'
                f'平均分配后该台超容量，建议加机器或减 vusers',
            )

    shards: list[Shard] = []
    for i, (lg, sh) in enumerate(zip(sorted_lgs, shares)):
        if sh <= 0:
            continue   # share=0 的 agent 不建 shard，避免起 0 thread 的 jmeter
        shards.append(Shard(
            index=i,
            load_generator_id=lg.id,
            pod_name=lg.pod_name,
            base_url=lg.base_url,
            vusers=sh,
        ))
    return shards


# ── jmx 切片 ────────────────────────────────────────────────────────────

def _scale_thread_groups_to_shard(
    xml_bytes: bytes,
    shard_vusers: int,
    total_vusers: int,
) -> bytes:
    """
    把 xml 中每个 enabled 的 ThreadGroup（标准 / 插件型）按比例缩到本分片。
    比如 total=120, shard=60 → 系数 0.5；每个 TG 的 users / target_concurrency /
    target_rps 字段乘 0.5（向上取整保证 ≥ 1）。
    """
    if total_vusers <= 0 or shard_vusers <= 0:
        return xml_bytes
    factor = shard_vusers / total_vusers
    if factor >= 1.0 - 1e-9:
        return xml_bytes  # 单机跑全部

    tgs = list_thread_groups(xml_bytes)
    out = xml_bytes
    for tg in tgs:
        if not tg['enabled']:
            continue
        kind = tg['kind']
        params = dict(tg['current_params'])
        # 按 kind 缩 vusers / RPS 字段
        if kind == 'ThreadGroup':
            users = params.get('users') or params.get('num_threads') or 1
            params = {
                'users': max(1, math.ceil(int(users) * factor)),
                'ramp_up': params.get('ramp_up') or params.get('ramp_time') or 0,
                'duration': params.get('duration') or 0,
            }
        elif kind == 'SteppingThreadGroup':
            init_t = params.get('initial_threads') or 0
            step_u = params.get('step_users') or 0
            params = {
                'initial_threads': max(0, math.ceil(int(init_t) * factor)),
                'step_users': max(1, math.ceil(int(step_u) * factor)),
                'step_delay': params.get('step_delay') or 0,
                'step_count': params.get('step_count') or 0,
                'hold': params.get('hold') or 0,
                'shutdown': params.get('shutdown') or 0,
            }
        elif kind == 'ConcurrencyThreadGroup':
            tc = params.get('target_concurrency') or 1
            params = {
                'target_concurrency': max(1, math.ceil(int(tc) * factor)),
                'ramp_up': params.get('ramp_up') or 0,
                'steps': params.get('steps') or 1,
                'hold': params.get('hold') or 0,
                'unit': params.get('unit') or 'S',
            }
        elif kind == 'UltimateThreadGroup':
            users = params.get('users') or 1
            params = {
                'users': max(1, math.ceil(int(users) * factor)),
                'initial_delay': params.get('initial_delay') or 0,
                'ramp_up': params.get('ramp_up') or 0,
                'hold': params.get('hold') or 0,
                'shutdown': params.get('shutdown') or 0,
            }
        elif kind == 'ArrivalsThreadGroup':
            rps = params.get('target_rps') or 1
            params = {
                'target_rps': max(1, math.ceil(float(rps) * factor)),
                'ramp_up': params.get('ramp_up') or 0,
                'steps': params.get('steps') or 1,
                'hold': params.get('hold') or 0,
                'unit': params.get('unit') or 'S',
            }
        else:
            continue  # 未知 kind 不动

        try:
            out = replace_thread_group(out, path=tg['path'], kind=kind, params=params)
        except JmxParseError:
            # path 在 build_run_xml 之后理论上一定有效；忽略边界情况
            continue
    return out


def build_shard_jmx(
    task: 'Task',
    *,
    run_id: str,
    shard: Shard,
    total_vusers: int,
    total_shards: int,
    influxdb_url: str,
    influxdb_db: str,
) -> bytes:
    """
    生成本分片的可执行 JMX：
      Step 2 完整 xml → 缩 TG 参数到本分片 → 注入 BackendListener（带 host tag）

    total_shards 由 _run_distributed 传 len(shards)；旧版本拿 total_vusers/shard.vusers
    现算，容量分配不均时各片算出来不一致（80+20+20 三片各报 2/6/6）。
    """
    # 先拿基础 xml（含 Step 2 thread-groups + csv-bindings + DNS 注入）
    # 不让 build_run_xml 注入 BackendListener，scheduler 自己加（要带 host tag）
    base = build_run_xml(
        task,
        inject_environment_dns=True,
        inject_backend_listener=False,
    )
    # 按分片缩 TG vusers
    sliced = _scale_thread_groups_to_shard(base, shard.vusers, total_vusers)

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

    # 注入带 host tag 的 BackendListener
    final = _inject_backend_listener(
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
