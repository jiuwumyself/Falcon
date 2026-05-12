"""
falcon-agent — 容器化压力源单文件入口（v1.2）。

启动顺序：
  1. 读环境变量（FALCON_MASTER_URL / FALCON_AGENT_TOKEN / FALCON_AGENT_PORT / pod_name 等）
  2. 起 FastAPI（监听 FALCON_AGENT_PORT 默认 9100）
  3. startup 钩子调主控 POST /api/performance/load-generators/register/ 自注册
  4. 后台 daemon 线程每 30s PUT 主控 heartbeat 维持 last_heartbeat_at

暴露给主控的端点：
  POST   /runs                    起 jmeter 子进程
  POST   /runs/{run_id}/cancel    graceful + SIGKILL（30s）
  GET    /runs/{run_id}/log       拉 jmeter.log tail
  GET    /runs/{run_id}/jtl       下载 results.jtl 给主控合并
  GET    /system-metrics          psutil 实时 CPU/Mem/网络/磁盘 IO
  GET    /capabilities            cpu / mem / jmeter_version / max_vusers
  GET    /health                  200 OK

设计要点（与主控 RunExecutor 对齐）：
  - cancel 走 graceful 30s（连 jmeter nongui.port 发 StopTestNow）+ SIGTERM 10s + SIGKILL
  - 每个 run 独立 work_dir = $AGENT_RUN_DIR/<run_id>/{run.jmx, results.jtl, jmeter.log, csv/}
  - 复用 jmeter_runner._augmented_env 的 Java PATH/JAVA_HOME 兜底逻辑（容器里也保险）
"""
from __future__ import annotations

import os
import secrets
import shutil
import signal
import socket
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import psutil
import requests
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse


# ── 环境变量 ────────────────────────────────────────────────────────────

def _env(key: str, default: str = '') -> str:
    return os.environ.get(key, default)


# 主控地址（docker compose 网络内一般是 http://web:8000，本地 venv 调试用 localhost）
MASTER_URL = _env('FALCON_MASTER_URL', 'http://localhost:8000').rstrip('/')
AGENT_TOKEN = _env('FALCON_AGENT_TOKEN', '')
AGENT_PORT = int(_env('FALCON_AGENT_PORT', '9100'))
# AGENT_PORT 是容器内部监听端口；多 agent 单宿主部署时每个容器映射不同 host port，
# 这条 env 让 agent 上报"宿主可达的"端口，主控反向调用走这个值。空 = 与 AGENT_PORT 同。
AGENT_REPORT_PORT = int(_env('FALCON_AGENT_REPORT_PORT') or AGENT_PORT)
POD_NAME = _env('FALCON_POD_NAME') or _env('HOSTNAME') or f'agent-{secrets.token_hex(4)}'
ORCHESTRATOR_TYPE = _env('FALCON_ORCHESTRATOR_TYPE', 'docker')
JMETER_HOME = _env('JMETER_HOME', '/opt/apache-jmeter-5.6.3')
JMETER_VERSION = _env('JMETER_VERSION', '5.6.3')
MAX_VUSERS = int(_env('FALCON_MAX_VUSERS', '100'))
RUN_DIR_ROOT = Path(_env('FALCON_AGENT_RUN_DIR', '/tmp/falcon-agent-runs'))
HEARTBEAT_INTERVAL = 30  # 秒
GRACEFUL_TIMEOUT = 30
SIGTERM_TIMEOUT = 10
STOPTEST_PORT_BASE = 4445


# ── 运行时状态（每个 agent 进程内，无外部存储）────────────────────────────

@dataclass
class AgentRun:
    run_id: str                   # agent 内部生成的 hex（与主控的 TaskRun.run_id 不同）
    master_run_id: str            # 主控 TaskRun.run_id，多机调度对账用
    work_dir: Path
    proc: subprocess.Popen
    stop_port: int
    started_at: float
    cancel_requested: bool = False
    finished_at: Optional[float] = None
    exit_code: Optional[int] = None
    cancel_lock: threading.Lock = field(default_factory=threading.Lock)


_runs: dict[str, AgentRun] = {}
_runs_lock = threading.Lock()
_self_id: Optional[int] = None         # 主控注册成功后回传的 LoadGenerator id
_self_id_lock = threading.Lock()


# ── 工具函数 ────────────────────────────────────────────────────────────

