"""JMeter 子进程封装 + JTL 解析。

被以下场景共用：
- Step 2 校验（1 线程 × 1 循环）
- Step 3 执行（v1.1，真压测）

接口：`run_jmeter(xml_bytes, work_dir)` → list[JtlSample]。
进程退出码非 0 时抛 `JMeterRunError`，附带 jmeter.log 末尾以便定位。
"""
from __future__ import annotations

import csv
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .jmeter import ensure_jmeter_installed


class JMeterRunError(RuntimeError):
    """JMeter 进程没成功跑完；message 含退出码 + 日志尾巴。"""


@dataclass
class JtlSample:
    timestamp_ms: int = 0
    elapsed_ms: int = 0
    label: str = ''
    response_code: str = ''
    response_message: str = ''
    success: bool = False
    failure_message: str = ''
    url: str = ''
    bytes_recv: int = 0


def _resolve_jmeter_bin() -> Path:
    home = ensure_jmeter_installed()
    name = 'jmeter.bat' if os.name == 'nt' else 'jmeter'
    binary = home / 'bin' / name
    if not binary.exists():
        raise JMeterRunError(f'jmeter 可执行文件不存在：{binary}')
    return binary


def _augmented_env() -> dict[str, str]:
    """子进程兜底设置 PATH + JAVA_HOME。

    - mac brew 装的 openjdk@17 不一定在系统 PATH 里
    - JMeter shell 在 mac 上若 JAVA_HOME 未设会调 `/usr/libexec/java_home`，
      在没装真 JDK 的 mac 上会返回 `/usr/bin/java` stub，jmeter 启动报
      "Unable to locate a Java Runtime"。所以这里显式设 JAVA_HOME 跳过探测。
    """
    env = dict(os.environ)
    java_home_candidates = [
        '/opt/homebrew/opt/openjdk@17',  # apple silicon brew
        '/usr/local/opt/openjdk@17',     # intel brew
    ]
    cur_path = env.get('PATH', '')
    for jh in java_home_candidates:
        bin_dir = f'{jh}/bin'
        if Path(jh).exists() and Path(f'{bin_dir}/java').exists():
            if bin_dir not in cur_path:
                cur_path = f'{bin_dir}:{cur_path}' if cur_path else bin_dir
            # Brew openjdk 的 JAVA_HOME 实际是 libexec/openjdk.jdk/Contents/Home
            # 但 bin/java 在 $jh/bin 也能用。jmeter 只需要能找到 bin/java。
            env.setdefault('JAVA_HOME', jh)
            break
    env['PATH'] = cur_path
    return env


def run_jmeter(
    xml_bytes: bytes,
    work_dir: Path,
    *,
    timeout: int = 120,
) -> list[JtlSample]:
    """跑 `jmeter -n` 然后解析 JTL；返回每条 Sampler 结果。

    work_dir 会被清空重建。跑完后里面有：
    - run.jmx       本次执行的脚本
    - result.jtl    JTL CSV
    - jmeter.log    引擎日志
    """
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    run_jmx = work_dir / 'run.jmx'
    result_jtl = work_dir / 'result.jtl'
    log_file = work_dir / 'jmeter.log'
    run_jmx.write_bytes(xml_bytes)

    binary = _resolve_jmeter_bin()
    cmd = [
        str(binary),
        '-n',
        '-t', str(run_jmx),
        '-l', str(result_jtl),
        '-j', str(log_file),
        # JMeter 默认 url 列不写入 JTL，校验结果展示需要它，强开
        '-Jjmeter.save.saveservice.url=true',
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(work_dir),
            env=_augmented_env(),
        )
    except subprocess.TimeoutExpired as e:
        raise JMeterRunError(
            f'JMeter 进程超时 (>{timeout}s)，可能某个接口卡住或脚本太大'
        ) from e
    except FileNotFoundError as e:
        raise JMeterRunError(f'找不到可执行：{e}（确认 java/jmeter 都在 PATH）') from e

    if proc.returncode != 0:
        log_tail = ''
        if log_file.exists():
            try:
                lines = log_file.read_text(errors='replace').splitlines()
                log_tail = '\n'.join(lines[-30:])
            except OSError:
                pass
        raise JMeterRunError(
            f'jmeter 退出码 {proc.returncode}\n'
            f'stderr: {proc.stderr[-500:] if proc.stderr else "(空)"}\n'
            f'jmeter.log 末尾:\n{log_tail}'
        )

    return _parse_jtl(result_jtl)


def _parse_jtl(jtl_path: Path) -> list[JtlSample]:
    if not jtl_path.exists():
        return []
    samples: list[JtlSample] = []
    with jtl_path.open('r', encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            samples.append(JtlSample(
                timestamp_ms=_int_or_zero(row.get('timeStamp', '')),
                elapsed_ms=_int_or_zero(row.get('elapsed', '')),
                label=row.get('label', '') or '',
                response_code=row.get('responseCode', '') or '',
                response_message=row.get('responseMessage', '') or '',
                success=(row.get('success', '').strip().lower() == 'true'),
                failure_message=row.get('failureMessage', '') or '',
                url=row.get('URL', '') or '',
                bytes_recv=_int_or_zero(row.get('bytes', '')),
            ))
    return samples


def _int_or_zero(s: str) -> int:
    try:
        return int(s)
    except (ValueError, TypeError):
        return 0
