"""JMeter 子进程封装 + JTL 解析。

被以下场景共用：
- Step 2 试跑（1 线程 × 1 循环，save_response_data=True 拿响应体）
- Step 3 执行（v1.1，真压测，CSV JTL 体积小）

接口：`run_jmeter(xml_bytes, work_dir)` → list[JtlSample]。
进程退出码非 0 时抛 `JMeterRunError`，附带 jmeter.log 末尾以便定位。
"""
from __future__ import annotations

import csv
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

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
    # 仅 save_response_data=True 时填，CSV 模式留空
    response_body: str = ''
    response_headers: str = ''
    request_data: str = ''
    assertion_failures: list[str] = field(default_factory=list)


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
    save_response_data: bool = False,
) -> list[JtlSample]:
    """跑 `jmeter -n` 然后解析 JTL；返回每条 Sampler 结果。

    work_dir 会被清空重建。跑完后里面有：
    - run.jmx       本次执行的脚本
    - result.jtl    JTL（CSV 默认；save_response_data=True 时切 XML）
    - jmeter.log    引擎日志

    `save_response_data=True`：切 XML 格式 JTL 并捕获响应体 / 头 / sampler 数据，
    用于 Step 2 试跑展示完整响应；Step 3 真压测保持 CSV 格式（体积可控）。
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
    if save_response_data:
        cmd += [
            '-Jjmeter.save.saveservice.output_format=xml',
            '-Jjmeter.save.saveservice.response_data=true',
            '-Jjmeter.save.saveservice.response_headers=true',
            '-Jjmeter.save.saveservice.samplerData=true',
            '-Jjmeter.save.saveservice.assertion_results=all',
            # 体积保护：单条响应体超过 200KB 截断（避免下载大附件把 JTL 撑爆）
            '-Jjmeter.save.saveservice.response_data.on_error=false',
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

    if save_response_data:
        return _parse_jtl_xml(result_jtl)
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


# ─── XML JTL 解析（save_response_data=True 时） ─────────────────────────

# 响应体 / 请求体超过这个长度就截断，前端展示不必看完整 1MB binary
_BODY_TRUNCATE_BYTES = 200 * 1024  # 200 KB


def _truncate(s: str) -> str:
    if not s:
        return ''
    if len(s) > _BODY_TRUNCATE_BYTES:
        return s[:_BODY_TRUNCATE_BYTES] + f'\n\n... [已截断，原长度 {len(s)} 字节]'
    return s


def _xml_text(parent: etree._Element, tag: str) -> str:
    """读直接子节点 <tag> 的文本（缺省返回空串）。"""
    el = parent.find(tag)
    return (el.text or '') if el is not None else ''


def _parse_assertion_failures(parent: etree._Element) -> list[str]:
    """解析 sample 内嵌的 <assertionResult>，收集失败的断言信息。"""
    failures: list[str] = []
    for ar in parent.findall('assertionResult'):
        failure = ar.findtext('failure', default='').strip().lower() == 'true'
        error = ar.findtext('error', default='').strip().lower() == 'true'
        if failure or error:
            name = ar.findtext('name', default='') or '(未命名断言)'
            msg = ar.findtext('failureMessage', default='').strip()
            failures.append(f'{name}: {msg}' if msg else name)
    return failures


def _build_request_data(sample: etree._Element, url: str) -> str:
    """从 sample 子节点合成请求详情：method / URL / queryString / cookies。

    JMeter 的 XML JTL 会把请求分散写在多个标签里（method / queryString /
    java.net.URL / cookies），不写一个统一的 samplerData。我们这里组合成一段
    可读文本，前端面板直接展示。
    """
    parts: list[str] = []
    method = _xml_text(sample, 'method')
    if method or url:
        parts.append(f'{method or "?"} {url}')
    qs = _xml_text(sample, 'queryString')
    if qs:
        parts.append('')
        parts.append('Body / Query:')
        parts.append(qs)
    cookies = _xml_text(sample, 'cookies')
    if cookies:
        parts.append('')
        parts.append(f'Cookies: {cookies}')
    samplerData = _xml_text(sample, 'samplerData')
    if samplerData:
        parts.append('')
        parts.append(samplerData)
    return '\n'.join(parts)


def _sample_to_jtl(sample: etree._Element) -> JtlSample:
    """XML JTL 的 <sample>/<httpSample> → JtlSample。"""
    a = sample.attrib
    # JMeter XML 把 URL 用 <java.net.URL> 子元素存
    url_el = sample.find('java.net.URL')
    url = (url_el.text or '') if url_el is not None else ''
    return JtlSample(
        timestamp_ms=_int_or_zero(a.get('ts', '')),
        elapsed_ms=_int_or_zero(a.get('t', '')),
        label=a.get('lb', ''),
        response_code=a.get('rc', ''),
        response_message=a.get('rm', ''),
        success=(a.get('s', '').lower() == 'true'),
        failure_message=_xml_text(sample, 'failureMessage'),
        url=url,
        bytes_recv=_int_or_zero(a.get('by', '')),
        response_body=_truncate(_xml_text(sample, 'responseData')),
        response_headers=_truncate(_xml_text(sample, 'responseHeader')),
        request_data=_truncate(_build_request_data(sample, url)),
        assertion_failures=_parse_assertion_failures(sample),
    )


def _parse_jtl_xml(jtl_path: Path) -> list[JtlSample]:
    """XML 格式 JTL → JtlSample 列表。仅 save_response_data=True 时调用。"""
    if not jtl_path.exists():
        return []
    # JMeter 写 XML 是流式的，文件可能很大但 1×1 试跑数据量有限
    parser = etree.XMLParser(huge_tree=True, recover=True)
    tree = etree.parse(str(jtl_path), parser)
    root = tree.getroot()
    samples: list[JtlSample] = []
    for el in root:
        if isinstance(el.tag, str) and el.tag in ('sample', 'httpSample'):
            samples.append(_sample_to_jtl(el))
    return samples