def _augmented_env() -> dict[str, str]:
    """容器内一般已经把 JAVA_HOME / PATH 设好；Mac 本地 venv 调试时兜底加 brew openjdk@17。"""
    env = dict(os.environ)
    if not env.get('JAVA_HOME'):
        for jh in ('/opt/homebrew/opt/openjdk@17', '/usr/local/opt/openjdk@17'):
            bin_dir = Path(jh) / 'bin'
            if (bin_dir / 'java').exists():
                env['JAVA_HOME'] = jh
                env['PATH'] = f'{bin_dir}:{env.get("PATH", "")}'
                break
    env.setdefault('JAVA_TOOL_OPTIONS', '-Dfile.encoding=UTF-8')
    return env


def _resolve_jmeter_bin() -> Path:
    name = 'jmeter.bat' if os.name == 'nt' else 'jmeter'
    binary = Path(JMETER_HOME) / 'bin' / name
    if not binary.exists():
        raise FileNotFoundError(f'jmeter binary not found at {binary}')
    return binary


def _get_local_ip() -> str:
    """容器内自我 IP；compose 默认网络下能拿到 bridge 网段地址。
    本地 venv 调试场景（master_url 含 localhost / 127.0.0.1）直接报 127.0.0.1，
    避免上报路由出口 IP 主控调不通。

    单机 docker dev 形态下宿主→容器只能走 published port，主控调用必须 127.0.0.1:<published>
    才能命中。这种场景显式设 FALCON_AGENT_REPORT_IP=127.0.0.1 + compose ports 发布 9100:9100。
    """
    override = _env('FALCON_AGENT_REPORT_IP')
    if override:
        return override
    if 'localhost' in MASTER_URL or '127.0.0.1' in MASTER_URL:
        return '127.0.0.1'
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'


def _allocate_stop_port(seed: str) -> int:
    """按 seed hash 选 4445~5444 之间一个端口。"""
    offset = int(seed, 16) % 1000
    return STOPTEST_PORT_BASE + offset


def _master_headers() -> dict[str, str]:
    headers = {'Content-Type': 'application/json'}
    if AGENT_TOKEN:
        headers['Authorization'] = f'Bearer {AGENT_TOKEN}'
    return headers


# ── 注册 + 心跳 ──────────────────────────────────────────────────────────

def _register_self() -> Optional[int]:
    """
    POST /api/performance/load-generators/register/ 自注册。返回主控分配的 LoadGenerator id。
    主控按 pod_name unique upsert，agent 容器重启后重新注册仍是同一行。
    """
    url = f'{MASTER_URL}/api/performance/load-generators/register/'
    payload = {
        'pod_name': POD_NAME,
        'hostname': socket.gethostname(),
        'ip': _get_local_ip(),
        'port': AGENT_REPORT_PORT,
        'token': AGENT_TOKEN,
        'cpu_cores': psutil.cpu_count(logical=True) or 0,
        'memory_gb': round(psutil.virtual_memory().total / 1024**3, 2),
        'max_vusers': MAX_VUSERS,
        'jmeter_version': JMETER_VERSION,
        'orchestrator_type': ORCHESTRATOR_TYPE,
    }
    try:
        r = requests.post(url, json=payload, headers=_master_headers(), timeout=10)
        if r.status_code in (200, 201):
            data = r.json()
            print(f'[agent] registered: id={data["id"]} pod={POD_NAME} status={data["status"]}',
                  flush=True)
            return data['id']
        print(f'[agent] register failed: {r.status_code} {r.text[:200]}', flush=True)
    except requests.RequestException as e:
        print(f'[agent] register error: {e}', flush=True)
    return None


def _heartbeat_once(self_id: int, status: str = 'idle') -> bool:
    url = f'{MASTER_URL}/api/performance/load-generators/{self_id}/heartbeat/'
    try:
        r = requests.put(url, json={'status': status}, headers=_master_headers(), timeout=5)
        return r.status_code == 200
    except requests.RequestException:
        return False


def _current_status() -> str:
    """根据本地是否有 active run 决定汇报 idle / busy。"""
    with _runs_lock:
        for r in _runs.values():
            if r.proc.poll() is None:
                return 'busy'
    return 'idle'


