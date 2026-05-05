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

from . import influxdb as influxdb_svc
from . import jmx as jmx_svc
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
_GRACEFUL_TIMEOUT_SEC = 30
_SIGTERM_TIMEOUT_SEC = 10

# 心跳间隔 + duration 超时余量
_HEARTBEAT_INTERVAL_SEC = 1.0
_DURATION_OVERRUN_SEC = 60

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
        # 子进程在跑则发 stoptest
        if self._proc and self._proc.poll() is None and self.run.stop_port:
            self._send_stoptest()

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

            # 2) 进 pending → running，组 run.jmx 写盘
            self._update_run(status=RunStatus.PENDING)
            run_jmx = self._build_and_write_run_jmx()
            stop_port = self._allocate_stop_port()
            self._update_run(
                status=RunStatus.RUNNING,
                stop_port=stop_port,
                started_at=dj_timezone.now(),
                last_heartbeat_at=dj_timezone.now(),
            )

            # 3) 起 JMeter 子进程
            self._proc = self._spawn_jmeter(run_jmx, stop_port)
            self._update_run(pid=self._proc.pid)

            # 4) 心跳 + cancel 监听 + duration 超时兜底
            exit_code = self._heartbeat_loop(self._proc)

            # 5) 总结 + 归档
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

    def _pre_check(self) -> tuple[bool, str]:
        """返回 (ok, 多行日志)。任一项失败 ok=False。"""
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

        # 5) Environment hosts TCP 探测
        # host_entries 兼容两种格式（同 _inject_dns_cache_manager）：
        #   - dict {"hostname": "...", "ip": "..."}
        #   - str "10.0.0.1 hostname.foo.com"（/etc/hosts 风格 + # 注释）
        # 用 jmx_svc._parse_host_entry 统一规范化，避免 string 上调 .get 炸 AttributeError。
        if task.environment_id and task.environment.host_entries:
            # 海量 hosts 时 TCP 探测会拖慢 pre_check（用户那台环境有 1500+ 条），
            # 这里只挑前 50 条做探测代表性即可——超过的话用户去 admin 自己分类拆环境。
            entries = task.environment.host_entries[:50]
            skipped = max(0, len(task.environment.host_entries) - 50)
            for entry in entries:
                pair = jmx_svc._parse_host_entry(entry)
                if not pair:
                    continue
                host, ip = pair
                reachable = False
                for port in (80, 443):
                    try:
                        with socket.create_connection((ip, port), timeout=2):
                            reachable = True
                            break
                    except OSError:
                        continue
                if reachable:
                    lines.append(f'✅ Environment {host} → {ip}: TCP 可达')
                else:
                    # 不阻塞 ok（环境内网未开 80/443 的服务仍能被 JMeter 访问）
                    lines.append(
                        f'⚠️  Environment {host} → {ip}: TCP 80/443 探测未通过（非致命）'
                    )
            if skipped:
                lines.append(f'ℹ️  Environment 还有 {skipped} 条 hosts 跳过探测（>50 条只抽样）')

        return ok, '\n'.join(lines)

    # ── build + spawn ──────────────────────────────────────

    def _build_and_write_run_jmx(self) -> Path:
        from .jmeter import _atomic_write_bytes  # noqa: PLC0415
        run_dir = get_run_dir(self.run.run_id)
        run_jmx = run_dir / 'run.jmx'
        xml = jmx_svc.build_run_xml(
            self.run.task,
            inject_environment_dns=bool(self.run.task.environment_id),
            inject_backend_listener=True,
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
        ]

        # JMeter 需要 Java 17+；start.sh 把 openjdk@17 加进 PATH 了，子进程继承即可
        env = os.environ.copy()
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
        """每秒更新心跳；监听 cancel；检查 duration 超时。返 exit code。"""
        from ..models import RunStatus  # noqa: PLC0415
        duration = self.run.duration_seconds or 0
        ramp = self.run.ramp_up_seconds or 0
        # 整 run 应在 ramp + duration + DURATION_OVERRUN 内结束；超了进 timeout
        max_wall = ramp + duration + _DURATION_OVERRUN_SEC if duration else 0
        start_t = time.monotonic()

        while True:
            ret = proc.poll()
            if ret is not None:
                return ret

            self._update_run(last_heartbeat_at=dj_timezone.now())

            if self._cancelled.is_set():
                return self._wait_or_kill(proc)

            if max_wall and (time.monotonic() - start_t) > max_wall:
                # duration 超时兜底：强制 graceful 停
                self._update_run(status=RunStatus.CANCELLING)
                self._send_stoptest()
                exit_code = self._wait_or_kill(proc)
                # 标 timeout 而不是 cancelled（用户没主动按）
                self._update_run(status=RunStatus.TIMEOUT)
                return exit_code

            time.sleep(_HEARTBEAT_INTERVAL_SEC)

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

        status_update = {
            'finished_at': dj_timezone.now(),
            'avg_rps': summary.get('avg_rps', 0),
            'p99_ms': summary.get('p99_ms', 0),
            'error_rate': summary.get('error_rate', 0),
            'total_requests': summary.get('total_requests', 0),
        }

        # 终态决策
        if run.status == RunStatus.CANCELLING:
            status_update['status'] = RunStatus.CANCELLED
        elif run.status == RunStatus.TIMEOUT:
            status_update['status'] = RunStatus.TIMEOUT
        elif exit_code == 0:
            status_update['status'] = RunStatus.SUCCESS
        else:
            status_update['status'] = RunStatus.FAILED
            status_update['error_message'] = (
                f'JMeter 子进程异常退出（exit={exit_code}），详情见 jmeter.log'
            )

        TaskRun.objects.filter(pk=run.pk).update(**status_update)

        # 旧 run 自动归档
        try:
            cleanup_old_runs(keep=_RUN_KEEP_COUNT)
        except Exception as e:  # noqa: BLE001
            print(f'[executor] WARN: cleanup_old_runs failed: {e}',
                  file=sys.stderr)

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
    """
    if not jtl_path.exists() or jtl_path.stat().st_size == 0:
        return {'avg_rps': 0, 'p99_ms': 0, 'error_rate': 0, 'total_requests': 0}

    elapsed_list: list[int] = []
    error_count = 0
    total = 0
    first_ts: int | None = None
    last_ts: int | None = None

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
    except OSError:
        return {'avg_rps': 0, 'p99_ms': 0, 'error_rate': 0, 'total_requests': 0}

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
    }
