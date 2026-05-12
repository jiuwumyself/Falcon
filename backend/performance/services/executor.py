"""
RunExecutor — JMeter 子进程的生命周期编排（Step 3 主菜）。

每个 TaskRun 对应一个 RunExecutor 实例：
  pre_check → spawn JMeter → 心跳 + 取消监听 → 读 .jtl 算总结 → 归档
全程跑在 daemon=False 的子线程里，不阻塞 web 进程。

并发约束：
  - 同 task 串行：DB 唯一约束 unique_active_run_per_task 兜底，第二次启动直接 IntegrityError
  - 不同 task 不限并发：每个 run 一个独立线程 + 子进程

取消语义：
  - graceful 30s：子进程通过 stoptest 端口（默认 4445 起 + run hash）收 "StopTestNow"
  - 超时升级 SIGTERM → SIGKILL
"""
from __future__ import annotations

import csv
import os
import random
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone as dj_timezone

import requests

from . import influxdb as influxdb_svc
from . import jmx as jmx_svc
from . import pinpoint_collector as pinpoint_collector_svc
from . import scheduler as scheduler_svc
from . import jtl_merger
from .jmeter_runner import _augmented_env
from .jmeter import (
    archive_run_dir,
    cleanup_old_runs,
    ensure_jmeter_installed,
    ensure_plugins_installed,
    get_jmeter_bin,
    get_jmeter_home,
    get_run_dir,
    get_runs_dir,
)


# 模块级活跃 executor 注册表，cancel 走它定位线程
RUN_EXECUTORS: dict[str, 'RunExecutor'] = {}
_REGISTRY_LOCK = threading.Lock()

# JMeter stoptest 端口起点；不同 run 加 hash 偏移避免撞
_STOPTEST_PORT_BASE = 4445
_STOPTEST_PORT_RANGE = 1000

# graceful 取消超时 → SIGTERM → SIGKILL
# cancel 链路 worst case = HEARTBEAT(1s) + GRACEFUL + SIGTERM + SIGKILL(5s)
# JMeter 收到 StopTestNow 正常 1-2s 就退；5s 还不退基本卡死了，没必要陪它继续磨。
# 旧值 30/10 → 用户感觉点了取消等半天；改成 5/3 把 worst case 压到 ~14s。
_GRACEFUL_TIMEOUT_SEC = 5
_SIGTERM_TIMEOUT_SEC = 3

# 心跳间隔 + duration 超时余量
_HEARTBEAT_INTERVAL_SEC = 1.0
_DURATION_OVERRUN_SEC = 60

# P0 #3 early abort gate：跑足 GRACE_PERIOD 秒后开始检查，每 INTERVAL 秒查一次最近
# WINDOW 秒错误率，若总样本 ≥ MIN_TOTAL 且 error_rate ≥ THRESHOLD → 自动中止。
_EARLY_ABORT_GRACE_SEC = 30
_EARLY_ABORT_CHECK_INTERVAL_SEC = 5
_EARLY_ABORT_WINDOW_SEC = 30
_EARLY_ABORT_THRESHOLD = 0.80
_EARLY_ABORT_MIN_TOTAL = 50

# § 12 S1 事件锚点 heartbeat 扫描间隔：每 N 秒扫一次 first_sample / first_error / first_5xx
_RUNTIME_ANCHOR_INTERVAL_SEC = 5

# 分布式：每 N 秒把每台 agent 的 errors.xml 增量拉回主控
# 这样运行中前端 ErrorByEndpointTable 就能拿到真实失败 body（不再 100% HTTP_REASON 兜底）
_ERRORS_XML_PULL_INTERVAL_SEC = 10

# 分布式：每 N 秒把每台 agent 的 results.jtl 拉回主控 + 合并到 <run_dir>/results.jtl
# 聚合端点（error-samples?aggregate=true / sampler-stats）扫的是主控本地 results.jtl，
# 不拉 → 运行中聚合表只能等所有 agent 终态后才能出数据（用户看到的「暂无错误样本」）
_PULL_JTL_INTERVAL_SEC = 10

# 保留最新 N 个 run 目录，更老的自动归档为 tar.gz
_RUN_KEEP_COUNT = 20


def get_executor(run_id: str) -> 'RunExecutor | None':
    with _REGISTRY_LOCK:
        return RUN_EXECUTORS.get(run_id)


def register_executor(executor: 'RunExecutor') -> None:
    with _REGISTRY_LOCK:
        RUN_EXECUTORS[executor.run.run_id] = executor


def unregister_executor(run_id: str) -> None:
    with _REGISTRY_LOCK:
        RUN_EXECUTORS.pop(run_id, None)


