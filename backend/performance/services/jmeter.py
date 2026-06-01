"""
JMeter tool lifecycle + script storage.

Scope:
- Where the Apache JMeter tool lives on disk (auto-download if missing in dev;
  respect JMETER_HOME in Docker/production).
- Where user-uploaded JMX scripts get stored (<jmeter_home>/scripts/).
- How to turn a user-facing title into a safe, collision-free .jmx filename.
- Per-run artifact directory lifecycle (Step 3).

This module does NOT parse JMX XML — that's tasks/services/jmx.py.
"""
import hashlib
import os
import re
import shutil
import sys
import tarfile
import tempfile
import time
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

from django.conf import settings

JMETER_VERSION = os.getenv('JMETER_VERSION', '5.4.1')

# JMeter always lives under backend/jmeter/, bundled with the project.
# We do NOT read JMETER_HOME env — that caused path hijacking when devs had
# a system-wide JMeter install. For Docker, extract to this same path at
# image build time (see backend/CLAUDE.md §18.3).
JMETER_BASE_DIR = Path(settings.BASE_DIR) / 'jmeter'
JMETER_DOWNLOAD_URL = (
    f'https://archive.apache.org/dist/jmeter/binaries/'
    f'apache-jmeter-{JMETER_VERSION}.zip'
)
JMETER_SHA512_URL = JMETER_DOWNLOAD_URL + '.sha512'

# Plugin JARs required for Stepping / Concurrency (Arrivals) ThreadGroup
# in Step 2. Sourced from Maven Central (repo1.maven.org) — stable mirrors,
# no jmeter-plugins.org availability concerns.
JMETER_PLUGIN_JARS: tuple[tuple[str, str], ...] = (
    (
        'jmeter-plugins-casutg-2.10.jar',
        'https://repo1.maven.org/maven2/kg/apc/jmeter-plugins-casutg/2.10/'
        'jmeter-plugins-casutg-2.10.jar',
    ),
    (
        'jmeter-plugins-cmn-jmeter-0.6.jar',
        'https://repo1.maven.org/maven2/kg/apc/jmeter-plugins-cmn-jmeter/0.6/'
        'jmeter-plugins-cmn-jmeter-0.6.jar',
    ),
)

# Windows reserved device names
_WIN_RESERVED = {
    'CON', 'PRN', 'AUX', 'NUL',
    *(f'COM{i}' for i in range(1, 10)),
    *(f'LPT{i}' for i in range(1, 10)),
}
_INVALID_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_UNDERSCORE = re.compile(r'_{2,}')


# ── Tool lifecycle ───────────────────────────────────────────────────────

def get_jmeter_home() -> Path:
    """
    JMeter install directory, always bundled with the project at
    backend/jmeter/apache-jmeter-<VERSION>/. No env-var overrides —
    Docker should extract JMeter to this exact path at image build time.
    """
    return JMETER_BASE_DIR / f'apache-jmeter-{JMETER_VERSION}'


def get_scripts_dir() -> Path:
    """<jmeter_home>/scripts/ — created on demand."""
    d = get_jmeter_home() / 'scripts'
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_runs_dir() -> Path:
    """<jmeter_home>/runs/ — 每次跑压测时落 run.jmx 快照 + .jtl 结果（v1.1 才用）。"""
    d = get_jmeter_home() / 'runs'
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_jmeter_bin() -> Path:
    """跨平台返回 JMeter CLI 可执行文件路径（jmeter / jmeter.bat）。"""
    name = 'jmeter.bat' if os.name == 'nt' else 'jmeter'
    return get_jmeter_home() / 'bin' / name