def _heartbeat_loop():
    """daemon 线程：自注册 + 30s 心跳；网络抖动时无限重试。"""
    global _self_id
    backoff = 5
    while _self_id is None:
        sid = _register_self()
        if sid is not None:
            with _self_id_lock:
                _self_id = sid
            backoff = 5
            break
        time.sleep(backoff)
        backoff = min(backoff * 2, 60)

    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        ok = _heartbeat_once(_self_id, _current_status())
        if not ok:
            # 主控可能重启清表 → 尝试重新注册
            new_id = _register_self()
            if new_id is not None:
                with _self_id_lock:
                    _self_id = new_id


# ── jmeter 子进程管理（与主控 RunExecutor 风格对齐）──────────────────────

def _spawn_jmeter(work_dir: Path, run_jmx: Path, stop_port: int) -> subprocess.Popen:
    jtl = work_dir / 'results.jtl'
    log = work_dir / 'jmeter.log'
    report_dir = work_dir / 'report'

    cmd = [
        str(_resolve_jmeter_bin()),
        '-n',
        '-t', str(run_jmx),
        '-l', str(jtl),
        '-j', str(log),
        '-e', '-o', str(report_dir),
        f'-Jjmeterengine.nongui.port={stop_port}',
        '-Jjmeterengine.stopfail.system.exit=false',
        '-Jjmeterengine.remote.system.exit=false',
        # 跟 master executor 对齐的 JTL 保存开关（不能依赖 jmeter.properties 默认值，
        # 不同版本会漂移）：
        #   response_message: HTTP responseMessage 列（前端 message 兜底）
        #   assertion_results_failure_message: 断言失败原因列（JSR223/BeanShell
        #     assertion 写的 FailureMessage 落到这里——分布式失败 body 的关键来源）
        #   url: 错误样例下钻看请求 URL
        '-Jjmeter.save.saveservice.response_message=true',
        '-Jjmeter.save.saveservice.assertion_results_failure_message=true',
        '-Jjmeter.save.saveservice.url=true',
    ]

    # cwd = work_dir（**不是 JMETER_HOME**）。原因：scheduler.py 注入的
    # SimpleDataWriter listener 写 errors.xml 时用的是相对路径 'errors.xml'，
    # JMeter 按 cwd 解析 → 必须落到 work_dir 下，否则 agent /errors-xml 端点
    # 在 work_dir 找不到文件返 404 → 主控 body_index 永远为空 → 前端 message
    # 列 100% 走 HTTP_REASON 兜底（看不到真实响应 body）。
    # -l / -j / -o 都是绝对路径，cwd 切换不影响；JMeter 加载 lib/ext 走
    # JMETER_HOME 环境变量，也不依赖 cwd。
    kwargs: dict = {
        'cwd': str(work_dir),
        'env': _augmented_env(),
        'stdout': subprocess.DEVNULL,
        'stderr': subprocess.STDOUT,
    }
    if os.name != 'nt':
        kwargs['preexec_fn'] = os.setsid
    return subprocess.Popen(cmd, **kwargs)


def _send_stoptest(port: int):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=3) as s:
            s.sendall(b'StopTestNow\r\n')
    except OSError:
        pass


def _wait_or_kill(proc: subprocess.Popen) -> int:
    try:
        return proc.wait(timeout=GRACEFUL_TIMEOUT)
    except subprocess.TimeoutExpired:
        pass
    try:
        if os.name != 'nt':
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        else:
            proc.terminate()
    except OSError:
        pass
    try:
        return proc.wait(timeout=SIGTERM_TIMEOUT)
    except subprocess.TimeoutExpired:
        pass
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


def _watcher(run: AgentRun):
    """daemon 线程，等子进程退出后回填 finished_at + exit_code。"""
    code = run.proc.wait()
    run.exit_code = code
    run.finished_at = time.time()


# ── FastAPI app ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    RUN_DIR_ROOT.mkdir(parents=True, exist_ok=True)
    t = threading.Thread(target=_heartbeat_loop, daemon=True, name='falcon-agent-heartbeat')
    t.start()
    print(f'[agent] starting on port {AGENT_PORT}, master={MASTER_URL}, pod={POD_NAME}',
          flush=True)
    yield
    # 关停时尽量友好——主控的 LoadGenerator 行让 release_idle_agents 命令清理


app = FastAPI(title='falcon-agent', version='1.2.0', lifespan=lifespan)


@app.get('/health')
def health():
    return {'status': 'ok', 'pod_name': POD_NAME, 'master_id': _self_id}


