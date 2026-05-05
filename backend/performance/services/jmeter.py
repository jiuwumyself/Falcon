"""
JMeter tool lifecycle + script storage.

Scope:
- Where the Apache JMeter tool lives on disk (auto-download if missing in dev;
  respect JMETER_HOME in Docker/production).
- Where user-uploaded JMX scripts get stored (<jmeter_home>/scripts/).
- How to turn a user-facing title into a safe, collision-free .jmx filename.

This module does NOT parse JMX XML — that's tasks/services/jmx.py.
"""
import hashlib
import os
import re
import shutil
import sys
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
