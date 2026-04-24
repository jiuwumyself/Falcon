"""
Step 2 "1 并发校验" 引擎。

对 JMX 里每个启用的 HTTPSampler 发一次真实请求（用 Python requests 库），
按 JMeter 的 HeaderManager 作用域规则合并 headers，应用 Environment 的
hosts 映射（绕开系统 DNS）。

**变量替换**（v2 新增）：按 JMeter 作用域规则收集各层 CSVDataSet，读其
物理文件**第一行**数据按 `variableNames` 建字典；在 URL / params / body /
header values 里替换 `${x}`。没解析掉的 `${...}` 会加到 `unresolved_vars`
告诉前端。

**不走 JMeter CLI**：JMeter 冷启动 3-5 秒，1 并发校验没必要等那么久。
代价：不支持正则提取 / Pre-Post Processor / 复杂函数（__BASE64 等）——
这些高级特性"接口通不通"的场景用不上。
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import requests
import urllib3
from lxml import etree

# We intentionally use verify=False for DNS-override validation (IP-direct
# connect with Host header) where cert mismatch is expected. Silence noise.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from .jmeter import get_scripts_dir
from .jmx import (
    JmxParseError, _hashtree_pairs, _local, _parse_tree, _str_prop, _top_hashtree,
)

# 每个 sampler 最多等这么久（秒）。1 并发校验，不应该慢。
REQUEST_TIMEOUT = 10


@dataclass
class ValidateResult:
    path: str
    testname: str
    url: str
    status: int = 0
    elapsed_ms: int = 0
    ok: bool = False
    error: str = ''
    unresolved_vars: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            'path': self.path,
            'testname': self.testname,
            'url': self.url,
            'status': self.status,
            'elapsed_ms': self.elapsed_ms,
            'ok': self.ok,
        }
        if self.error:
            d['error'] = self.error
        if self.unresolved_vars:
            d['unresolved_vars'] = self.unresolved_vars
        return d


# ─── 变量替换 ${name} ─────────────────────────────────────────────────────

_VAR_RE = re.compile(r'\$\{([^${}]+?)\}')


def substitute_vars(text: str, vars: dict[str, str]) -> tuple[str, list[str]]:
    """
    把 text 里的 `${name}` 替换成 vars[name]；没命中的占位符保持字面串。
    返回 (替换后文本, 未解析的变量名列表 unique)。
    """
    if not text or '${' not in text:
        return text, []
    unresolved: list[str] = []

    def repl(m: re.Match[str]) -> str:
        name = m.group(1).strip()
        # 忽略带函数调用的（__Base64、__P 等）——这些是 JMeter 内置函数
        if name.startswith('__'):
            if name not in unresolved:
                unresolved.append(name)
            return m.group(0)
        if name in vars:
            return vars[name]
        if name not in unresolved:
            unresolved.append(name)
        return m.group(0)

    return _VAR_RE.sub(repl, text), unresolved


# ─── HeaderManager 作用域合并 ─────────────────────────────────────────────


def _is_enabled(el: etree._Element) -> bool:
    return (el.get('enabled', 'true') or 'true').lower() == 'true'


def _read_header_pairs(hm: etree._Element) -> list[tuple[str, str]]:
    """从一个 HeaderManager 元素里抽出 (name, value) 对。"""
    out: list[tuple[str, str]] = []
    coll = hm.find("collectionProp[@name='HeaderManager.headers']")
    if coll is None:
        return out
    for eprop in coll.findall('elementProp'):
        name = _str_prop(eprop, 'Header.name')
        value = _str_prop(eprop, 'Header.value')
        if name:
            out.append((name, value))
    return out


def _merge_header_managers_at(
    ht: etree._Element, acc: dict[str, str],
) -> None:
    """
    合并 ht 这个 hashTree 下直接子节点里所有启用的 HeaderManager 的 headers
    到 acc。JMeter 规则：近的覆盖远的（所以同名 header 后来的会覆盖早的）。
    """
    for el in ht:
        if not isinstance(el.tag, str):
            continue
        if _local(el) != 'HeaderManager':
            continue
        if not _is_enabled(el):
            continue
        for name, value in _read_header_pairs(el):
            acc[name] = value


# ─── CSVDataSet 作用域（跟 HeaderManager 同规则） ─────────────────────────


def _read_csvdataset_first_row_vars(csv_el: etree._Element) -> dict[str, str]:
    """
    读一个 CSVDataSet 元素的：filename + variableNames + delimiter，
    从物理文件（scripts/ 下）读第一行（跳过 header 如果 ignoreFirstLine=true），
    返回 {var_name: value} 字典。文件不存在 / 空 / 解析错 → 返回 {}。
    """
    filename = _str_prop(csv_el, 'filename').strip()
    var_names = _str_prop(csv_el, 'variableNames').strip()
    delimiter = _str_prop(csv_el, 'delimiter').strip() or ','
    # boolProp
    ignore_first = False
    ignore_el = csv_el.find("boolProp[@name='ignoreFirstLine']")
    if ignore_el is not None and (ignore_el.text or '').strip().lower() == 'true':
        ignore_first = True

    if not filename or not var_names:
        return {}

    # 路径解析：绝对路径直接用，相对路径在 scripts/ 下找
    fp = Path(filename)
    if not fp.is_absolute():
        fp = get_scripts_dir() / fp.name  # 只用 basename，规避路径穿越

    if not fp.exists():
        return {}

    try:
        with fp.open('r', encoding='utf-8-sig', newline='') as f:
            reader = csv.reader(f, delimiter=delimiter)
            rows = iter(reader)
            if ignore_first:
                next(rows, None)
            first = next(rows, None)
            if not first:
                return {}
    except (OSError, UnicodeDecodeError, csv.Error):
        return {}

    names = [n.strip() for n in var_names.split(',')]
    out: dict[str, str] = {}
    for i, name in enumerate(names):
        if not name:
            continue
        out[name] = first[i] if i < len(first) else ''
    return out


def _collect_csvdatasets_at(
    ht: etree._Element, acc: list[etree._Element],
) -> None:
    """收 ht 这个 hashTree 直接子节点里所有启用的 CSVDataSet。"""
    for el in ht:
        if not isinstance(el.tag, str):
            continue
        if _local(el) != 'CSVDataSet':
            continue
        if not _is_enabled(el):
            continue
        acc.append(el)


def collect_effective_csv_vars(
    xml_bytes: bytes, sampler_path: str,
) -> dict[str, str]:
    """
    按 JMeter 作用域规则算某 Sampler 能看到的 CSV 变量。

    作用域：从根到 Sampler 的每一层 hashTree 里的启用 CSVDataSet 都生效；
    Sampler 自己 hashTree 里的 CSVDataSet 也生效。近的覆盖远的。
    每个 CSVDataSet 取其物理文件的第一行，按 variableNames 映射。
    """
    tree = _parse_tree(xml_bytes)
    try:
        top = _top_hashtree(tree)
    except JmxParseError:
        return {}
    try:
        indices = [int(x) for x in sampler_path.split('.')]
    except ValueError:
        return {}

    csvs: list[etree._Element] = []
    current_ht: etree._Element | None = top
    for idx in indices:
        if current_ht is None:
            break
        _collect_csvdatasets_at(current_ht, csvs)
        next_ht: etree._Element | None = None
        for el, child_ht, pos in _hashtree_pairs(current_ht):
            if pos == idx:
                next_ht = child_ht
                break
        current_ht = next_ht
    if current_ht is not None:
        _collect_csvdatasets_at(current_ht, csvs)

    merged: dict[str, str] = {}
    for csv_el in csvs:
        merged.update(_read_csvdataset_first_row_vars(csv_el))
    return merged


def collect_effective_headers(
    xml_bytes: bytes, sampler_path: str,
) -> dict[str, str]:
    """
    按 JMeter 作用域规则返回某 Sampler 的最终生效 headers。

    从根到 Sampler 沿路径每一层：该层 hashTree 里的 HeaderManager 都继承；
    Sampler 自己 hashTree 里的 HeaderManager 也加上。同名 header 取最近的一个。
    """
    tree = _parse_tree(xml_bytes)
    try:
        top = _top_hashtree(tree)
    except JmxParseError:
        return {}
    try:
        indices = [int(x) for x in sampler_path.split('.')]
    except ValueError:
        return {}

    headers: dict[str, str] = {}
    current_ht: etree._Element | None = top
    for idx in indices:
        if current_ht is None:
            break
        # 该层的 HeaderManager 应用到所有后代 Sampler
        _merge_header_managers_at(current_ht, headers)
        # 定位到下一层
        next_ht: etree._Element | None = None
        for el, child_ht, pos in _hashtree_pairs(current_ht):
            if pos == idx:
                next_ht = child_ht
                break
        current_ht = next_ht

    # Sampler 自己的 hashTree 里的 HeaderManager
    if current_ht is not None:
        _merge_header_managers_at(current_ht, headers)

    return headers


# ─── Sampler 遍历 + 请求发送 ──────────────────────────────────────────────


@dataclass
class _SamplerInfo:
    path: str
    testname: str
    element: etree._Element


def _walk_enabled_samplers(
    ht: etree._Element, prefix: str, parent_enabled: bool,
    out: list[_SamplerInfo],
) -> None:
    for el, child_ht, idx in _hashtree_pairs(ht):
        path = f'{prefix}{idx}'
        enabled = parent_enabled and _is_enabled(el)
        if _local(el) == 'HTTPSamplerProxy' and enabled:
            out.append(_SamplerInfo(
                path=path,
                testname=el.get('testname') or '',
                element=el,
            ))
        if child_ht is not None:
            _walk_enabled_samplers(child_ht, f'{path}.', enabled, out)


def _sampler_args_collection(el: etree._Element) -> etree._Element | None:
    wrapper = el.find("elementProp[@name='HTTPsampler.Arguments']")
    if wrapper is None:
        return None
    return wrapper.find("collectionProp[@name='Arguments.arguments']")


def _sub(text: str, vars: dict[str, str], unresolved: list[str]) -> str:
    """薄封装：替换 + 合并未解析变量到总列表（去重）。"""
    new_text, miss = substitute_vars(text, vars)
    for name in miss:
        if name not in unresolved:
            unresolved.append(name)
    return new_text


def _build_url_and_body(
    el: etree._Element, host_map: dict[str, str], csv_vars: dict[str, str],
    unresolved: list[str],
) -> tuple[str, dict[str, str], dict[str, str], str, str, str]:
    """
    返回 (url, params_dict, headers_for_host_map, method, body_raw, host_header)

    host_map: {domain: ip} — 如果 sampler 的 domain 命中，用 ip 连、保留 Host 头
    csv_vars: CSV 提供的变量字典（Sampler 作用域内合并后的）；会替换到所有字段里
    unresolved: 调用方维护的累计未解析变量名列表（传引用进来）
    """
    domain = _sub(_str_prop(el, 'HTTPSampler.domain'), csv_vars, unresolved).strip() or 'localhost'
    port = _sub(_str_prop(el, 'HTTPSampler.port'), csv_vars, unresolved).strip()
    protocol = (_str_prop(el, 'HTTPSampler.protocol').strip() or 'http').lower()
    method = (_str_prop(el, 'HTTPSampler.method').strip() or 'GET').upper()
    path = _sub(_str_prop(el, 'HTTPSampler.path'), csv_vars, unresolved).strip()
    if path and not path.startswith('/'):
        path = '/' + path

    # Environment DNS 覆盖
    connect_host = host_map.get(domain, domain)
    host_header = domain if connect_host != domain else ''

    authority = connect_host
    if port:
        authority = f'{authority}:{port}'
    url = f'{protocol}://{authority}{path}'

    # Body / params
    body_raw_mode = False
    body_boolProp = el.find("boolProp[@name='HTTPSampler.postBodyRaw']")
    if body_boolProp is not None and (body_boolProp.text or '').strip().lower() == 'true':
        body_raw_mode = True

    params: dict[str, str] = {}
    body = ''
    args_coll = _sampler_args_collection(el)
    if args_coll is not None:
        eprops = args_coll.findall('elementProp')
        if body_raw_mode:
            if eprops:
                body = _sub(_str_prop(eprops[0], 'Argument.value'), csv_vars, unresolved)
        else:
            for eprop in eprops:
                name = _sub(_str_prop(eprop, 'Argument.name'), csv_vars, unresolved)
                if not name:
                    continue
                params[name] = _sub(_str_prop(eprop, 'Argument.value'), csv_vars, unresolved)

    extra_hdrs: dict[str, str] = {}
    if host_header:
        extra_hdrs['Host'] = host_header

    return url, params, extra_hdrs, method, body, host_header


def validate_task(
    xml_bytes: bytes,
    host_entries: Iterable[dict[str, str]] | None = None,
) -> list[ValidateResult]:
    """
    遍历 JMX 里所有启用的 HTTPSampler，对每个发一次 request，返回逐条结果。

    host_entries: [{"hostname": ..., "ip": ...}, ...] — 绕开系统 DNS 的映射。
    禁用的 Sampler（自身 enabled=false 或祖先禁用）跳过。
    某条失败不中断整体，error 字段带错误原因。
    """
    host_map: dict[str, str] = {}
    for he in host_entries or []:
        hn = (he.get('hostname') or '').strip()
        ip = (he.get('ip') or '').strip()
        if hn and ip:
            host_map[hn] = ip

    tree = _parse_tree(xml_bytes)
    try:
        top = _top_hashtree(tree)
    except JmxParseError:
        return []

    samplers: list[_SamplerInfo] = []
    _walk_enabled_samplers(top, '', True, samplers)

    results: list[ValidateResult] = []
    for s in samplers:
        unresolved: list[str] = []
        csv_vars = collect_effective_csv_vars(xml_bytes, s.path)
        url, params, extra_hdrs, method, body, _host_hdr = _build_url_and_body(
            s.element, host_map, csv_vars, unresolved,
        )
        headers_raw = collect_effective_headers(xml_bytes, s.path)
        headers = {
            _sub(k, csv_vars, unresolved): _sub(v, csv_vars, unresolved)
            for k, v in headers_raw.items()
        }
        headers.update(extra_hdrs)  # Host 覆盖

        # Preview URL shown to user = original (with real domain if host_map hit)
        preview_url = url
        if extra_hdrs.get('Host'):
            # Cosmetic: swap IP-host back to domain in the display URL
            preview_url = url.replace(f'://{list(host_map.values())[0] if host_map else ""}', f'://{extra_hdrs["Host"]}') if host_map else url

        r = ValidateResult(path=s.path, testname=s.testname, url=preview_url, unresolved_vars=unresolved)
        try:
            # verify=False: 用 IP 直连 HTTPS 时 cert 通常不匹配；v1 只是校验通不通
            resp = requests.request(
                method=method,
                url=url,
                params=params or None,
                data=body if body else None,
                headers=headers or None,
                timeout=REQUEST_TIMEOUT,
                verify=False,
                allow_redirects=False,
            )
            r.status = resp.status_code
            r.elapsed_ms = int(resp.elapsed.total_seconds() * 1000)
            r.ok = 200 <= resp.status_code < 400
        except requests.exceptions.Timeout:
            r.error = f'请求超时 (>{REQUEST_TIMEOUT}s)'
        except requests.exceptions.ConnectionError as e:
            r.error = f'连接失败: {e.__class__.__name__}'
        except requests.exceptions.RequestException as e:  # noqa: BLE001
            r.error = f'{e.__class__.__name__}: {e}'
        except Exception as e:  # noqa: BLE001
            r.error = f'{e.__class__.__name__}: {e}'
        results.append(r)

    return results
