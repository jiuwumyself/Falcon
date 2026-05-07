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
    JmxParseError, _inject_backend_listener, build_run_xml, list_thread_groups,
    replace_thread_group,
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


# ── 分配 ────────────────────────────────────────────────────────────────

def compute_shards(
    vusers: int,
    available_lgs: list['LoadGenerator'],
) -> list[Shard]:
    """
    按 max_vusers 容量分配 vusers 到各 agent。
    - capacity 大的优先分配（避免小机被堆满）
    - 每台不超过自己的 max_vusers
    - 总 capacity 不够时返回 ValueError，由调用方决定是否扩容

    返回的 Shard 每个 vusers 都 ≥ 1。
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

    # 容量大的优先；同容量时按 id 稳定排
    sorted_lgs = sorted(available_lgs, key=lambda lg: (-lg.max_vusers, lg.id))
    remaining = vusers
    shards: list[Shard] = []
    for i, lg in enumerate(sorted_lgs):
        take = min(remaining, lg.max_vusers)
        if take <= 0:
            break
        shards.append(Shard(
            index=i,
            load_generator_id=lg.id,
            pod_name=lg.pod_name,
            base_url=lg.base_url,
            vusers=take,
        ))
        remaining -= take
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
    influxdb_url: str,
    influxdb_db: str,
) -> bytes:
    """
    生成本分片的可执行 JMX：
      Step 2 完整 xml → 缩 TG 参数到本分片 → 注入 BackendListener（带 host tag）
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
            'shard_count': str(max(1, math.ceil(total_vusers / max(shard.vusers, 1)))),
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