def get_run_dir(run_id: str) -> Path:
    """单个 run 的产物目录 <jmeter_home>/runs/<run_id>/，按需创建。"""
    if not run_id or '/' in run_id or '\\' in run_id or '..' in run_id:
        raise ValueError(f'invalid run_id: {run_id!r}')
    d = get_runs_dir() / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def generate_html_report(run_id: str) -> Path:
    """按需从 results.jtl 生成 JMeter 原生 HTML 报告(jmeter -g),**成功后删 results.jtl**。

    跑压测不再带 `-e -o`(省每 run 的报告生成开销 + report/ 占盘);用户点"生成报告"
    时才跑这个。报告含全部分析,JTL 删了原始数据也在 DB → 可放心删,腾盘。
    返回 report/ 路径;失败抛 RuntimeError(不删 jtl,可重试)。
    """
    import subprocess  # noqa: PLC0415
    from .jmeter_runner import _augmented_env  # noqa: PLC0415
    run_dir = get_run_dir(run_id)
    jtl = run_dir / 'results.jtl'
    report_dir = run_dir / 'report'
    if not jtl.exists() or jtl.stat().st_size == 0:
        raise RuntimeError('results.jtl 不存在或为空,无法生成报告(可能已生成过并清理)')
    # jmeter -g 要求输出目录不存在 / 为空
    if report_dir.exists():
        shutil.rmtree(report_dir, ignore_errors=True)
    env = _augmented_env()
    env.setdefault('JAVA_TOOL_OPTIONS', '-Dfile.encoding=UTF-8')
    try:
        proc = subprocess.run(
            [str(get_jmeter_bin()), '-g', str(jtl), '-o', str(report_dir)],
            cwd=str(get_jmeter_home()), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        raise RuntimeError(f'报告生成异常: {e}') from e
    if proc.returncode != 0 or not (report_dir / 'index.html').exists():
        tail = (proc.stdout or b'').decode('utf-8', 'replace')[-500:]
        raise RuntimeError(f'报告生成失败(exit={proc.returncode}): {tail}')
    # 成功 → 删 results.jtl 腾盘(报告 + DB 已覆盖全部分析需求)
    try:
        jtl.unlink()
    except OSError:
        pass
    return report_dir


def archive_run_dir(run_id: str) -> Path | None:
    """把 runs/<run_id>/ 整体打包成 runs/<run_id>.tar.gz 并删原目录。

    已归档（tar.gz 已存在）或目录不存在时是 no-op。失败抛 RuntimeError。
    返回归档文件路径；no-op 时返 None。
    """
    runs = get_runs_dir()
    src = runs / run_id
    archive = runs / f'{run_id}.tar.gz'
    if archive.exists():
        return archive  # 已归档
    if not src.is_dir():
        return None
    # 写到临时文件再 rename，避免半写归档
    tmp = runs / f'.{run_id}.tar.gz.tmp'
    try:
        with tarfile.open(tmp, 'w:gz') as tf:
            tf.add(src, arcname=run_id)
        tmp.replace(archive)
        shutil.rmtree(src, ignore_errors=True)
    finally:
        tmp.unlink(missing_ok=True)
    return archive


# 孤儿 temp / 用完校验目录的清理阈值：mtime 超过此值才清(避免误删进行中的)。
_TEMP_TTL_SEC = 60 * 60  # 60 min


def cleanup_old_runs(keep: int | None = None) -> list[str]:
    """清理 run 目录:勾选「保留」(TaskRun.keep=True)的永不删;未勾选的目录 mtime
    超过 settings.RUN_RETENTION_DAYS(30) 天才整删(run_dir + 遗留 .tar.gz)并同步清
    InfluxDB 时序数据。

    设计(2026-05 资源治理 / 2026-05-27 改 30 天 TTL + keep 豁免):终态分析数据已入
    DB(RunSamplerStat/RunErrorAggregate/RunAnalysis + TaskRun summary),查历史走 DB,
    run 目录是可丢的重数据。DB 分析行 / TaskRun 行**不删**,历史照查。

    顺手清理:孤儿 .tmp(SIGKILL/网络异常残留)、用完的 _validate_* 校验目录
    (mtime > _TEMP_TTL_SEC)。

    `keep` 参数已废弃(旧的"最近 N 个"计数淘汰),保留签名兼容调用方;实际按
    RUN_RETENTION_DAYS 天 TTL 淘汰。返回本次删除的 run_id 列表(日志用)。
    """
    runs = get_runs_dir()
    if not runs.exists():
        return []

    now = time.time()
    # 1) 清孤儿 temp + 用完的校验目录
    for p in runs.iterdir():
        try:
            if now - p.stat().st_mtime < _TEMP_TTL_SEC:
                continue
        except OSError:
            continue
        name = p.name
        if p.is_file() and ('.tmp' in name):
            p.unlink(missing_ok=True)
        elif p.is_dir() and name.startswith('_validate_'):
            shutil.rmtree(p, ignore_errors=True)

    # 2) keep=True 的 run 豁免;其余目录 mtime 超 RUN_RETENTION_DAYS 天的整删
    ttl_sec = getattr(settings, 'RUN_RETENTION_DAYS', 30) * 86400
    try:
        from ..models import TaskRun  # noqa: PLC0415  (局部 import 避循环依赖)
        kept = set(
            TaskRun.all_objects.filter(keep=True).values_list('run_id', flat=True),
        )
    except Exception:  # noqa: BLE001
        kept = set()

    deleted: list[str] = []
    for p in runs.iterdir():
        if (not p.is_dir() or p.name.startswith('_validate_')
                or p.name.startswith('.')):
            continue
        run_id = p.name
        if run_id in kept:
            continue  # 用户勾选保留,永不自动删
        try:
            if now - p.stat().st_mtime < ttl_sec:
                continue  # 未到 30 天,留着
        except OSError:
            continue
        try:
            shutil.rmtree(p, ignore_errors=True)
            (runs / f'{run_id}.tar.gz').unlink(missing_ok=True)  # 删遗留归档
            # 同步清 InfluxDB(局部 import 避循环依赖;失败不阻断,retention 兜底)
            try:
                from . import influxdb as _influx  # noqa: PLC0415
                _influx.delete_run_data(run_id)
            except Exception:  # noqa: BLE001
                pass
            deleted.append(run_id)
        except Exception as e:  # noqa: BLE001
            print(f'[jmeter] WARN: delete old run {run_id} failed: {e}',
                  file=sys.stderr)
    return deleted


# Minimum disk free space required before writing scripts / CSVs / run snapshots.
# Below this, write functions raise to surface a clear error rather than silently
# failing later when JMeter tries to read a half-written file.
_MIN_FREE_BYTES = 100 * 1024 * 1024  # 100 MB


class DiskFullError(RuntimeError):
    """Raised when free disk space at the target path is below the threshold."""


def _check_free_space(path: Path) -> None:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return  # If we can't stat, let the actual write fail with its own error
    if usage.free < _MIN_FREE_BYTES:
        free_mb = usage.free // (1024 * 1024)
        raise DiskFullError(
            f'磁盘空间不足（{free_mb} MB < 100 MB），请清理后重试'
        )


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write + flush + fsync — guarantees bytes hit the disk before we return."""
    with path.open('wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def _jmeter_binary_exists(home: Path) -> bool:
    name = 'jmeter.bat' if os.name == 'nt' else 'jmeter'
    return (home / 'bin' / name).exists()


def ensure_jmeter_installed(log=print) -> Path:
    """
    Ensure JMeter is usable; download + extract if missing (local dev only).

    Returns the jmeter_home path. Safe to call on every request — after first
    success it's just an existence check.

    In Docker: set JMETER_HOME to a pre-installed path and this function
    is a no-op check. See backend/CLAUDE.md §18 for Dockerfile example.
    """
    home = get_jmeter_home()
    if _jmeter_binary_exists(home):
        return home

    JMETER_BASE_DIR.mkdir(parents=True, exist_ok=True)
    lock = JMETER_BASE_DIR / '.downloading'

    # Concurrent-request guard: wait up to 10 min for another worker's download.
    if lock.exists():
        log(f'[jmeter] another worker is downloading, waiting…')
        deadline = time.time() + 600
        while lock.exists() and time.time() < deadline:
            time.sleep(2)
            if _jmeter_binary_exists(home):
                return home
        if lock.exists():
            lock.unlink(missing_ok=True)  # stale lock
            raise RuntimeError('JMeter download lock stuck > 10min; removed stale .downloading')

    lock.touch()
    try:
        log(f'[jmeter] downloading {JMETER_DOWNLOAD_URL} …')
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
            tmp_path = Path(tmp.name)
        try:
            urllib.request.urlretrieve(JMETER_DOWNLOAD_URL, tmp_path)

            log(f'[jmeter] verifying SHA-512 …')
            _verify_sha512(tmp_path, JMETER_SHA512_URL)

            log(f'[jmeter] extracting to {JMETER_BASE_DIR} …')
            with zipfile.ZipFile(tmp_path) as zf:
                zf.extractall(JMETER_BASE_DIR)
            # zipfile 不保留 unix +x 位；jmeter / jmeter-server / *.sh 都需要可执行
            if os.name != 'nt':
                bin_dir = home / 'bin'
                if bin_dir.exists():
                    for f in bin_dir.iterdir():
                        if f.is_file() and (f.suffix == '' or f.suffix in ('.sh',)):
                            f.chmod(f.stat().st_mode | 0o111)
        finally:
            tmp_path.unlink(missing_ok=True)

        if not _jmeter_binary_exists(home):
            raise RuntimeError(
                f'Download succeeded but jmeter binary still missing at {home}/bin'
            )
        log(f'[jmeter] installed at {home}')
        return home
    finally:
        lock.unlink(missing_ok=True)


def ensure_plugins_installed(log=print) -> list[Path]:
    """
    Ensure all JMeter plugin JARs needed by Step 2 exist under lib/ext/.
    Downloads any missing ones from Maven Central. Returns list of absolute
    paths to all installed plugin jars.

    Safe to call repeatedly — after first success it's just existence checks.
    Assumes `ensure_jmeter_installed()` has already set up lib/ext/.
    """
    home = get_jmeter_home()
    lib_ext = home / 'lib' / 'ext'
    if not lib_ext.exists():
        raise RuntimeError(
            f'JMeter lib/ext not found at {lib_ext} — run ensure_jmeter_installed first'
        )

    results: list[Path] = []
    for jar_name, url in JMETER_PLUGIN_JARS:
        dst = lib_ext / jar_name
        if dst.exists() and dst.stat().st_size > 0:
            results.append(dst)
            continue
        log(f'[jmeter-plugins] downloading {jar_name} …')
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix='.jar') as tmp:
                tmp_path = Path(tmp.name)
            try:
                urllib.request.urlretrieve(url, tmp_path)
                shutil.move(str(tmp_path), str(dst))
            finally:
                tmp_path.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            # Don't hard-fail — user can still use standard ThreadGroup without
            # the plugins. Surface the error via log, caller can decide.
            print(f'[jmeter-plugins] WARN: failed to install {jar_name}: {e}',
                  file=sys.stderr)
            continue
        log(f'[jmeter-plugins] installed {dst}')
        results.append(dst)
    return results


def _verify_sha512(zip_path: Path, sha_url: str) -> None:
    try:
        with urllib.request.urlopen(sha_url, timeout=30) as resp:
            expected_hex = resp.read().decode('ascii').strip().split()[0].lower()
    except Exception as e:
        # Don't hard-fail on hash-fetch network issues in dev; just log and skip.
        print(f'[jmeter] WARN: could not fetch SHA-512 ({e}); skipping verify',
              file=sys.stderr)
        return

    h = hashlib.sha512()
    with zip_path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    actual_hex = h.hexdigest().lower()
    if actual_hex != expected_hex:
        raise RuntimeError(
            f'JMeter zip SHA-512 mismatch.\n  expected: {expected_hex}\n  actual:   {actual_hex}'
        )


# ── Filename sanitization ────────────────────────────────────────────────

def sanitize_script_name(title: str) -> str:
    """
    Turn a user-supplied title into a safe bare filename (no extension).

    - Strip Windows/Linux-illegal chars: < > : " / \\ | ? * and control chars
    - Collapse whitespace → single underscore
    - Preserve CJK / letters / digits / - _ .
    - Trim leading/trailing dots and spaces
    - Prefix with _ if result collides with Windows reserved name
    - Cap length at 200 chars
    - Empty result → 'task'
    """
    if not title:
        return 'task'
    # Normalize unicode (e.g. full-width → half-width)
    s = unicodedata.normalize('NFC', title)
    # Defensive: strip any trailing .jmx the caller accidentally included
    s = re.sub(r'\.jmx$', '', s, flags=re.IGNORECASE)
    # Whitespace → single underscore
    s = re.sub(r'\s+', '_', s)
    # Drop illegal FS chars
    s = _INVALID_FS_CHARS.sub('', s)
    # Collapse double underscores from earlier stripping
    s = _MULTI_UNDERSCORE.sub('_', s)
    # Trim leading/trailing dots / spaces / underscores
    s = s.strip(' ._')
    # Length cap
    if len(s) > 200:
        s = s[:200].rstrip(' ._')
    if not s:
        return 'task'
    # Windows reserved (compare case-insensitive, without extension)
    if s.upper() in _WIN_RESERVED:
        s = '_' + s
    return s


def unique_script_filename(title: str, exclude: Path | None = None) -> str:
    """
    Return "<safe>.jmx" that does not collide with any file in scripts/.
    If `exclude` is given (current file for this task), a collision with it
    is ignored (so renaming to same name is a no-op).
    """
    base = sanitize_script_name(title)
    scripts = get_scripts_dir()
    candidate = scripts / f'{base}.jmx'
    if not candidate.exists() or (exclude and candidate.resolve() == exclude.resolve()):
        return candidate.name
    n = 2
    while True:
        candidate = scripts / f'{base}_{n}.jmx'
        if not candidate.exists():
            return candidate.name
        n += 1


# ── Physical file helpers ────────────────────────────────────────────────

def write_script(filename: str, data: bytes) -> Path:
    """Write raw bytes to <scripts_dir>/<filename>. Returns full path."""
    ensure_jmeter_installed()
    scripts = get_scripts_dir()
    _check_free_space(scripts)
    path = scripts / filename
    _atomic_write_bytes(path, data)
    return path


def read_script(filename: str) -> bytes:
    return (get_scripts_dir() / filename).read_bytes()


def delete_script(filename: str) -> None:
    if not filename:
        return
    (get_scripts_dir() / filename).unlink(missing_ok=True)


def rename_script(old_filename: str, new_filename: str) -> None:
    if old_filename == new_filename:
        return
    scripts = get_scripts_dir()
    src = scripts / old_filename
    dst = scripts / new_filename
    if src.exists():
        shutil.move(str(src), str(dst))


# ── CSV helpers ──────────────────────────────────────────────────────────
# CSV parameterization files live side-by-side with .jmx in scripts/
# (naming: `<jmx_stem>.csv`, e.g. `2026-04-23_foo.jmx` → `2026-04-23_foo.csv`).
# This keeps everything JMeter needs for a run in one folder.

def unique_csv_filename(jmx_filename: str, exclude: Path | None = None) -> str:
    """
    Given the task's current `jmx_filename`, return a non-colliding CSV
    filename with the same stem (e.g. `foo.jmx` → `foo.csv`; if taken,
    `foo_2.csv`, etc.).
    """
    base = Path(jmx_filename).stem if jmx_filename else 'task'
    scripts = get_scripts_dir()
    candidate = scripts / f'{base}.csv'
    if not candidate.exists() or (exclude and candidate.resolve() == exclude.resolve()):
        return candidate.name
    n = 2
    while True:
        candidate = scripts / f'{base}_{n}.csv'
        if not candidate.exists():
            return candidate.name
        n += 1


def write_csv(filename: str, data: bytes) -> Path:
    """Write raw bytes to <scripts_dir>/<filename>. Returns full path."""
    ensure_jmeter_installed()
    scripts = get_scripts_dir()
    _check_free_space(scripts)
    path = scripts / filename
    _atomic_write_bytes(path, data)
    return path


def read_csv(filename: str) -> bytes:
    return (get_scripts_dir() / filename).read_bytes()


def delete_csv(filename: str) -> None:
    if not filename:
        return
    (get_scripts_dir() / filename).unlink(missing_ok=True)


def rename_csv(old_filename: str, new_filename: str) -> None:
    if old_filename == new_filename:
        return
    scripts = get_scripts_dir()
    src = scripts / old_filename
    dst = scripts / new_filename
    if src.exists():
        shutil.move(str(src), str(dst))


_MAX_JAR_SIZE = 50 * 1024 * 1024  # 50 MB


def write_jar(filename: str, data: bytes) -> Path:
    """把 JAR 写入 JMeter lib/ext/（全局共享，所有任务公用）。"""
    if not filename.lower().endswith('.jar'):
        raise ValueError('只接受 .jar 文件')
    if len(data) > _MAX_JAR_SIZE:
        raise ValueError('JAR 文件超过 50 MB 上限')
    safe_stem = sanitize_script_name(Path(filename).stem) or 'custom'
    ext_dir = get_jmeter_home() / 'lib' / 'ext'
    if not ext_dir.exists():
        raise RuntimeError(
            f'JMeter lib/ext 目录不存在：{ext_dir}，请先运行 setup_jmeter'
        )
    _check_free_space(ext_dir)
    dest = ext_dir / f'{safe_stem}.jar'
    _atomic_write_bytes(dest, data)
    return dest