@app.get('/capabilities')
def capabilities():
    return {
        'pod_name': POD_NAME,
        'cpu_cores': psutil.cpu_count(logical=True) or 0,
        'memory_gb': round(psutil.virtual_memory().total / 1024**3, 2),
        'max_vusers': MAX_VUSERS,
        'jmeter_version': JMETER_VERSION,
        'orchestrator_type': ORCHESTRATOR_TYPE,
    }


# 网络 / 磁盘 IO 增量计算用的 baseline（每次调 /system-metrics 算 delta）
_io_baseline_lock = threading.Lock()
_io_baseline: dict[str, tuple[float, float, float]] = {}  # key → (ts, bytes_or_count, ...)


@app.get('/system-metrics')
def system_metrics():
    """单点采样，返回 CPU% / Mem% / 网络 KB/s（实时） / 磁盘 IOPS（实时）。"""
    cpu_pct = psutil.cpu_percent(interval=0.2)
    mem = psutil.virtual_memory()

    net = psutil.net_io_counters()
    disk = psutil.disk_io_counters()
    now = time.time()

    with _io_baseline_lock:
        prev_net = _io_baseline.get('net')
        prev_disk = _io_baseline.get('disk')
        _io_baseline['net'] = (now, net.bytes_sent, net.bytes_recv)
        if disk is not None:
            _io_baseline['disk'] = (now, disk.read_count, disk.write_count)

    if prev_net:
        dt = max(now - prev_net[0], 0.001)
        net_kbs_out = (net.bytes_sent - prev_net[1]) / dt / 1024
        net_kbs_in = (net.bytes_recv - prev_net[2]) / dt / 1024
    else:
        net_kbs_out = 0.0
        net_kbs_in = 0.0

    if prev_disk and disk is not None:
        dt = max(now - prev_disk[0], 0.001)
        disk_iops_read = (disk.read_count - prev_disk[1]) / dt
        disk_iops_write = (disk.write_count - prev_disk[2]) / dt
    else:
        disk_iops_read = 0.0
        disk_iops_write = 0.0

    return {
        'cpu_pct': round(cpu_pct, 1),
        'mem_pct': round(mem.percent, 1),
        'mem_used_gb': round(mem.used / 1024**3, 2),
        'mem_total_gb': round(mem.total / 1024**3, 2),
        'net_kbs_in': round(net_kbs_in, 1),
        'net_kbs_out': round(net_kbs_out, 1),
        'disk_iops_read': round(disk_iops_read, 1),
        'disk_iops_write': round(disk_iops_write, 1),
        'timestamp': int(now * 1000),
    }


@app.post('/runs')
async def start_run(
    master_run_id: str = Form(...),
    jmx_file: UploadFile = File(...),
    csv_files: list[UploadFile] = File(default=[]),
):
    """
    主控调：起 jmeter 子进程。
    - master_run_id：主控的 TaskRun.run_id，写到 work_dir 名 + 日志便于对账
    - jmx_file：经过主控 scheduler 切片后的本机分片 jmx
    - csv_files：可选，与 jmx 中 CSVDataSet filename 字段匹配的 csv（已切片）
    """
    run_id = secrets.token_hex(8)
    work_dir = RUN_DIR_ROOT / f'{master_run_id}__{run_id}'
    work_dir.mkdir(parents=True, exist_ok=True)
    csv_dir = work_dir / 'csv'
    csv_dir.mkdir(parents=True, exist_ok=True)

    run_jmx = work_dir / 'run.jmx'
    run_jmx.write_bytes(await jmx_file.read())

    for csv in csv_files:
        if not csv.filename:
            continue
        target = csv_dir / Path(csv.filename).name
        target.write_bytes(await csv.read())

    stop_port = _allocate_stop_port(run_id)
    try:
        proc = _spawn_jmeter(work_dir, run_jmx, stop_port)
    except Exception as e:
        return JSONResponse({'detail': f'spawn failed: {e}'}, status_code=500)

    run = AgentRun(
        run_id=run_id,
        master_run_id=master_run_id,
        work_dir=work_dir,
        proc=proc,
        stop_port=stop_port,
        started_at=time.time(),
    )
    with _runs_lock:
        _runs[run_id] = run
    threading.Thread(target=_watcher, args=(run,), daemon=True,
                     name=f'agent-watch-{run_id}').start()

    # 立即上报 busy 一次（让前端 LoadGeneratorPicker 第一时间看到 busy）
    if _self_id is not None:
        try:
            _heartbeat_once(_self_id, 'busy')
        except Exception:
            pass

    return {'run_id': run_id, 'pid': proc.pid, 'stop_port': stop_port,
            'work_dir': str(work_dir)}


