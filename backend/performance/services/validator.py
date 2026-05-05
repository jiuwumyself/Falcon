"""
Step 2 "1 并发校验" 引擎（JMeter CLI 实现）。

工作流程：
1. 取 Task 原件 → 把所有启用的 ThreadGroup-like 元素降级为 1 线程 1 循环的
   标准 ThreadGroup（`build_validate_xml`）
2. 套上 CSV 绑定（绝对路径）+ Environment DNSCacheManager
3. 写到 `<jmeter_home>/runs/_validate_<task_id>/run.jmx`
4. subprocess: `jmeter -n -t run.jmx -l result.jtl`
5. 解析 JTL CSV → list[ValidateResult]

**为什么走 JMeter 而不是 Python requests**：JMeter 原生支持 CookieManager /
AuthManager / 各种 PreProcessor / 完整 JSONPath / BeanShell / `__time` 等
函数 / Synchronizing Timer 集合点；用 Python 重新实现这些永远会差点意思。
代价是 JMeter 冷启动 3-5s——校验对延时不敏感，可接受。

**保真度** = 100%（用真 JMeter 跑）。Step 3 真压测共用同一套 runner。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from lxml import etree

from .jmeter import get_runs_dir
from .jmeter_runner import JMeterRunError, JtlSample, run_jmeter
from .jmx import (
    JmxParseError, _hashtree_pairs, _local, _parse_tree, _top_hashtree,
    _tg_kind_from_tag, build_validate_xml,
)


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
    warnings: list[str] = field(default_factory=list)
    # 仅 XML JTL 模式有值，前端点击行展开使用
    response_body: str = ''
    response_headers: str = ''
    request_data: str = ''
    response_message: str = ''
    assertion_failures: list[str] = field(default_factory=list)

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
        if self.warnings:
            d['warnings'] = self.warnings
        # 详情字段：只有非空才返，省带宽
        if self.response_body:
            d['response_body'] = self.response_body
        if self.response_headers:
            d['response_headers'] = self.response_headers
        if self.request_data:
            d['request_data'] = self.request_data
        if self.response_message:
            d['response_message'] = self.response_message
        if self.assertion_failures:
            d['assertion_failures'] = self.assertion_failures
        return d


# ─── Sampler 路径遍历（document order）──────────────────────────────────


@dataclass
class _SamplerInfo:
    path: str
    testname: str


def _walk_enabled_samplers(
    ht: etree._Element, prefix: str, parent_enabled: bool,
    out: list[_SamplerInfo],
) -> None:
    for el, child_ht, idx in _hashtree_pairs(ht):
        path = f'{prefix}{idx}'
        enabled = parent_enabled and (el.get('enabled', 'true') or 'true').lower() == 'true'
        if _local(el) == 'HTTPSamplerProxy' and enabled:
            out.append(_SamplerInfo(path=path, testname=el.get('testname') or ''))
        if child_ht is not None:
            _walk_enabled_samplers(child_ht, f'{path}.', enabled, out)


def _list_sampler_infos(xml_bytes: bytes) -> list[_SamplerInfo]:
    tree = _parse_tree(xml_bytes)
    try:
        top = _top_hashtree(tree)
    except JmxParseError:
        return []
    out: list[_SamplerInfo] = []
    _walk_enabled_samplers(top, '', True, out)
    return out


# ─── JTL → ValidateResult 映射 ────────────────────────────────────────


def _status_int(code: str) -> int:
    """JTL responseCode 多数是 '200'/'404'，连接错误时是 'Non HTTP response code: ...'。"""
    s = (code or '').strip()
    if s.isdigit():
        try:
            return int(s)
        except ValueError:
            return 0
    return 0


def _match_samples_to_paths(
    samplers: list[_SamplerInfo],
    samples: list[JtlSample],
) -> list[ValidateResult]:
    """按 testname (label) 匹配 JTL 样本到 sampler 路径，同名时按出现顺序。

    多 TG 并行时 JTL 顺序可能交织，纯索引匹配会错位；按 label-FIFO 更稳。
    label 找不到的 JTL 样本独立一行（path 留空）；没跑到的 sampler 也单独
    一行（标 error='未被 JMeter 执行'）。"""
    pending: dict[str, list[_SamplerInfo]] = {}
    for s in samplers:
        pending.setdefault(s.testname, []).append(s)

    results: list[ValidateResult] = []
    for sample in samples:
        info: _SamplerInfo | None = None
        bucket = pending.get(sample.label)
        if bucket:
            info = bucket.pop(0)
        path = info.path if info else ''
        results.append(ValidateResult(
            path=path,
            testname=sample.label,
            url=sample.url,
            status=_status_int(sample.response_code),
            elapsed_ms=sample.elapsed_ms,
            ok=sample.success,
            error=(
                ''
                if sample.success
                else (sample.failure_message
                      or sample.response_message
                      or sample.response_code
                      or '请求失败')
            ),
            response_body=sample.response_body,
            response_headers=sample.response_headers,
            request_data=sample.request_data,
            response_message=sample.response_message,
            assertion_failures=sample.assertion_failures,
        ))

    # 没被 JMeter 执行的 sampler（可能被前面失败 / 控制器跳过 / 多 TG 并行下漏）
    for bucket in pending.values():
        for info in bucket:
            results.append(ValidateResult(
                path=info.path,
                testname=info.testname,
                url='',
                status=0,
                elapsed_ms=0,
                ok=False,
                error='未被 JMeter 执行（可能被前面的失败 / 控制器跳过）',
            ))
    return results


# ─── 公共 API ──────────────────────────────────────────────────────────


def _collect_enabled_tgs(xml_bytes: bytes) -> list[dict[str, Any]]:
    """从原件 JMX 收集所有 enabled=true 的 ThreadGroup-like 节点信息。

    用于试跑结果头部展示"本次执行了哪些 TG"——和 build_validate_xml 的
    "把 enabled TG 降级为 1×1" 同源（同一筛选规则）。
    """
    tree = _parse_tree(xml_bytes)
    try:
        top = _top_hashtree(tree)
    except JmxParseError:
        return []
    out: list[dict[str, Any]] = []

    def _walk(ht, prefix: str = '') -> None:
        for el, child_ht, idx in _hashtree_pairs(ht):
            path = f'{prefix}{idx}'
            tag = _local(el)
            kind = _tg_kind_from_tag(tag)
            if kind is not None and (el.get('enabled', 'true') or 'true').lower() == 'true':
                out.append({
                    'path': path,
                    'kind': kind,
                    'testname': el.get('testname') or '',
                })
            if child_ht is not None:
                _walk(child_ht, f'{path}.')

    _walk(top)
    return out


def validate_task(
    task,
    host_entries: Iterable[dict[str, str]] | None = None,
) -> tuple[list[str], list[ValidateResult], list[dict[str, Any]]]:
    """对 Task 跑 1 线程 × 1 循环的 JMeter 试跑，返回 (warnings, results, executed_tgs)。

    host_entries: 显式覆盖 task.environment.host_entries（视图层接收 body
    的 environment_id 时用）。None 则用 task 本身关联的 environment。
    返回 tuple：
      warnings:     任务级提示（如 DNS 注入跳过的原因），前端表头横条
      results:      每个 Sampler 的执行结果（含失败信息 + 响应体）
      executed_tgs: 本次实际跑的 ThreadGroup 列表（仅启用的）；前端展示
                    "本次执行 TG"行，用户能看出禁用 TG 没参与
    """
    he_list = list(host_entries) if host_entries is not None else None
    warnings: list[str] = []
    # 注意 executed_tgs 取自原件（含真实 kind/testname），不取自 build_validate_xml
    # 的产物——后者已经全部替换为标准 TG，看不出原 kind。
    executed_tgs = _collect_enabled_tgs(task.read_jmx_bytes())
    xml_bytes = build_validate_xml(task, host_entries=he_list, warnings=warnings)
    samplers = _list_sampler_infos(xml_bytes)

    work_dir = get_runs_dir() / f'_validate_{task.id}'
    # save_response_data=True 让 JTL 出 XML 格式，附带响应体 / 头 / sampler 数据
    samples = run_jmeter(xml_bytes, work_dir, save_response_data=True)

    return warnings, _match_samples_to_paths(samplers, samples), executed_tgs


# 兼容用：旧 import 还在引用
__all__ = ['ValidateResult', 'validate_task', 'JMeterRunError']