class RunExecutor:
    def __init__(self, run):
        # 局部 import 避免循环依赖
        from ..models import TaskRun  # noqa: F401, PLC0415
        self.run = run
        self._thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None
        self._cancelled = threading.Event()
        # P0 #3 early abort：平台主动判定无效 run 时打标，_on_finish 据此标 FAILED
        # 而非 CANCELLED（区分"用户 cancel"vs"平台 abort 无效 run"）
        self._early_aborted = False
        # v1.2 多机调度状态
        self._selected_lgs: list = []                          # list[LoadGenerator]
        self._agent_runs: dict[int, dict] = {}                  # lg_id → {agent_run_id, base_url, jtl_path}
        self._agent_runs_lock = threading.Lock()
        # § 12 S1 实时锚点缓存：已写过的事件类型，heartbeat 跳过重复扫描
        self._anchors_recorded: set[str] = set()

    # ── public ─────────────────────────────────────────────

    def start(self) -> None:
        """注册到全局表，起子线程。立即返回。"""
        register_executor(self)
        self._thread = threading.Thread(
            target=self._worker_thread,
            name=f'falcon-run-{self.run.run_id}',
            daemon=False,
        )
        self._thread.start()

    def cancel(self) -> None:
        """触发 graceful cancel；线程会在心跳里看到这个 flag 走清理路径。"""
        self._cancelled.set()
        # 立即写 cancel_requested_at + status=cancelling
        from ..models import TaskRun, RunStatus  # noqa: PLC0415
        TaskRun.objects.filter(pk=self.run.pk).filter(
            status__in=[RunStatus.PRE_CHECKING, RunStatus.PENDING, RunStatus.RUNNING],
        ).update(
            status=RunStatus.CANCELLING,
            cancel_requested_at=dj_timezone.now(),
        )
        # 单机：子进程在跑则发 stoptest
        if self._proc and self._proc.poll() is None and self.run.stop_port:
            self._send_stoptest()
        # 多机：广播 cancel 到所有 agent
        with self._agent_runs_lock:
            agent_runs = list(self._agent_runs.items())
        for lg_id, info in agent_runs:
            try:
                requests.post(
                    f'{info["base_url"]}/runs/{info["agent_run_id"]}/cancel',
                    timeout=5,
                    headers=self._agent_headers(),
                )
            except requests.RequestException:
                pass

    # ── worker thread main ─────────────────────────────────

    def _worker_thread(self) -> None:
        """子线程入口：完整生命周期编排。"""
        # 子线程必须自己管理 DB 连接，否则会复用主线程的连接出错
        close_old_connections()
        try:
            from ..models import RunStatus  # noqa: PLC0415
            # 1) 预检
            ok, log = self._pre_check()
            self._update_run(pre_check_log=log)
            if not ok:
                self._update_run(
                    status=RunStatus.PRE_CHECK_FAILED,
                    error_message='环境检测未通过，详情见 pre_check_log',
                    finished_at=dj_timezone.now(),
                )
                return
            if self._cancelled.is_set():
                self._update_run(
                    status=RunStatus.CANCELLED,
                    finished_at=dj_timezone.now(),
                )
                return

            # 2) 决策走分布式 or 本地
            self._selected_lgs = self._select_load_generators()
            distributed = bool(self._selected_lgs)

            self._update_run(status=RunStatus.PENDING)

            if distributed:
                # 分布式路径（v1.2）：多 agent 并行
                self._update_run(
                    status=RunStatus.RUNNING,
                    started_at=dj_timezone.now(),
                    last_heartbeat_at=dj_timezone.now(),
                )
                self._pre_record_phase_anchors()
                exit_code = self._run_distributed()
            else:
                # 本地兜底路径：原 v1.1 单机流程
                run_jmx = self._build_and_write_run_jmx()
                stop_port = self._allocate_stop_port()
                self._update_run(
                    status=RunStatus.RUNNING,
                    stop_port=stop_port,
                    started_at=dj_timezone.now(),
                    last_heartbeat_at=dj_timezone.now(),
                )
                self._pre_record_phase_anchors()
                self._proc = self._spawn_jmeter(run_jmx, stop_port)
                self._update_run(pid=self._proc.pid)
                exit_code = self._heartbeat_loop(self._proc)

            # 5) 总结 + 归档（两路径共用）
            self._on_finish(exit_code)
        except Exception:  # noqa: BLE001
            from ..models import RunStatus  # noqa: PLC0415
            err = traceback.format_exc()
            self._update_run(
                status=RunStatus.FAILED,
                error_message=err[-2000:],
                finished_at=dj_timezone.now(),
            )
        finally:
            unregister_executor(self.run.run_id)
            close_old_connections()

    # ── pre check ──────────────────────────────────────────

    def _flush_pre_check_log(self, lines: list[str]) -> None:
        """把当前累积的预检日志同步写回 DB，让前端 3s 轮询能看到逐项点亮。"""
        self._update_run(pre_check_log='\n'.join(lines))

    def _pre_check(self) -> tuple[bool, str]:
        """返回 (ok, 多行日志)。任一项失败 ok=False。每跑完一项 flush 一次。"""
        lines: list[str] = []
        ok = True

        # 1) JMeter 二进制
        try:
            ensure_jmeter_installed()
            ensure_plugins_installed()
            jbin = get_jmeter_bin()
            if not jbin.exists():
                ok = False
                lines.append(f'❌ JMeter 二进制缺失: {jbin}')
            else:
                lines.append(f'✅ JMeter: {jbin}')
        except Exception as e:  # noqa: BLE001
            ok = False
            lines.append(f'❌ JMeter 安装失败: {e}')
        self._flush_pre_check_log(lines)

        # 2) 脚本检查
        task = self.run.task
        try:
            jmx_path = task.jmx_path()
            if not jmx_path.exists():
                ok = False
                lines.append(f'❌ JMX 文件不存在: {jmx_path}')
            else:
                lines.append(f'✅ JMX 原件: {jmx_path.name}')
            if not task.thread_groups_config:
                ok = False
                lines.append('❌ Step 2 任务配置为空，请先完成场景配置')
            else:
                lines.append(f'✅ Step 2 配置: {len(task.thread_groups_config)} 个 ThreadGroup')
            # build_run_xml 试运行
            jmx_svc.build_run_xml(
                task,
                inject_environment_dns=bool(task.environment_id),
                inject_backend_listener=True,
                run_id=self.run.run_id,
            )
            lines.append('✅ 可执行 XML 组装通过')
        except Exception as e:  # noqa: BLE001
            ok = False
            lines.append(f'❌ 脚本检查失败: {e}')
        self._flush_pre_check_log(lines)

        # 3) 磁盘空间
        try:
            usage = shutil.disk_usage(get_runs_dir())
            free_mb = usage.free // (1024 * 1024)
            if free_mb < 100:
                ok = False
                lines.append(f'❌ 磁盘空间不足: 剩余 {free_mb} MB < 100 MB')
            else:
                lines.append(f'✅ 磁盘空间: 剩余 {free_mb} MB')
        except Exception as e:  # noqa: BLE001
            ok = False
            lines.append(f'❌ 磁盘检查失败: {e}')
        self._flush_pre_check_log(lines)

        # 4) InfluxDB
        try:
            if influxdb_svc.ping():
                lines.append(f'✅ InfluxDB: {settings.INFLUXDB_URL} ({settings.INFLUXDB_DB})')
            else:
                ok = False
                lines.append(
                    f'❌ InfluxDB 不可达: {getattr(settings, "INFLUXDB_URL", "(未配置)")} '
                    '请确认服务已启动且数据库存在（manage.py setup_influxdb）'
                )
        except Exception as e:  # noqa: BLE001
            ok = False
            lines.append(f'❌ InfluxDB 检查异常: {e}')
        self._flush_pre_check_log(lines)

        # 5) Environment hosts TCP 探测
        # host_entries 兼容两种格式（同 _inject_dns_cache_manager）：
        #   - dict {"hostname": "...", "ip": "..."}
        #   - str "10.0.0.1 hostname.foo.com"（/etc/hosts 风格 + # 注释）
        # 用 jmx_svc._parse_host_entry 统一规范化。
        # 随机抽 10 条，只汇总通过 / 未通过数；不阻塞 ok（内网未开 80/443 也常见）。
        if task.environment_id and task.environment.host_entries:
            parsed: list[tuple[str, str]] = []
            for entry in task.environment.host_entries:
                pair = jmx_svc._parse_host_entry(entry)
                if pair:
                    parsed.append(pair)
            if not parsed:
                lines.append('ℹ️  Environment hosts 全部无法解析，跳过 TCP 探测')
            else:
                sample_size = min(10, len(parsed))
                sample = random.sample(parsed, sample_size)
                passed = 0
                failed = 0
                for _host, ip in sample:
                    reachable = False
                    for port in (80, 443):
                        try:
                            with socket.create_connection((ip, port), timeout=2):
                                reachable = True
                                break
                        except OSError:
                            continue
                    if reachable:
                        passed += 1
                    else:
                        failed += 1
                suffix = f'（共 {len(parsed)} 条，随机抽 {sample_size} 条）'
                if failed == 0:
                    lines.append(f'✅ Environment hosts: {passed}/{sample_size} TCP 可达 {suffix}')
                else:
                    lines.append(
                        f'⚠️  Environment hosts: {passed}/{sample_size} TCP 可达，'
                        f'{failed} 未通过（非致命）{suffix}'
                    )
        self._flush_pre_check_log(lines)

        # 6) 压力源（agent）
        # 判定与 _select_load_generators 对齐：status=idle 且心跳 ≤ 3 min。
        # 未选 agent / 全不可用时，按 settings.LOCAL_FALLBACK 决定是否拒绝。
        from datetime import timedelta  # noqa: PLC0415
        from django.utils import timezone as _tz  # noqa: PLC0415
        from ..models import LoadGeneratorStatus  # noqa: PLC0415

        local_fallback = bool(getattr(settings, 'LOCAL_FALLBACK', True))
        selected = list(self.run.load_generators.all())

        if not selected:
            if local_fallback:
                lines.append('✅ 压力源: 未选 agent，走本地 JMeter 兜底（LOCAL_FALLBACK=1）')
            else:
                ok = False
                lines.append('❌ 压力源: 未选 agent，且本地兜底已关闭（LOCAL_FALLBACK=0）')
        else:
            cutoff = _tz.now() - timedelta(minutes=3)
            usable = []
            issues: list[str] = []
            for lg in selected:
                fresh = lg.last_heartbeat_at and lg.last_heartbeat_at >= cutoff
                if lg.status == LoadGeneratorStatus.IDLE and fresh:
                    usable.append(lg)
                else:
                    reason = '心跳过期' if not fresh else lg.status
                    issues.append(f'{lg.pod_name}({reason})')

            if usable:
                capacity = sum(lg.max_vusers for lg in usable)
                msg = f'✅ 压力源: {len(usable)}/{len(selected)} 台可用，容量合计 {capacity} VU'
                if issues:
                    msg += f'（不可用: {", ".join(issues)}）'
                lines.append(msg)
                if capacity < self.run.virtual_users:
                    ok = False
                    lines.append(
                        f'❌ 压力源容量不足: 可用合计 {capacity} VU '
                        f'< 任务需要 {self.run.virtual_users} VU'
                    )
            elif local_fallback:
                lines.append(
                    f'⚠️  压力源: 选了 {len(selected)} 台全不可用'
                    f'（{", ".join(issues)}），将走本地兜底'
                )
            else:
                ok = False
                lines.append(
                    f'❌ 压力源: 选了 {len(selected)} 台全不可用'
                    f'（{", ".join(issues)}），本地兜底已关闭（LOCAL_FALLBACK=0）'
                )
        self._flush_pre_check_log(lines)

        return ok, '\n'.join(lines)

    # ── v1.2 多机调度 ───────────────────────────────────────

    def _select_load_generators(self) -> list:
        """从 TaskRun.load_generators M2M 拿用户 Step 3 选的 agent 集合。
        要求：status=idle **且** 心跳新鲜（≤ 3 min）。心跳过老的 idle 是
        release_idle_agents 还没跑过的"假活"行，POST 给它会 connection refused。
        全部失效 → 返回空 → 走本地兜底（如果 LOCAL_FALLBACK 关了，pre_check 已经拒绝）。"""
        from datetime import timedelta  # noqa: PLC0415
        from django.utils import timezone as _tz  # noqa: PLC0415
        from ..models import LoadGeneratorStatus  # noqa: PLC0415
        cutoff = _tz.now() - timedelta(minutes=3)
        lgs = list(
            self.run.load_generators
                .filter(status=LoadGeneratorStatus.IDLE, last_heartbeat_at__gte=cutoff)
        )
        return lgs

    def _agent_headers(self) -> dict:
        token = getattr(settings, 'FALCON_AGENT_TOKEN', '') or ''
        h = {}
        if token:
            h['Authorization'] = f'Bearer {token}'
        return h

    def _pull_agent_jtls_and_merge(self, run_dir: Path) -> None:
        """周期性把每台 agent 的 jtl 拉回主控 + merge 到 <run_dir>/results.jtl。

        - 拉每台 agent /runs/:id/jtl，覆盖写 <run_dir>/<pod_name>.jtl
        - 调 jtl_merger.merge_jtls 写到 <run_dir>/.results.jtl.tmp 再原子 replace
          为 results.jtl（防聚合端点读到半写文件）
        - 拉空 / 404 / 网络错都静默；只要至少一台 agent 有数据就能合并出非空 jtl
        - 终态后 _run_distributed 仍会跑一次最终 merge（见下方代码），覆盖此处运行
          中拿到的"截断"快照
        """
        with self._agent_runs_lock:
            agent_runs = list(self._agent_runs.values())

        jtl_paths: list[Path] = []
        for info in agent_runs:
            try:
                r = requests.get(
                    f'{info["base_url"]}/runs/{info["agent_run_id"]}/jtl',
                    timeout=30, headers=self._agent_headers(), stream=True,
                )
                if r.status_code != 200:
                    continue
                target = info['jtl_path']
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_suffix('.jtl.tmp')
                with tmp.open('wb') as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                tmp.replace(target)
                jtl_paths.append(target)
            except (requests.RequestException, OSError):
                continue

        if not jtl_paths:
            return

        merged_final = run_dir / 'results.jtl'
        merged_tmp = run_dir / '.results.jtl.tmp'
        try:
            jtl_merger.merge_jtls(jtl_paths, merged_tmp)
            merged_tmp.replace(merged_final)
        except Exception as e:  # noqa: BLE001
            print(f'[executor] WARN: runtime jtl merge failed: {e}', file=sys.stderr)
            try:
                merged_tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def _pull_agent_errors_xml(self, run_dir: Path) -> None:
        """把每台 agent 的 errors.xml 拉回主控 <run_dir>/errors_<pod>.xml。

        - 覆盖写（不增量）：每个 agent 的 errors.xml 流式 append，每次 GET 拿当时
          全量；views.error_samples 的 iterparse(recover=True) 能读未闭合 XML。
        - 写盘走 .tmp + os.replace 原子切换，避免主控并发读到半写文件。
        - 404 / 网络错 / IO 错都静默——拉不到时前端自然 fallback 到 HTTP_REASON。
        """
        with self._agent_runs_lock:
            agent_runs = list(self._agent_runs.values())
        for info in agent_runs:
            try:
                r = requests.get(
                    f'{info["base_url"]}/runs/{info["agent_run_id"]}/errors-xml',
                    timeout=15, headers=self._agent_headers(), stream=True,
                )
                if r.status_code != 200:
                    continue
                pod = info.get('pod_name') or 'agent'
                err_path = run_dir / f'errors_{pod}.xml'
                tmp_path = err_path.with_suffix('.xml.tmp')
                with tmp_path.open('wb') as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                tmp_path.replace(err_path)
            except (requests.RequestException, OSError):
                continue

    def _run_distributed(self) -> int:
        """
        多 agent 编排：
          1. compute_shards 算每台 vusers
          2. 给每台 build_shard_jmx → POST /runs (multipart)
          3. 心跳轮询每台 agent /runs/:id 状态
          4. 全部退出后 GET /jtl 拉回各文件 → jtl_merger.merge_jtls 写到 run_dir/results.jtl
        返 exit_code 兼容 _on_finish 的语义（0=success / 非 0=failed）
        """
        from ..models import RunStatus  # noqa: PLC0415
        run_dir = get_run_dir(self.run.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        # 总并发要走 thread_groups_config 聚合：task.virtual_users 是 jmx parse 时
        # 的初值（来自第一个标准 TG，可能 = 1 或解析兜底），多 TG 场景严重失真 →
        # compute_shards 拿到偏小的 vusers，share 算少甚至只塞第一台 agent。
        # snapshot 优先（已快照当时的 TG 配置），无 snapshot 走当前 task 配置兜底。
        tg_cfgs = (
            self.run.thread_groups_config_snapshot
            or self.run.task.thread_groups_config
            or []
        )
        total_vusers = scheduler_svc.compute_planned_vusers_total(
            tg_cfgs, fallback=self.run.virtual_users or 1,
        )
        shards = scheduler_svc.compute_shards(total_vusers, self._selected_lgs)
        # 每台 agent 起一个分片任务
        for shard in shards:
            shard_jmx = scheduler_svc.build_shard_jmx(
                self.run.task,
                run_id=self.run.run_id,
                shard=shard,
                total_vusers=total_vusers,
                total_shards=len(shards),
                # 分布式：jmx 在 agent 容器里跑，烤进容器可达的 InfluxDB URL
                # （主控自己读 InfluxDB 仍走 settings.INFLUXDB_URL）
                influxdb_url=getattr(
                    settings, 'AGENT_INFLUXDB_URL', getattr(settings, 'INFLUXDB_URL', ''),
                ),
                influxdb_db=getattr(settings, 'INFLUXDB_DB', 'jmeter'),
            )
            files = [('jmx_file', ('run.jmx', shard_jmx, 'application/xml'))]
            # 阶段 3：把 task.csv_bindings 的 CSV 文件作 multipart 上传给 agent。
            # build_shard_jmx 已经把 CSVDataSet filename 改成 'csv/<filename>'（agent 端
            # 相对路径），agent main.py 收到 csv_files 后写到 <work_dir>/csv/<filename>，
            # JMeter 按 jmx 所在目录解析相对路径，对得上。
            #
            # 切片开关 settings.CSV_SLICE_ENABLED：
            #   - False（默认）→ 全量副本（字典表 / 共享参数场景）
            #   - True → slice_csv_by_offset 按行模 (row_idx % shard_count == shard_index)
            #     切片，各 agent 只拿自己那部分（账号池等"数据只能用一次"场景）
            csv_slice = getattr(settings, 'CSV_SLICE_ENABLED', False)
            from .jmeter import get_scripts_dir  # noqa: PLC0415
            scripts_dir = get_scripts_dir()
            for binding in self.run.task.csv_bindings.all():
                if not binding.component_path or not binding.filename:
                    continue
                src = scripts_dir / binding.filename
                if not src.exists():
                    print(f'[executor] WARN: csv binding {binding.filename} 物理文件不存在，跳过',
                          file=sys.stderr)
                    continue
                if csv_slice and len(shards) > 1:
                    try:
                        payload = scheduler_svc.slice_csv_by_offset(
                            src, shard_index=shard.index, shard_count=len(shards),
                        )
                    except Exception as e:  # noqa: BLE001
                        # 切片失败（编码 / 格式异常）→ 兜底全量副本，不阻断 run
                        print(f'[executor] WARN: csv slice {binding.filename} 失败兜底全量: {e}',
                              file=sys.stderr)
                        payload = src.read_bytes()
                else:
                    payload = src.read_bytes()
                files.append((
                    'csv_files',
                    (binding.filename, payload, 'text/csv'),
                ))
            try:
                r = requests.post(
                    f'{shard.base_url}/runs',
                    data={'master_run_id': self.run.run_id},
                    files=files,
                    timeout=30,
                    headers=self._agent_headers(),
                )
                r.raise_for_status()
                data = r.json()
            except (requests.RequestException, ValueError) as e:
                self._update_run(error_message=f'agent {shard.pod_name} POST /runs 失败: {e}')
                return 1
            with self._agent_runs_lock:
                self._agent_runs[shard.load_generator_id] = {
                    'agent_run_id': data['run_id'],
                    'pid': data.get('pid'),
                    'base_url': shard.base_url,
                    'pod_name': shard.pod_name,
                    'jtl_path': run_dir / f'{shard.pod_name}.jtl',
                    'finished': False,
                    'exit_code': None,
                }

        # 心跳轮询：1s 间隔；max_wall 同单机版（ramp + duration + DURATION_OVERRUN）
        # P0 #1：max_wall 按 TG kind 算（旧公式 ramp+duration+60 不适配 Stepping/
        # Concurrency/Ultimate/Arrivals 这些 plugin TG，导致实际 145s 算成 125s 误标
        # timeout）。estimate_max_wall_sec 会取所有启用 TG 的 max（并行），最少 1 秒。
        tg_cfg = self.run.task.thread_groups_config or []
        fallback = self.run.duration_seconds or 0
        max_wall = (
            scheduler_svc.estimate_max_wall_sec(tg_cfg, fallback) + _DURATION_OVERRUN_SEC
            if (tg_cfg or fallback)
            else 0
        )
        start_t = time.monotonic()
        last_abort_check = start_t
        last_anchor_check = start_t
        last_errors_pull = start_t
        last_jtl_pull = start_t
        any_failed = False
        early_aborted = False

        while True:
            self._update_run(last_heartbeat_at=dj_timezone.now())

            with self._agent_runs_lock:
                pending = [
                    (lg_id, info) for lg_id, info in self._agent_runs.items()
                    if not info['finished']
                ]

            if not pending:
                break

            if self._cancelled.is_set():
                # cancel 已经在 cancel() 里广播过了；这里继续等终态
                pass

            now = time.monotonic()

            # § 12 S1：实时锚点扫描（first_sample / first_error / first_5xx）
            # 分布式时本地 results.jtl 还没合并 → JTL 扫描会自动 skip；first_error 走
            # InfluxDB 查得到（所有 agent 写同一 measurement）。
            if (now - last_anchor_check) > _RUNTIME_ANCHOR_INTERVAL_SEC:
                last_anchor_check = now
                self._record_runtime_anchors()

            # 周期性拉 agent errors.xml 到主控（覆盖写 errors_<pod>.xml）。
            # JMeter SimpleDataWriter 流式 append，运行中文件已有部分失败样本 body；
            # 主控 aggregates 端点 iterparse(recover=True) 能读未闭合 XML。
            # 不拉 → 运行中 body_index 空 → message 列 100% 走 HTTP_REASON 兜底。
            if (now - last_errors_pull) > _ERRORS_XML_PULL_INTERVAL_SEC:
                last_errors_pull = now
                self._pull_agent_errors_xml(run_dir)

            # 周期性拉 agent results.jtl 到主控 + merge 到 <run_dir>/results.jtl。
            # 聚合端点（error-samples?aggregate / sampler-stats）扫的就是这个文件；
            # 不拉 → 运行中聚合表只能等所有 agent 终态后才有数据（用户看到的「暂无错误样本」）。
            if (now - last_jtl_pull) > _PULL_JTL_INTERVAL_SEC:
                last_jtl_pull = now
                self._pull_agent_jtls_and_merge(run_dir)

            # P0 #3 early abort gate（与单机版同逻辑）：grace 后查最近 30s 错误率
            if (
                not early_aborted
                and (now - start_t) > _EARLY_ABORT_GRACE_SEC
                and (now - last_abort_check) > _EARLY_ABORT_CHECK_INTERVAL_SEC
            ):
                last_abort_check = now
                abort_msg = self._check_early_abort()
                if abort_msg:
                    early_aborted = True
                    self._early_aborted = True
                    self._record_event_anchor(
                        'error_rate_breached',
                        ts_ms=int(time.time() * 1000),
                        metadata={'message': abort_msg[:200]},
                    )
                    self._update_run(
                        status=RunStatus.CANCELLING,
                        error_message=abort_msg,
                    )
                    # 广播 cancel 给所有 pending agent
                    for lg_id, info in pending:
                        try:
                            requests.post(
                                f'{info["base_url"]}/runs/{info["agent_run_id"]}/cancel',
                                timeout=5, headers=self._agent_headers(),
                            )
                        except requests.RequestException:
                            pass
                    # _on_finish 终态决策时按 status=CANCELLING 走 cancelled 分支会丢
                    # error_message——这里改预期：循环退出后单独标 failed
                    # 标 failed 而非 cancelled——平台主动判定无效
                    # 这里不能立即 break，要等所有 agent 拿到终态；下个循环 cancel
                    # 完成后 pending 空自然 break

            if max_wall and (now - start_t) > max_wall:
                # duration 超时：广播 cancel，标 timeout
                self._update_run(status=RunStatus.CANCELLING)
                for lg_id, info in pending:
                    try:
                        requests.post(
                            f'{info["base_url"]}/runs/{info["agent_run_id"]}/cancel',
                            timeout=5, headers=self._agent_headers(),
                        )
                    except requests.RequestException:
                        pass
                self._update_run(status=RunStatus.TIMEOUT)

            for lg_id, info in pending:
                try:
                    r = requests.get(
                        f'{info["base_url"]}/runs/{info["agent_run_id"]}',
                        timeout=5, headers=self._agent_headers(),
                    )
                    if r.status_code != 200:
                        continue
                    st = r.json()
                except (requests.RequestException, ValueError):
                    continue
                if not st.get('is_running'):
                    info['finished'] = True
                    info['exit_code'] = st.get('exit_code')
                    if (st.get('exit_code') or 0) != 0:
                        any_failed = True

            time.sleep(_HEARTBEAT_INTERVAL_SEC)

        # 全部 agent 终态：拉 jtl
        jtl_paths: list[Path] = []
        with self._agent_runs_lock:
            agent_runs = list(self._agent_runs.values())
        for info in agent_runs:
            try:
                r = requests.get(
                    f'{info["base_url"]}/runs/{info["agent_run_id"]}/jtl',
                    timeout=60, headers=self._agent_headers(), stream=True,
                )
                if r.status_code == 200:
                    info['jtl_path'].parent.mkdir(parents=True, exist_ok=True)
                    with info['jtl_path'].open('wb') as f:
                        for chunk in r.iter_content(8192):
                            f.write(chunk)
                    jtl_paths.append(info['jtl_path'])
            except requests.RequestException:
                continue

        merged = run_dir / 'results.jtl'
        try:
            jtl_merger.merge_jtls(jtl_paths, merged)
        except Exception as e:  # noqa: BLE001
            print(f'[executor] WARN: jtl merge failed: {e}', file=sys.stderr)

        # 终态后再拉一次 errors.xml（兜底：JMeter 最后几条失败样本可能还在 buffer 里）。
        # 运行中已经周期性拉过（_ERRORS_XML_PULL_INTERVAL_SEC），这次相当于"最后一遍补刀"。
        self._pull_agent_errors_xml(run_dir)

        # agent 端清理（删 work_dir，避免 disk leak）
        for info in agent_runs:
            try:
                requests.delete(
                    f'{info["base_url"]}/runs/{info["agent_run_id"]}',
                    timeout=5, headers=self._agent_headers(),
                )
            except requests.RequestException:
                pass

        return 0 if not any_failed else 1

    # ── build + spawn ──────────────────────────────────────

    def _build_and_write_run_jmx(self) -> Path:
        from .jmeter import _atomic_write_bytes  # noqa: PLC0415
        run_dir = get_run_dir(self.run.run_id)
        run_jmx = run_dir / 'run.jmx'
        xml = jmx_svc.build_run_xml(
            self.run.task,
            inject_environment_dns=bool(self.run.task.environment_id),
            inject_backend_listener=True,
            inject_error_response_listener=True,  # 仅失败样本写 errors.xml 含 body
            run_id=self.run.run_id,
        )
        _atomic_write_bytes(run_jmx, xml)
        return run_jmx

    def _allocate_stop_port(self) -> int:
        """从 4445 起按 run_id hash 找一个空闲端口。"""
        offset = int(self.run.run_id, 16) % _STOPTEST_PORT_RANGE
        candidate = _STOPTEST_PORT_BASE + offset
        for _ in range(_STOPTEST_PORT_RANGE):
            if _is_port_free(candidate):
                return candidate
            candidate = _STOPTEST_PORT_BASE + ((candidate - _STOPTEST_PORT_BASE + 1) % _STOPTEST_PORT_RANGE)
        # 兜底：直接返起点；端口已用时 jmeter 会报错也能在心跳里看到
        return _STOPTEST_PORT_BASE

    def _spawn_jmeter(self, run_jmx: Path, stop_port: int) -> subprocess.Popen:
        run_dir = run_jmx.parent
        jtl = run_dir / 'results.jtl'
        log = run_dir / 'jmeter.log'
        report_dir = run_dir / 'report'

        cmd = [
            str(get_jmeter_bin()),
            '-n',
            '-t', str(run_jmx),
            '-l', str(jtl),
            '-j', str(log),
            '-e', '-o', str(report_dir),
            f'-Jjmeterengine.nongui.port={stop_port}',
            '-Jjmeterengine.stopfail.system.exit=false',
            '-Jjmeterengine.remote.system.exit=false',
            # 显式开启 JTL 关键字段保存，避免依赖 jmeter.properties 默认值（不同版本/环境会漂移）。
            # 影响 ErrorMessageTable / ErrorDetailList 能否拿到 message：
            #   response_message: HTTP responseMessage（"OK" / "Gateway Time-out" 等）
            #   assertion_results_failure_message: 断言失败原因（200 + success=false 时唯一信息）
            #   url: 错误样例下钻看请求 URL
            '-Jjmeter.save.saveservice.response_message=true',
            '-Jjmeter.save.saveservice.assertion_results_failure_message=true',
            '-Jjmeter.save.saveservice.url=true',
        ]

        # JMeter 需要 Java 17+。光靠 PATH 不够：JMeter 的 bin/jmeter shell
        # 脚本在 mac 上会调 /usr/libexec/java_home 探测，命中 stub /usr/bin/java
        # 后启动失败（连 jmeter.log 都来不及写）。复用 jmeter_runner 的 helper：
        # 显式塞 JAVA_HOME + PATH 兜底（与试跑用的同一逻辑）。
        env = _augmented_env()
        # 防止 JMeter 子进程把控制台编码搞坏（中文 testname 落 jmeter.log 时）
        env.setdefault('JAVA_TOOL_OPTIONS', '-Dfile.encoding=UTF-8')

        # Mac/Linux：让 JMeter 进新进程组，方便后面 SIGKILL 整组
        kwargs: dict = {
            'cwd': str(get_jmeter_home()),
            'env': env,
            'stdout': subprocess.DEVNULL,  # JMeter -j 写文件了，stdout 可丢
            'stderr': subprocess.STDOUT,
        }
        if os.name != 'nt':
            kwargs['preexec_fn'] = os.setsid
        else:
            kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP

        return subprocess.Popen(cmd, **kwargs)

    # ── heartbeat / cancel / kill ──────────────────────────

    def _heartbeat_loop(self, proc: subprocess.Popen) -> int:
        """每秒更新心跳；监听 cancel；检查 duration 超时；P0 #3 early abort 检查。"""
        from ..models import RunStatus  # noqa: PLC0415
        # P0 #1：max_wall 按 TG kind 算（旧公式 ramp+duration+60 不适配 plugin TG）
        tg_cfg = self.run.task.thread_groups_config or []
        fallback = self.run.duration_seconds or 0
        max_wall = (
            scheduler_svc.estimate_max_wall_sec(tg_cfg, fallback) + _DURATION_OVERRUN_SEC
            if (tg_cfg or fallback)
            else 0
        )
        start_t = time.monotonic()
        last_abort_check = start_t
        last_anchor_check = start_t

        while True:
            ret = proc.poll()
            if ret is not None:
                return ret

            self._update_run(last_heartbeat_at=dj_timezone.now())

            if self._cancelled.is_set():
                return self._wait_or_kill(proc)

            now = time.monotonic()

            # § 12 S1：实时锚点扫描（first_sample / first_error / first_5xx）
            if (now - last_anchor_check) > _RUNTIME_ANCHOR_INTERVAL_SEC:
                last_anchor_check = now
                self._record_runtime_anchors()

            # P0 #3 early abort gate：grace 期后每 INTERVAL 秒查一次，命中即 cancel
            if (
                (now - start_t) > _EARLY_ABORT_GRACE_SEC
                and (now - last_abort_check) > _EARLY_ABORT_CHECK_INTERVAL_SEC
            ):
                last_abort_check = now
                abort_msg = self._check_early_abort()
                if abort_msg:
                    self._early_aborted = True
                    self._record_event_anchor(
                        'error_rate_breached',
                        ts_ms=int(time.time() * 1000),
                        metadata={'message': abort_msg[:200]},
                    )
                    self._update_run(
                        status=RunStatus.CANCELLING,
                        error_message=abort_msg,
                    )
                    self._send_stoptest()
                    exit_code = self._wait_or_kill(proc)
                    # 标 failed 而非 cancelled——这是平台主动判定无效，非用户取消
                    self._update_run(status=RunStatus.FAILED)
                    return exit_code

            if max_wall and (now - start_t) > max_wall:
                # duration 超时兜底：强制 graceful 停
                self._update_run(status=RunStatus.CANCELLING)
                self._send_stoptest()
                exit_code = self._wait_or_kill(proc)
                # 标 timeout 而不是 cancelled（用户没主动按）
                self._update_run(status=RunStatus.TIMEOUT)
                return exit_code

            time.sleep(_HEARTBEAT_INTERVAL_SEC)

    def _check_early_abort(self) -> str | None:
        """P0 #3：查最近 30s 错误率，命中 abort 阈值时返回错误说明字符串，否则 None。"""
        result = influxdb_svc.query_recent_window_error_rate(
            self.run.run_id, window_sec=_EARLY_ABORT_WINDOW_SEC,
        )
        if not result:
            return None  # InfluxDB 不可达 / 无数据 → 不 abort
        total, errors, error_rate = result
        if total < _EARLY_ABORT_MIN_TOTAL:
            return None  # 样本量太少不下结论（可能 ramp 还没开始喷流量）
        if error_rate < _EARLY_ABORT_THRESHOLD:
            return None
        pct = error_rate * 100
        return (
            f'测试自动中止：最近 {_EARLY_ABORT_WINDOW_SEC}s 错误率 {pct:.1f}%（≥ '
            f'{int(_EARLY_ABORT_THRESHOLD * 100)}% 阈值），共 {total} 样本 / {errors} 失败。'
            f'常见原因：CSVDataSet 路径不可达 / 登录变量未注入 / 业务接口路径错。'
            f'查 jmeter.log 与错误明细 tab 定位根因后重跑。'
        )

    def _send_stoptest(self) -> None:
        """连 JMeter 的 nongui.port 发 'StopTestNow'。失败静默——心跳会兜底升级 KILL。"""
        port = self.run.stop_port or _STOPTEST_PORT_BASE
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=3) as s:
                s.sendall(b'StopTestNow\r\n')
        except OSError:
            pass

    def _wait_or_kill(self, proc: subprocess.Popen) -> int:
        """graceful → SIGTERM → SIGKILL。返 exit code。"""
        # 已发 stoptest（cancel() 里发过）
        try:
            return proc.wait(timeout=_GRACEFUL_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            pass
        # 升级 SIGTERM
        try:
            if os.name != 'nt':
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            else:
                proc.terminate()
        except OSError:
            pass
        try:
            return proc.wait(timeout=_SIGTERM_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            pass
        # 升级 SIGKILL
        try:
            if os.name != 'nt':
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            else:
                proc.kill()
        except OSError:
            pass
        try:
            return proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            return -9

    # ── finalize ───────────────────────────────────────────

    def _on_finish(self, exit_code: int) -> None:
        """根据当前 status + exit code 决定终态；解析 .jtl 填总结指标；触发归档。"""
        from ..models import RunStatus, TaskRun  # noqa: PLC0415
        # 重新拉一遍最新 run（cancel 期间可能已经被改成 cancelling/timeout）
        run = TaskRun.objects.get(pk=self.run.pk)

        # 总结指标：优先从 InfluxDB 拿，失败回退到 JTL
        summary = influxdb_svc.query_run_summary(run.run_id)
        if summary['total_requests'] == 0:
            summary = _summarize_jtl(get_run_dir(run.run_id) / 'results.jtl')

        # § 12 S2：error_breakdown 总是来自 JTL（InfluxDB summary 不含分桶字段）。
        # 即使 InfluxDB summary 命中也补扫一次 JTL 算分桶——_summarize_jtl 已经
        # 是 JTL 全扫，体积小（终态 JTL 一般 < 100MB）。
        if 'error_breakdown' not in summary:
            jtl_summary = _summarize_jtl(get_run_dir(run.run_id) / 'results.jtl')
            summary['error_breakdown'] = jtl_summary.get('error_breakdown', {})

        status_update = {
            'finished_at': dj_timezone.now(),
            'avg_rps': summary.get('avg_rps', 0),
            'p99_ms': summary.get('p99_ms', 0),
            'error_rate': summary.get('error_rate', 0),
            'total_requests': summary.get('total_requests', 0),
            'error_breakdown': summary.get('error_breakdown') or {},
        }

        # 终态决策
        if self._early_aborted:
            # P0 #3：平台 early abort（用户没主动按）→ failed 而非 cancelled；
            # error_message 已经在 _check_early_abort 时写过，保留
            status_update['status'] = RunStatus.FAILED
        elif run.status == RunStatus.CANCELLING:
            status_update['status'] = RunStatus.CANCELLED
        elif run.status == RunStatus.TIMEOUT:
            status_update['status'] = RunStatus.TIMEOUT
        elif exit_code == 0:
            # 阶段 0 踩过：JMeter 主进程 exit 0 但 thread 全因 CSV/init 失败 0 sampler，
            # 不能误标 success。total_requests=0 时降级 failed + 指引看 jmeter.log。
            if (summary.get('total_requests') or 0) == 0:
                status_update['status'] = RunStatus.FAILED
                if not run.error_message:
                    status_update['error_message'] = (
                        'JMeter 子进程退出 0 但未产生任何 sample。常见原因：'
                        'CSVDataSet 文件路径错误 / Thread init 阶段抛异常 / 全部 sampler 被禁。'
                        '详情见 jmeter.log（runs/<run_id>/jmeter.log）'
                    )
            else:
                status_update['status'] = RunStatus.SUCCESS
        else:
            status_update['status'] = RunStatus.FAILED
            # 保留具体错误（_run_distributed 等子流程已写入），仅在为空时填通用信息
            if not run.error_message:
                status_update['error_message'] = (
                    f'JMeter 子进程异常退出（exit={exit_code}），详情见 jmeter.log'
                )

        TaskRun.objects.filter(pk=run.pk).update(**status_update)

        # § 12 S1：写阶段事件锚点（ramp_done / hold_start / shutdown_start）+
        # 扫 InfluxDB 补 first_error。同步写表，体量小（< 10 条），失败静默不阻塞。
        try:
            self._record_phase_anchors_for_run(run)
        except Exception as e:  # noqa: BLE001
            print(f'[executor] WARN: phase anchors record failed: {e}', file=sys.stderr)

        # 旧 run 自动归档
        try:
            cleanup_old_runs(keep=_RUN_KEEP_COUNT)
        except Exception as e:  # noqa: BLE001
            print(f'[executor] WARN: cleanup_old_runs failed: {e}',
                  file=sys.stderr)

        # P3 § 11：异步触发 Pinpoint slow trace 拉取（v1.3）。
        # daemon thread + 失败静默——不阻塞 _on_finish 主流程；PinpointConfig
        # 禁用 / 不可达时 collector 内部 skip。仅 success 终态拉（其他终态业务
        # 可能没真跑业务请求，trace 也意义不大）。
        if status_update.get('status') == RunStatus.SUCCESS:
            try:
                # 重新读最新 run 对象（_update_run 后内存版才齐全 finished_at 等字段）
                run_for_pinpoint = TaskRun.objects.get(pk=run.pk)
                threading.Thread(
                    target=self._collect_pinpoint_safely,
                    args=(run_for_pinpoint,),
                    name=f'pinpoint-collect-{run.run_id}',
                    daemon=True,
                ).start()
            except Exception as e:  # noqa: BLE001
                print(f'[executor] WARN: pinpoint collect dispatch failed: {e}',
                      file=sys.stderr)

    def _pre_record_phase_anchors(self) -> None:
        """§ 12 S1：run 进入 RUNNING 后立即把 phase 边界事件预写入（基于 task config
        + started_at 推算）。这样进度条第一时间就有精确边界，不靠 phaseSegments 的
        本地 fallback。失败静默——锚点缺失不阻塞 run。"""
        try:
            if not self.run.started_at:
                return
            started_ms = int(self.run.started_at.timestamp() * 1000)
            anchors = scheduler_svc.estimate_phase_anchors_sec(
                self.run.task.thread_groups_config or []
            )
            if not anchors:
                return
            for event_type, sec_key in [
                ('ramp_done', 'ramp_done_sec'),
                ('hold_start', 'hold_start_sec'),
                ('shutdown_start', 'shutdown_start_sec'),
            ]:
                sec = anchors.get(sec_key)
                if sec is None or sec < 0:
                    continue
                if event_type in self._anchors_recorded:
                    continue
                self._record_event_anchor(
                    event_type, started_ms + sec * 1000,
                    metadata={'phase_offset_sec': sec},
                )
                self._anchors_recorded.add(event_type)
        except Exception as e:  # noqa: BLE001
            print(f'[executor] WARN: pre-record phase anchors: {e}', file=sys.stderr)

    def _record_runtime_anchors(self) -> None:
        """§ 12 S1：heartbeat 里增量写 first_sample / first_error / first_5xx。
        已写过的用 self._anchors_recorded 缓存，避免每次都开 JTL 文件。
        分布式时 results.jtl 在 _on_finish 才合并，期间 JTL 扫描自然 skip；
        first_error 仍能通过 InfluxDB 查到（每台 agent 都写同一 measurement）。"""
        needs = {'first_sample', 'first_error', 'first_5xx'} - self._anchors_recorded
        if not needs:
            return

        # first_error: 扫 InfluxDB error_count
        if 'first_error' in needs:
            try:
                metrics = influxdb_svc.query_run_realtime(self.run.run_id)
                err_pts = (metrics or {}).get('overall', {}).get('error_count') or []
                for ts_ms, val in err_pts:
                    if val and val > 0:
                        self._record_event_anchor(
                            'first_error', int(ts_ms),
                            metadata={'error_count': int(val)},
                        )
                        self._anchors_recorded.add('first_error')
                        break
            except Exception as e:  # noqa: BLE001
                print(f'[executor] WARN: first_error realtime scan: {e}', file=sys.stderr)

        # first_sample / first_5xx: 扫本地 results.jtl 第一行 / 第一条 5xx
        if {'first_sample', 'first_5xx'} & needs:
            try:
                import csv as _csv  # noqa: PLC0415
                jtl_path = get_run_dir(self.run.run_id) / 'results.jtl'
                if jtl_path.exists() and jtl_path.stat().st_size > 0:
                    with jtl_path.open('r', encoding='utf-8', errors='replace') as f:
                        reader = _csv.DictReader(f)
                        for row in reader:
                            ts = int(row.get('timeStamp') or 0)
                            if ts <= 0:
                                continue
                            if 'first_sample' not in self._anchors_recorded:
                                self._record_event_anchor('first_sample', ts)
                                self._anchors_recorded.add('first_sample')
                            if 'first_5xx' not in self._anchors_recorded:
                                code = (row.get('responseCode') or '').strip()
                                success = (row.get('success') or '').lower()
                                if success != 'true' and code.startswith('5') and len(code) == 3:
                                    self._record_event_anchor(
                                        'first_5xx', ts,
                                        metadata={'response_code': code},
                                    )
                                    self._anchors_recorded.add('first_5xx')
                            if {'first_sample', 'first_5xx'}.issubset(self._anchors_recorded):
                                break
            except Exception as e:  # noqa: BLE001
                print(f'[executor] WARN: first_sample/5xx realtime scan: {e}', file=sys.stderr)

    def _record_event_anchor(self, event_type: str, ts_ms: int, metadata: dict | None = None) -> None:
        """§ 12 S1：往 RunEventAnchor 写一条事件锚点。失败静默——事件锚点是辅助
        信号，不阻塞 run 终态。"""
        try:
            from ..models import RunEventAnchor  # noqa: PLC0415
            RunEventAnchor.objects.create(
                run=self.run,
                event_type=event_type,
                ts_ms=int(ts_ms),
                metadata=metadata or {},
            )
        except Exception as e:  # noqa: BLE001
            print(f'[executor] WARN: event anchor write failed ({event_type}): {e}',
                  file=sys.stderr)

    def _record_phase_anchors_for_run(self, run) -> None:
        """§ 12 S1：基于 run.started_at + task.thread_groups_config 算阶段锚点
        （ramp_done / hold_start / shutdown_start）+ 扫 InfluxDB 补 first_error。

        多 TG 时取首个（与 § 4 主场景决策一致）；TG kind 未知时跳过阶段锚点。
        InfluxDB 不可达时 first_error 跳过。整流程失败静默。
        """
        from ..models import RunEventAnchor  # noqa: PLC0415
        if not run.started_at:
            return
        started_ms = int(run.started_at.timestamp() * 1000)

        # 1) 阶段锚点（来自 task config + 实际起始时刻）
        anchors = scheduler_svc.estimate_phase_anchors_sec(run.task.thread_groups_config or [])
        if anchors:
            for event_type, sec_key in [
                ('ramp_done', 'ramp_done_sec'),
                ('hold_start', 'hold_start_sec'),
                ('shutdown_start', 'shutdown_start_sec'),
            ]:
                sec = anchors.get(sec_key)
                if sec is None or sec < 0:
                    continue
                # 同 ts 不写两次（hold_start 和 ramp_done 时刻经常一致）
                ts_ms = started_ms + sec * 1000
                if RunEventAnchor.objects.filter(
                    run=run, event_type=event_type, ts_ms=ts_ms,
                ).exists():
                    continue
                try:
                    RunEventAnchor.objects.create(
                        run=run, event_type=event_type, ts_ms=ts_ms,
                        metadata={'phase_offset_sec': sec},
                    )
                except Exception as e:  # noqa: BLE001
                    print(f'[executor] WARN: phase anchor {event_type}: {e}', file=sys.stderr)

        # 2) first_error：扫 InfluxDB 找第一个 error_count > 0 的 ts
        try:
            metrics = influxdb_svc.query_run_realtime(run.run_id)
            err_pts = (metrics or {}).get('overall', {}).get('error_count') or []
            for ts_ms, val in err_pts:
                if val and val > 0:
                    if not RunEventAnchor.objects.filter(
                        run=run, event_type='first_error',
                    ).exists():
                        RunEventAnchor.objects.create(
                            run=run, event_type='first_error',
                            ts_ms=int(ts_ms),
                            metadata={'error_count': int(val)},
                        )
                    break
        except Exception as e:  # noqa: BLE001
            print(f'[executor] WARN: first_error scan: {e}', file=sys.stderr)

        # 3) first_sample + first_5xx：扫 results.jtl 第一行 / 第一条 5xx
        try:
            import csv as _csv  # noqa: PLC0415
            jtl_path = get_run_dir(run.run_id) / 'results.jtl'
            if jtl_path.exists() and jtl_path.stat().st_size > 0:
                with jtl_path.open('r', encoding='utf-8', errors='replace') as f:
                    reader = _csv.DictReader(f)
                    saw_first_sample = False
                    saw_first_5xx = False
                    for row in reader:
                        ts = int(row.get('timeStamp') or 0)
                        if ts <= 0:
                            continue
                        if not saw_first_sample:
                            if not RunEventAnchor.objects.filter(
                                run=run, event_type='first_sample',
                            ).exists():
                                RunEventAnchor.objects.create(
                                    run=run, event_type='first_sample', ts_ms=ts,
                                )
                            saw_first_sample = True
                        if not saw_first_5xx:
                            code = (row.get('responseCode') or '').strip()
                            success = (row.get('success') or '').lower()
                            if success != 'true' and code.startswith('5') and len(code) == 3:
                                if not RunEventAnchor.objects.filter(
                                    run=run, event_type='first_5xx',
                                ).exists():
                                    RunEventAnchor.objects.create(
                                        run=run, event_type='first_5xx', ts_ms=ts,
                                        metadata={'response_code': code},
                                    )
                                saw_first_5xx = True
                        if saw_first_sample and saw_first_5xx:
                            break
        except Exception as e:  # noqa: BLE001
            print(f'[executor] WARN: first_sample/5xx scan: {e}', file=sys.stderr)

    def _collect_pinpoint_safely(self, run) -> None:
        """daemon thread 入口；任何异常都吞掉，pinpoint_collector 自身已 fail-fast。"""
        close_old_connections()  # 子线程必须自己管 DB 连接
        try:
            stat = pinpoint_collector_svc.collect_for_run(run)
            if stat:
                print(f'[pinpoint] run={run.run_id} collected: {stat}', file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            print(f'[pinpoint] run={run.run_id} collect error: {e}', file=sys.stderr)
        finally:
            close_old_connections()

    # ── DB helper ──────────────────────────────────────────

    def _update_run(self, **fields) -> None:
        from ..models import TaskRun  # noqa: PLC0415
        if not fields:
            return
        TaskRun.objects.filter(pk=self.run.pk).update(**fields)
        # 同步内存里的 run 对象（部分字段后续步骤用）
        for k, v in fields.items():
            setattr(self.run, k, v)


# ── module-level helpers ───────────────────────────────────


def _is_port_free(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', port))
            return True
    except OSError:
        return False


def _summarize_jtl(jtl_path: Path) -> dict:
    """退路：InfluxDB 拿不到时直接读 results.jtl 算总结指标。

    JTL 默认列：timeStamp,elapsed,label,responseCode,responseMessage,threadName,
    dataType,success,failureMessage,bytes,sentBytes,grpThreads,allThreads,
    URL,Latency,IdleTime,Connect

    § 12 S2：同时按 jmeter_runner.classify_jtl_error 算 error_breakdown 5 桶。
    """
    from .jmeter_runner import classify_jtl_error, empty_error_breakdown  # noqa: PLC0415
    empty = {
        'avg_rps': 0, 'p99_ms': 0, 'error_rate': 0, 'total_requests': 0,
        'error_breakdown': empty_error_breakdown(),
    }
    if not jtl_path.exists() or jtl_path.stat().st_size == 0:
        return empty

    elapsed_list: list[int] = []
    error_count = 0
    total = 0
    first_ts: int | None = None
    last_ts: int | None = None
    error_breakdown = empty_error_breakdown()

    try:
        with jtl_path.open('r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ts = int(row['timeStamp'])
                    elapsed = int(row['elapsed'])
                except (KeyError, ValueError):
                    continue
                total += 1
                elapsed_list.append(elapsed)
                if first_ts is None:
                    first_ts = ts
                last_ts = ts
                success = (row.get('success') or '').lower() == 'true'
                if not success:
                    error_count += 1
                    bucket = classify_jtl_error(row)
                    error_breakdown[bucket] = error_breakdown.get(bucket, 0) + 1
    except OSError:
        return empty

    p99 = 0
    if elapsed_list:
        elapsed_list.sort()
        idx = max(0, int(len(elapsed_list) * 0.99) - 1)
        p99 = elapsed_list[idx]

    avg_rps = 0.0
    if first_ts and last_ts and last_ts > first_ts and total > 0:
        span_sec = (last_ts - first_ts) / 1000.0
        if span_sec > 0:
            avg_rps = total / span_sec

    return {
        'avg_rps': avg_rps,
        'p99_ms': p99,
        'error_rate': (error_count / total * 100) if total else 0,
        'total_requests': total,
        'error_breakdown': error_breakdown,
    }