@app.get('/runs/{run_id}')
def run_status(run_id: str):
    with _runs_lock:
        run = _runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail='run not found')
    return {
        'run_id': run.run_id,
        'master_run_id': run.master_run_id,
        'pid': run.proc.pid,
        'started_at': run.started_at,
        'finished_at': run.finished_at,
        'exit_code': run.exit_code,
        'cancel_requested': run.cancel_requested,
        'is_running': run.proc.poll() is None,
    }


@app.post('/runs/{run_id}/cancel')
def cancel_run(run_id: str):
    with _runs_lock:
        run = _runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail='run not found')
    with run.cancel_lock:
        if run.cancel_requested:
            return {'status': 'already_requested'}
        run.cancel_requested = True
    _send_stoptest(run.stop_port)
    # 异步等：让 HTTP 立即返回，cancel 真正结束依赖 _watcher 收尾
    threading.Thread(target=_wait_or_kill, args=(run.proc,), daemon=True,
                     name=f'agent-cancel-{run_id}').start()
    return {'status': 'cancel_requested'}


@app.get('/runs/{run_id}/log')
def run_log(run_id: str, tail: int = 200):
    with _runs_lock:
        run = _runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail='run not found')
    log_file = run.work_dir / 'jmeter.log'
    if not log_file.exists():
        return {'lines': []}
    # 简单 tail：读全文 splitlines，取后 tail 行（开发态够用，生产再优化）
    try:
        text = log_file.read_text(encoding='utf-8', errors='replace')
    except OSError as e:
        raise HTTPException(status_code=500, detail=f'read log: {e}')
    lines = text.splitlines()
    return {'lines': lines[-tail:] if len(lines) > tail else lines}


def _stream_snapshot(path: Path, chunk: int = 65536):
    """按"读取时的文件 size 快照"流式吐字节，不预设 Content-Length。

    JMeter 边跑边追加写 jtl / errors.xml，主控运行中拉增量。FileResponse 把打开
    时的 stat().st_size 写到 Content-Length 头，等 starlette 真在 send 时文件
    已经变大 → RuntimeError: Response content longer than Content-Length。

    修法：先 snapshot 一次 size，只读这么多字节。读出来一定是完整 ≤ snapshot 的
    一个状态切片，下游 csv 解析不受影响（最多丢掉一行未刷盘的半行，下次拉时补回）。
    """
    size = path.stat().st_size
    with path.open('rb') as f:
        remaining = size
        while remaining > 0:
            data = f.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


@app.get('/runs/{run_id}/jtl')
def run_jtl(run_id: str):
    with _runs_lock:
        run = _runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail='run not found')
    jtl = run.work_dir / 'results.jtl'
    if not jtl.exists():
        raise HTTPException(status_code=404, detail='jtl not yet')
    return StreamingResponse(
        _stream_snapshot(jtl),
        media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{run_id}.jtl"'},
    )


@app.get('/runs/{run_id}/errors-xml')
def run_errors_xml(run_id: str):
    """SimpleDataWriter 落盘的失败样本 XML（含 responseData/body），主控合并后给
    前端 ErrorByEndpointTable 的 message 列拿真实响应。文件不存在时 404，主控容错。
    同 jtl：StreamingResponse + size snapshot 避开 Content-Length 漂移。"""
    with _runs_lock:
        run = _runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail='run not found')
    errors = run.work_dir / 'errors.xml'
    if not errors.exists() or errors.stat().st_size == 0:
        raise HTTPException(status_code=404, detail='no errors.xml')
    return StreamingResponse(
        _stream_snapshot(errors),
        media_type='application/xml',
        headers={'Content-Disposition': f'attachment; filename="{run_id}.errors.xml"'},
    )


@app.delete('/runs/{run_id}')
def delete_run(run_id: str):
    """主控合并 jtl 之后调，清理本地 work_dir 释放磁盘。"""
    with _runs_lock:
        run = _runs.pop(run_id, None)
    if not run:
        raise HTTPException(status_code=404, detail='run not found')
    if run.proc.poll() is None:
        # 正在跑就不清，让主控先 cancel
        with _runs_lock:
            _runs[run_id] = run
        raise HTTPException(status_code=409, detail='run still active, cancel first')
    try:
        shutil.rmtree(run.work_dir)
    except OSError:
        pass
    return {'status': 'deleted'}


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=AGENT_PORT)
