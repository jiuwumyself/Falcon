"""
Pinpoint slow trace collector（v1.3 接入 v0）。

run 终态时由 executor._on_finish 异步触发：
  1. 拿 P99 阈值（来自 InfluxDB query_run_summary）
  2. 遍历 task.service_names 中有 Service.pinpoint_app 的服务
  3. 调 pinpoint.query_slow_traces 拉慢 trace
  4. 入 RunPinpointTrace 表

整流程**失败静默**——Pinpoint 不可达 / Service 表没配 / P99 拿不到都不阻塞 run
终态写入。collector 是"额外信号"层，缺数据时前端显示"未拉到 trace"占位即可。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models import TaskRun


# P99 拿不到时的兜底比例（mean × 此值作为 elapsed 阈值；对 Pinpoint 来说宁可严
# 一点也不要拉太多）
_FALLBACK_P99_MULT = 3.0
# 单 service 最多存的 slow trace 条数
_LIMIT_PER_SERVICE = 100


def collect_for_run(run: 'TaskRun') -> dict:
    """
    主入口。同步返回 {service_name: trace_count} 统计；调用方一般在 daemon thread
    里调，结果用于日志/调试，非业务路径关键。

    失败模式：
      - PinpointConfig 不可达 → 整个 collect 跳过，返 {}
      - 单 service 拉失败 → 该 service trace 数为 0，其他继续
      - 入库 IntegrityError（重复 trace_id 同 run）→ 跳过该条，不打断
    """
    from ..models import (  # noqa: PLC0415
        PinpointConfig, RunPinpointTrace, Service,
    )
    from . import influxdb as influxdb_svc  # noqa: PLC0415
    from . import pinpoint as pinpoint_svc  # noqa: PLC0415

    result: dict[str, int] = {}

    # 1) 全局开关检查
    try:
        cfg = PinpointConfig.get_config()
    except Exception:  # noqa: BLE001
        return result
    if not cfg.enabled or not cfg.base_url:
        return result

    # 2) 拿 P99 阈值
    p99_threshold = _get_p99_threshold(run, influxdb_svc)

    # 3) 时间窗（毫秒 epoch）
    if not run.started_at:
        return result
    from_ts = int(run.started_at.timestamp() * 1000)
    if run.finished_at:
        to_ts = int(run.finished_at.timestamp() * 1000)
    else:
        # 终态但 finished_at 没填的极少数情况，扩 5 分钟兜底
        from datetime import timedelta  # noqa: PLC0415
        to_ts = int((run.started_at + timedelta(minutes=5)).timestamp() * 1000)

    # 4) 遍历 task.service_names 拉 slow traces
    service_names = run.task.service_names or []
    if not service_names:
        return result

    services_by_name = {
        s.name: s for s in Service.objects.filter(name__in=service_names)
    }

    for service_name in service_names:
        svc = services_by_name.get(service_name)
        if not svc or not svc.pinpoint_app:
            continue  # 该服务没配 Pinpoint application，跳过

        traces = pinpoint_svc.query_slow_traces(
            application=svc.pinpoint_app,
            from_ts=from_ts,
            to_ts=to_ts,
            p99_threshold_ms=p99_threshold,
            limit=_LIMIT_PER_SERVICE,
        )

        # 入库（重复 trace_id 跳过；ignore_conflicts 避免 IntegrityError 中断）
        objs = [
            RunPinpointTrace(
                run=run,
                service_name=service_name,
                trace_id=t['trace_id'],
                elapsed_ms=t['elapsed_ms'],
                start_ts_ms=t['start_ts_ms'],
                exception_type=t.get('exception_type', ''),
                pinpoint_detail_url=t.get('detail_url', ''),
            )
            for t in traces
        ]
        if objs:
            try:
                RunPinpointTrace.objects.bulk_create(objs, ignore_conflicts=True)
            except Exception:  # noqa: BLE001
                # 静默：collector 是辅助流程，不阻塞 run 终态
                pass

        result[service_name] = len(objs)

    return result


def _get_p99_threshold(run: 'TaskRun', influxdb_svc) -> int:
    """从 InfluxDB 拿 P99；拿不到时用 mean × 倍数兜底；都拿不到返 0（query 时
    elapsed > 0 都算 slow，等于全采）。"""
    try:
        summary = influxdb_svc.query_run_summary(run.run_id)
        p99 = int(summary.get('p99_ms') or 0)
        if p99 > 0:
            return p99
        # P99 拿不到（小 run 数据稀疏 / InfluxDB 不可达）→ run.p99_ms 兜底
        if run.p99_ms and run.p99_ms > 0:
            return int(run.p99_ms)
        # 仍拿不到，用 mean × 倍数（avg_rps 不能直接当延迟，需要 task 字段）
        # 简化：直接返 0，让 collector 拉全部 trace 也不太多（Pinpoint 自己 limit）
        return 0
    except Exception:  # noqa: BLE001
        return 0
