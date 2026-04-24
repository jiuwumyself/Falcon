"""
JMX (JMeter test plan) L1 编辑服务。

只处理 JMX 里的三个字段：
- ThreadGroup.num_threads  (虚拟用户数)
- ThreadGroup.ramp_time    (ramp-up 秒数)
- ThreadGroup.duration     (持续秒数, 需 scheduler=true)

以及 CSVDataSet 的 filename（v1.1 执行时会用到）。

策略：patch-in-place，只改 XPath 定位到的节点文本，其余原样保留。

另外还提供组件树遍历 / enabled 切换（Step 1 任务配置要用）：
- list_components(xml_bytes) → 按 <hashTree> 配对结构返回所有组件（嵌套）
- toggle_component(xml_bytes, path, enabled) → 改单个组件的 enabled 属性
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator

from lxml import etree


class JmxParseError(Exception):
    """JMX 解析失败（格式错、找不到必要元素等）"""


@dataclass
class JmxFields:
    virtual_users: int = 10
    ramp_up_seconds: int = 0
    duration_seconds: int = 0
    csv_paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'virtual_users': self.virtual_users,
            'ramp_up_seconds': self.ramp_up_seconds,
            'duration_seconds': self.duration_seconds,
            'csv_paths': list(self.csv_paths),
        }


# —— XPath 常量 —— #
# JMX 里 num_threads 一般是 stringProp，少数老模板可能写成 intProp；两种都兜底
_CSV_XPATH = './/CSVDataSet'

# ThreadGroup 有多种类型：标准的 + jmeter-plugins 变体。v1 能认出来就行。
# 解析：任一命中即可（用来抽 num_threads/ramp_time/duration 默认值）
# 补丁：`patch_jmx` 只能改标准 `<ThreadGroup>` 的属性；命中插件型的话
#      `_find_prop` 会返回 None，调用方会抛 "没找到 num_threads 属性"——符合预期。
_THREAD_GROUP_TAGS = (
    'ThreadGroup',
    'SetupThreadGroup',
    'PostThreadGroup',
    'kg.apc.jmeter.threads.UltimateThreadGroup',
    'kg.apc.jmeter.threads.SteppingThreadGroup',
    'com.blazemeter.jmeter.threads.arrivals.ArrivalsThreadGroup',
    'com.blazemeter.jmeter.threads.concurrency.ConcurrencyThreadGroup',
)


def _parse_tree(xml_bytes: bytes) -> etree._ElementTree:
    try:
        parser = etree.XMLParser(remove_blank_text=False, strip_cdata=False)
        return etree.ElementTree(etree.fromstring(xml_bytes, parser))
    except etree.XMLSyntaxError as e:
        raise JmxParseError(f'JMX XML 语法错误: {e}') from e


def _find_thread_group(tree: etree._ElementTree) -> etree._Element | None:
    """找第一个 ThreadGroup-like 元素；找不到返回 None。"""
    for tag in _THREAD_GROUP_TAGS:
        tg = tree.find(f'.//{tag}')
        if tg is not None:
            return tg
    # 兜底：本地名以 ThreadGroup 结尾的任何元素
    for el in tree.iter():
        if not isinstance(el.tag, str):
            continue  # skip comments / PIs
        local = etree.QName(el).localname
        if local.endswith('ThreadGroup'):
            return el
    return None


def _first_thread_group(tree: etree._ElementTree) -> etree._Element:
    """严格版：找不到直接抛（只给 patch 用）。"""
    tg = _find_thread_group(tree)
    if tg is None:
        raise JmxParseError('JMX 里没找到 <ThreadGroup> 节点')
    return tg


def _find_prop(parent: etree._Element, name: str) -> etree._Element | None:
    """在 parent 的直接子节点里找 name 匹配的 stringProp / intProp（兼容两种类型）。"""
    for tag in ('stringProp', 'intProp'):
        el = parent.find(f"{tag}[@name='{name}']")
        if el is not None:
            return el
    return None


def _find_bool_prop(parent: etree._Element, name: str) -> etree._Element | None:
    return parent.find(f"boolProp[@name='{name}']")


def _int_text(el: etree._Element | None, fallback: int = 0) -> int:
    if el is None or el.text is None:
        return fallback
    try:
        return int(el.text.strip())
    except (ValueError, AttributeError):
        return fallback


def parse_jmx(xml_bytes: bytes) -> JmxFields:
    """
    从 JMX 字节流里抽出 L1 可编辑字段。

    宽容策略：
    - 如果 XML 都解析不通过 → 抛 JmxParseError（真·坏文件才拒）
    - 如果找不到任何 ThreadGroup → 返回默认值 (10/0/0)，让上传照样成功
    - 如果是插件型 ThreadGroup（Ultimate/Stepping/Arrivals 等）→ 标准属性抽不到，
      num/ramp/duration 各自回退默认值；用户之后在前端编辑即可
    """
    tree = _parse_tree(xml_bytes)
    tg = _find_thread_group(tree)

    if tg is None:
        # 有效 XML 但没有任何 ThreadGroup：仍然建任务，用默认参数
        return JmxFields(
            virtual_users=10,
            ramp_up_seconds=0,
            duration_seconds=0,
            csv_paths=_find_csv_paths(tree),
        )

    num_el = _find_prop(tg, 'ThreadGroup.num_threads')
    ramp_el = _find_prop(tg, 'ThreadGroup.ramp_time')
    dur_el = _find_prop(tg, 'ThreadGroup.duration')

    return JmxFields(
        virtual_users=_int_text(num_el, 10),
        ramp_up_seconds=_int_text(ramp_el, 0),
        duration_seconds=_int_text(dur_el, 0),
        csv_paths=_find_csv_paths(tree),
    )


def _find_csv_paths(tree: etree._ElementTree) -> list[str]:
    paths: list[str] = []
    for csv in tree.findall(_CSV_XPATH):
        fn = _find_prop(csv, 'filename')
        if fn is not None and fn.text:
            paths.append(fn.text.strip())
    return paths


def patch_jmx(
    xml_bytes: bytes,
    *,
    virtual_users: int | None = None,
    ramp_up_seconds: int | None = None,
    duration_seconds: int | None = None,
    csv_path: str | None = None,
) -> bytes:
    """
    在原 JMX 上打补丁；只改传进来的字段，其他结构原样保留。

    如果 `duration_seconds` 被设置，会顺带把 `ThreadGroup.scheduler` 设为 true
    （否则 JMeter 会忽略 duration）。
    """
    tree = _parse_tree(xml_bytes)
    tg = _first_thread_group(tree)

    if virtual_users is not None:
        el = _find_prop(tg, 'ThreadGroup.num_threads')
        if el is None:
            raise JmxParseError('ThreadGroup 里没找到 num_threads 属性')
        el.text = str(virtual_users)

    if ramp_up_seconds is not None:
        el = _find_prop(tg, 'ThreadGroup.ramp_time')
        if el is None:
            raise JmxParseError('ThreadGroup 里没找到 ramp_time 属性')
        el.text = str(ramp_up_seconds)

    if duration_seconds is not None:
        dur_el = _find_prop(tg, 'ThreadGroup.duration')
        if dur_el is None:
            # 老模板可能没有 duration 节点，补一个
            dur_el = etree.SubElement(tg, 'stringProp', {'name': 'ThreadGroup.duration'})
        dur_el.text = str(duration_seconds)

        # 同步开启 scheduler（没有这一步 JMeter 会忽略 duration）
        sched_el = _find_bool_prop(tg, 'ThreadGroup.scheduler')
        if sched_el is None:
            sched_el = etree.SubElement(tg, 'boolProp', {'name': 'ThreadGroup.scheduler'})
        sched_el.text = 'true'

    if csv_path is not None:
        csv_nodes = tree.findall(_CSV_XPATH)
        if csv_nodes:
            # v1：只改第一个 CSVDataSet 的路径
            fn_el = _find_prop(csv_nodes[0], 'filename')
            if fn_el is not None:
                fn_el.text = csv_path

    return etree.tostring(tree, xml_declaration=True, encoding='UTF-8')


# ─── 组件树遍历 / enabled 切换（Step 1 任务配置用） ─────────────────────────


@dataclass
class JmxComponent:
    """JMX 里一个可启用/禁用的组件（TestPlan / ThreadGroup / Sampler / ...）"""
    path: str              # 索引路径，如 "0.0.1"（每一段是该层 hashTree 里的序号）
    tag: str               # 元素标签名，如 "HTTPSamplerProxy"
    testname: str          # JMeter GUI 里显示的名字（<... testname="..." />）
    enabled: bool          # 对应元素的 enabled 属性
    children: list['JmxComponent'] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'path': self.path,
            'tag': self.tag,
            'testname': self.testname,
            'enabled': self.enabled,
            'children': [c.to_dict() for c in self.children],
        }


def _local(el: etree._Element) -> str:
    """元素的 local name（忽略 namespace 前缀）。对注释/PI 返回空串。"""
    if not isinstance(el.tag, str):
        return ''
    return etree.QName(el).localname


def _hashtree_pairs(
    ht: etree._Element,
) -> Iterator[tuple[etree._Element, etree._Element | None, int]]:
    """
    遍历 <hashTree> 的孩子，按 JMeter 约定配对：
    孩子们是一组 [element, element_hashTree, element, element_hashTree, ...]，
    每个 element 之后紧跟一个 hashTree（装它的子节点）；最后一个 element 可能没有
    跟随的 hashTree（就当没有子）。

    产出 (element, following_hashTree_or_None, pos_index)，其中 pos_index 是
    element 在该层的序号（从 0 开始，跳过 hashTree 本身）。
    """
    children = list(ht)
    i = 0
    pos = 0
    while i < len(children):
        el = children[i]
        if _local(el) == 'hashTree':
            # 悬空的 hashTree（通常不该出现在这个位置）→ 跳过
            i += 1
            continue
        # 往后看一个是不是 hashTree
        sibling_ht: etree._Element | None = None
        if i + 1 < len(children) and _local(children[i + 1]) == 'hashTree':
            sibling_ht = children[i + 1]
        yield el, sibling_ht, pos
        pos += 1
        i += 2 if sibling_ht is not None else 1


def _walk_components(ht: etree._Element, prefix: str) -> list[JmxComponent]:
    out: list[JmxComponent] = []
    for el, child_ht, idx in _hashtree_pairs(ht):
        path = f'{prefix}{idx}'
        children = (
            _walk_components(child_ht, f'{path}.') if child_ht is not None else []
        )
        out.append(JmxComponent(
            path=path,
            tag=_local(el),
            testname=el.get('testname') or '',
            enabled=(el.get('enabled', 'true') or 'true').lower() == 'true',
            children=children,
        ))
    return out


def _top_hashtree(tree: etree._ElementTree) -> etree._Element:
    root = tree.getroot()
    top = root.find('./hashTree')
    if top is None:
        raise JmxParseError('JMX 根节点下没有 <hashTree>')
    return top


def list_components(xml_bytes: bytes) -> list[JmxComponent]:
    """按 JMeter 的 hashTree 配对结构返回组件树（最外层一般就一个 TestPlan）。"""
    tree = _parse_tree(xml_bytes)
    try:
        top = _top_hashtree(tree)
    except JmxParseError:
        return []
    return _walk_components(top, '')


def _locate_by_path(top_ht: etree._Element, path: str) -> etree._Element:
    """把 '0.1.0' 这种索引路径定位到具体 element。路径非法/越界抛 JmxParseError。"""
    if not path:
        raise JmxParseError('path 不能为空')
    try:
        indices = [int(x) for x in path.split('.')]
    except ValueError as e:
        raise JmxParseError(f'path 格式错误: {path}') from e

    current_ht: etree._Element | None = top_ht
    target: etree._Element | None = None
    for depth, idx in enumerate(indices):
        if current_ht is None:
            raise JmxParseError(f'path {path} 越界：第 {depth} 层没有子 hashTree')
        found: tuple[etree._Element, etree._Element | None] | None = None
        for el, child_ht, pos in _hashtree_pairs(current_ht):
            if pos == idx:
                found = (el, child_ht)
                break
        if found is None:
            raise JmxParseError(f'path {path} 越界：第 {depth} 层没有索引 {idx}')
        target, current_ht = found
    assert target is not None
    return target


def toggle_component(xml_bytes: bytes, path: str, enabled: bool) -> bytes:
    """按 path 定位组件，设置其 enabled 属性，返回新的 JMX 字节流。"""
    tree = _parse_tree(xml_bytes)
    top = _top_hashtree(tree)
    el = _locate_by_path(top, path)
    el.set('enabled', 'true' if enabled else 'false')
    return etree.tostring(tree, xml_declaration=True, encoding='UTF-8')


def rename_component(xml_bytes: bytes, path: str, testname: str) -> bytes:
    """按 path 定位组件，改 `testname` 属性（JMeter GUI 里显示的名字）。"""
    tree = _parse_tree(xml_bytes)
    top = _top_hashtree(tree)
    el = _locate_by_path(top, path)
    el.set('testname', testname or '')
    return etree.tostring(tree, xml_declaration=True, encoding='UTF-8')


# ─── Step 2：线程组替换 ──────────────────────────────────────────────────

# 五种支持的 ThreadGroup kind（内部统一名 → JMX 里的 tag）
# v2 新增 Ultimate + Arrivals，分别对应"峰值"和"吞吐量"场景
_TG_KIND_TO_TAG = {
    'ThreadGroup': 'ThreadGroup',
    'SteppingThreadGroup': 'kg.apc.jmeter.threads.SteppingThreadGroup',
    'ConcurrencyThreadGroup': 'com.blazemeter.jmeter.threads.concurrency.ConcurrencyThreadGroup',
    'UltimateThreadGroup': 'kg.apc.jmeter.threads.UltimateThreadGroup',
    'ArrivalsThreadGroup': 'com.blazemeter.jmeter.threads.arrivals.ArrivalsThreadGroup',
}

# JMX tag → 统一 kind 名（反向映射 + 宽容匹配老模板）
_TAG_TO_TG_KIND = {
    'ThreadGroup': 'ThreadGroup',
    'SetupThreadGroup': 'ThreadGroup',
    'PostThreadGroup': 'ThreadGroup',
    'kg.apc.jmeter.threads.SteppingThreadGroup': 'SteppingThreadGroup',
    'kg.apc.jmeter.threads.UltimateThreadGroup': 'UltimateThreadGroup',
    'com.blazemeter.jmeter.threads.concurrency.ConcurrencyThreadGroup': 'ConcurrencyThreadGroup',
    'com.blazemeter.jmeter.threads.arrivals.ArrivalsThreadGroup': 'ArrivalsThreadGroup',
}

# v1 上限（对应 CLAUDE.md 敲定的规则）
MAX_USERS = 5000
MAX_DURATION_SECONDS = 43200  # 12 小时


def _tg_kind_from_tag(tag: str) -> str | None:
    """JMX tag → 统一 kind；不在三类里返回 None。"""
    return _TAG_TO_TG_KIND.get(tag)


def _extract_tg_params(el: etree._Element, kind: str) -> dict[str, Any]:
    """从 JMX 节点里抽出该 kind 需要展示的参数（UI 初值回填）。找不到用默认。"""
    def _s(name: str, fallback: str = '') -> str:
        return _str_prop(el, name) or fallback

    def _i(name: str, fallback: int = 0) -> int:
        try:
            return int(_s(name, '').strip() or fallback)
        except (ValueError, AttributeError):
            return fallback

    if kind == 'ThreadGroup':
        return {
            'users': _i('ThreadGroup.num_threads', 10),
            'ramp_up': _i('ThreadGroup.ramp_time', 0),
            'duration': _i('ThreadGroup.duration', 60),
        }
    if kind == 'SteppingThreadGroup':
        return {
            'initial_threads': _i('Start users count burst', 0),
            'step_users': _i('Start users count', 10),
            'step_delay': _i('Start users period', 30),
            'step_count': _i('_step_count', 10),  # UI 衍生字段，JMX 里可能没有
            'hold': _i('flighttime', 60),
            'shutdown': _i('Stop users period', 1),
        }
    if kind == 'ConcurrencyThreadGroup':
        return {
            'target_concurrency': _i('TargetLevel', 100),
            'ramp_up': _i('RampUp', 10),
            'steps': _i('Steps', 5),
            'hold': _i('Hold', 60),
            'unit': _s('Unit', 'S') or 'S',
        }
    if kind == 'ArrivalsThreadGroup':
        return {
            'target_rps': _i('TargetLevel', 100),
            'ramp_up': _i('RampUp', 10),
            'steps': _i('Steps', 5),
            'hold': _i('Hold', 60),
            'unit': _s('Unit', 'M') or 'M',   # Arrivals 习惯用 M (每分钟)
        }
    if kind == 'UltimateThreadGroup':
        # 从 ultimatethreadgroupdata 里读第一行（v1 Ultimate 只生成/编辑单行）
        data = el.find("collectionProp[@name='ultimatethreadgroupdata']")
        if data is not None:
            rows = data.findall('collectionProp')
            if rows:
                row = rows[0]
                def _row_i(idx: str, fb: int) -> int:
                    e = row.find(f"stringProp[@name='{idx}']")
                    try:
                        return int((e.text or '').strip()) if e is not None else fb
                    except (ValueError, AttributeError):
                        return fb
                return {
                    'users': _row_i('1', 100),
                    'initial_delay': _row_i('2', 0),
                    'ramp_up': _row_i('3', 5),
                    'hold': _row_i('4', 60),
                    'shutdown': _row_i('5', 5),
                }
        return {
            'users': 100, 'initial_delay': 0, 'ramp_up': 5, 'hold': 60, 'shutdown': 5,
        }
    return {}


def _collect_thread_groups(
    ht: etree._Element, prefix: str, out: list[dict[str, Any]]
) -> None:
    """递归遍历 hashTree，收集所有 ThreadGroup-like 节点。"""
    for el, child_ht, idx in _hashtree_pairs(ht):
        path = f'{prefix}{idx}'
        tag = _local(el)
        kind = _tg_kind_from_tag(tag)
        if kind is not None:
            out.append({
                'path': path,
                'kind': kind,
                'tag': tag,
                'testname': el.get('testname') or '',
                'enabled': (el.get('enabled', 'true') or 'true').lower() == 'true',
                'current_params': _extract_tg_params(el, kind),
            })
        if child_ht is not None:
            _collect_thread_groups(child_ht, f'{path}.', out)


def list_thread_groups(xml_bytes: bytes) -> list[dict[str, Any]]:
    """
    返回 JMX 里所有 ThreadGroup-like 节点的列表（含三种类型的）。
    用于 Step 2 初始化：前端显示哪些 TG、每个当前的类型和参数。
    """
    tree = _parse_tree(xml_bytes)
    try:
        top = _top_hashtree(tree)
    except JmxParseError:
        return []
    out: list[dict[str, Any]] = []
    _collect_thread_groups(top, '', out)
    return out


def validate_thread_group_params(kind: str, params: dict[str, Any]) -> None:
    """参数边界校验：超限 raise JmxParseError（上层回 400）。"""
    if kind not in _TG_KIND_TO_TAG:
        raise JmxParseError(f'未知的线程组类型: {kind}')

    def _int(name: str, min_v: int = 0, max_v: int | None = None) -> int:
        v = params.get(name)
        if not isinstance(v, int):
            try:
                v = int(v)
            except (TypeError, ValueError):
                raise JmxParseError(f'{name} 必须是整数')
        if v < min_v:
            raise JmxParseError(f'{name} 不能小于 {min_v}')
        if max_v is not None and v > max_v:
            raise JmxParseError(f'{name} 不能超过 {max_v}')
        return v

    if kind == 'ThreadGroup':
        _int('users', 1, MAX_USERS)
        _int('ramp_up', 0, MAX_DURATION_SECONDS)
        _int('duration', 1, MAX_DURATION_SECONDS)
    elif kind == 'SteppingThreadGroup':
        initial = _int('initial_threads', 0, MAX_USERS)
        step_u = _int('step_users', 0, MAX_USERS)
        step_c = _int('step_count', 0, 1000)
        if initial + step_u * step_c > MAX_USERS:
            raise JmxParseError(
                f'总用户数 ({initial + step_u * step_c}) 超过上限 {MAX_USERS}'
            )
        _int('step_delay', 0, MAX_DURATION_SECONDS)
        _int('hold', 0, MAX_DURATION_SECONDS)
        _int('shutdown', 0, MAX_DURATION_SECONDS)
    elif kind == 'ConcurrencyThreadGroup':
        _int('target_concurrency', 1, MAX_USERS)
        _int('ramp_up', 0, MAX_DURATION_SECONDS)
        _int('steps', 0, 1000)
        _int('hold', 0, MAX_DURATION_SECONDS)
        unit = params.get('unit', 'S')
        if unit not in ('S', 'M'):
            raise JmxParseError("unit 必须是 'S' 或 'M'")
    elif kind == 'ArrivalsThreadGroup':
        _int('target_rps', 1, 1_000_000)  # RPS 不按用户数限
        _int('ramp_up', 0, MAX_DURATION_SECONDS)
        _int('steps', 0, 1000)
        _int('hold', 0, MAX_DURATION_SECONDS)
        unit = params.get('unit', 'M')
        if unit not in ('S', 'M'):
            raise JmxParseError("unit 必须是 'S' 或 'M'")
    elif kind == 'UltimateThreadGroup':
        _int('users', 1, MAX_USERS)
        _int('initial_delay', 0, MAX_DURATION_SECONDS)
        _int('ramp_up', 0, MAX_DURATION_SECONDS)
        _int('hold', 0, MAX_DURATION_SECONDS)
        _int('shutdown', 0, MAX_DURATION_SECONDS)


def _build_standard_tg(testname: str, enabled: str, p: dict[str, Any]) -> etree._Element:
    el = etree.Element('ThreadGroup', {
        'guiclass': 'ThreadGroupGui',
        'testclass': 'ThreadGroup',
        'testname': testname,
        'enabled': enabled,
    })
    etree.SubElement(el, 'stringProp', {'name': 'ThreadGroup.on_sample_error'}).text = 'continue'

    controller = etree.SubElement(el, 'elementProp', {
        'name': 'ThreadGroup.main_controller',
        'elementType': 'LoopController',
        'guiclass': 'LoopControlPanel',
        'testclass': 'LoopController',
        'testname': 'Loop Controller',
        'enabled': 'true',
    })
    etree.SubElement(controller, 'boolProp', {'name': 'LoopController.continue_forever'}).text = 'false'
    # -1 = 无限循环，由 scheduler + duration 负责停止
    etree.SubElement(controller, 'stringProp', {'name': 'LoopController.loops'}).text = '-1'

    etree.SubElement(el, 'stringProp', {'name': 'ThreadGroup.num_threads'}).text = str(p['users'])
    etree.SubElement(el, 'stringProp', {'name': 'ThreadGroup.ramp_time'}).text = str(p['ramp_up'])
    etree.SubElement(el, 'boolProp', {'name': 'ThreadGroup.scheduler'}).text = 'true'
    etree.SubElement(el, 'stringProp', {'name': 'ThreadGroup.duration'}).text = str(p['duration'])
    etree.SubElement(el, 'stringProp', {'name': 'ThreadGroup.delay'}).text = ''
    return el


def _build_stepping_tg(testname: str, enabled: str, p: dict[str, Any]) -> etree._Element:
    tag = _TG_KIND_TO_TAG['SteppingThreadGroup']
    el = etree.Element(tag, {
        'guiclass': f'{tag}Gui',
        'testclass': tag,
        'testname': testname,
        'enabled': enabled,
    })
    etree.SubElement(el, 'stringProp', {'name': 'ThreadGroup.on_sample_error'}).text = 'continue'

    controller = etree.SubElement(el, 'elementProp', {
        'name': 'ThreadGroup.main_controller',
        'elementType': 'LoopController',
        'guiclass': 'LoopControlPanel',
        'testclass': 'LoopController',
        'testname': 'Loop Controller',
        'enabled': 'true',
    })
    etree.SubElement(controller, 'boolProp', {'name': 'LoopController.continue_forever'}).text = 'false'
    etree.SubElement(controller, 'intProp', {'name': 'LoopController.loops'}).text = '-1'

    etree.SubElement(el, 'stringProp', {'name': 'Threads initial delay'}).text = '0'
    etree.SubElement(el, 'stringProp', {'name': 'Start users count'}).text = str(p['step_users'])
    etree.SubElement(el, 'stringProp', {'name': 'Start users count burst'}).text = str(p['initial_threads'])
    etree.SubElement(el, 'stringProp', {'name': 'Start users period'}).text = str(p['step_delay'])
    etree.SubElement(el, 'stringProp', {'name': 'Stop users count'}).text = str(p['step_users'])
    etree.SubElement(el, 'stringProp', {'name': 'Stop users period'}).text = str(p['shutdown'])
    etree.SubElement(el, 'stringProp', {'name': 'flighttime'}).text = str(p['hold'])
    # rampUp = 每步内部的 ramp 秒；v1 固定每步 ramp = step_delay / 2（圆整）
    etree.SubElement(el, 'stringProp', {'name': 'rampUp'}).text = str(max(1, p['step_delay'] // 2))
    # UI 衍生字段：step_count。存在 JMX 里方便下次读出来回显（JMeter 不解析它）
    etree.SubElement(el, 'stringProp', {'name': '_step_count'}).text = str(p['step_count'])
    return el


def _build_concurrency_tg(testname: str, enabled: str, p: dict[str, Any]) -> etree._Element:
    tag = _TG_KIND_TO_TAG['ConcurrencyThreadGroup']
    el = etree.Element(tag, {
        'guiclass': f'{tag}Gui',
        'testclass': tag,
        'testname': testname,
        'enabled': enabled,
    })
    # Concurrency TG 用自己的 controller（不是 LoopController）
    etree.SubElement(el, 'elementProp', {
        'name': 'ThreadGroup.main_controller',
        'elementType': 'com.blazemeter.jmeter.control.VirtualUserController',
    })
    etree.SubElement(el, 'stringProp', {'name': 'ThreadGroup.on_sample_error'}).text = 'continue'
    etree.SubElement(el, 'stringProp', {'name': 'TargetLevel'}).text = str(p['target_concurrency'])
    etree.SubElement(el, 'stringProp', {'name': 'RampUp'}).text = str(p['ramp_up'])
    etree.SubElement(el, 'stringProp', {'name': 'Steps'}).text = str(p['steps'])
    etree.SubElement(el, 'stringProp', {'name': 'Hold'}).text = str(p['hold'])
    etree.SubElement(el, 'stringProp', {'name': 'LogFilename'}).text = ''
    etree.SubElement(el, 'stringProp', {'name': 'Iterations'}).text = ''
    etree.SubElement(el, 'stringProp', {'name': 'Unit'}).text = p.get('unit', 'S')
    return el


def _build_arrivals_tg(testname: str, enabled: str, p: dict[str, Any]) -> etree._Element:
    tag = _TG_KIND_TO_TAG['ArrivalsThreadGroup']
    el = etree.Element(tag, {
        'guiclass': f'{tag}Gui',
        'testclass': tag,
        'testname': testname,
        'enabled': enabled,
    })
    etree.SubElement(el, 'elementProp', {
        'name': 'ThreadGroup.main_controller',
        'elementType': 'com.blazemeter.jmeter.control.VirtualUserController',
    })
    etree.SubElement(el, 'stringProp', {'name': 'ThreadGroup.on_sample_error'}).text = 'continue'
    etree.SubElement(el, 'stringProp', {'name': 'TargetLevel'}).text = str(p['target_rps'])
    etree.SubElement(el, 'stringProp', {'name': 'RampUp'}).text = str(p['ramp_up'])
    etree.SubElement(el, 'stringProp', {'name': 'Steps'}).text = str(p['steps'])
    etree.SubElement(el, 'stringProp', {'name': 'Hold'}).text = str(p['hold'])
    etree.SubElement(el, 'stringProp', {'name': 'LogFilename'}).text = ''
    etree.SubElement(el, 'stringProp', {'name': 'Iterations'}).text = ''
    etree.SubElement(el, 'stringProp', {'name': 'Unit'}).text = p.get('unit', 'M')
    # ConcurrencyLimit: 自动伸缩的 worker 线程上限；用 MAX_USERS 兜住
    etree.SubElement(el, 'intProp', {'name': 'ConcurrencyLimit'}).text = str(MAX_USERS)
    return el


def _build_ultimate_tg(testname: str, enabled: str, p: dict[str, Any]) -> etree._Element:
    tag = _TG_KIND_TO_TAG['UltimateThreadGroup']
    el = etree.Element(tag, {
        'guiclass': f'{tag}Gui',
        'testclass': tag,
        'testname': testname,
        'enabled': enabled,
    })
    # ultimatethreadgroupdata：v1 Ultimate 只写单行（用户想要多行 v1.1 再说）
    data = etree.SubElement(el, 'collectionProp', {'name': 'ultimatethreadgroupdata'})
    row = etree.SubElement(data, 'collectionProp', {'name': '1234567'})
    etree.SubElement(row, 'stringProp', {'name': '1'}).text = str(p['users'])
    etree.SubElement(row, 'stringProp', {'name': '2'}).text = str(p['initial_delay'])
    etree.SubElement(row, 'stringProp', {'name': '3'}).text = str(p['ramp_up'])
    etree.SubElement(row, 'stringProp', {'name': '4'}).text = str(p['hold'])
    etree.SubElement(row, 'stringProp', {'name': '5'}).text = str(p['shutdown'])

    controller = etree.SubElement(el, 'elementProp', {
        'name': 'ThreadGroup.main_controller',
        'elementType': 'LoopController',
        'guiclass': 'LoopControlPanel',
        'testclass': 'LoopController',
        'testname': 'Loop Controller',
        'enabled': 'true',
    })
    etree.SubElement(controller, 'boolProp', {'name': 'LoopController.continue_forever'}).text = 'false'
    etree.SubElement(controller, 'intProp', {'name': 'LoopController.loops'}).text = '-1'
    etree.SubElement(el, 'stringProp', {'name': 'ThreadGroup.on_sample_error'}).text = 'continue'
    return el


_TG_BUILDERS = {
    'ThreadGroup': _build_standard_tg,
    'SteppingThreadGroup': _build_stepping_tg,
    'ConcurrencyThreadGroup': _build_concurrency_tg,
    'ArrivalsThreadGroup': _build_arrivals_tg,
    'UltimateThreadGroup': _build_ultimate_tg,
}


def replace_thread_group(
    xml_bytes: bytes, path: str, kind: str, params: dict[str, Any],
    testname: str | None = None,
) -> bytes:
    """
    原地替换 path 位置的 ThreadGroup 元素为指定 kind 的新元素。

    - 校验 params 合法
    - 保留原节点的 testname（除非显式传入）和 enabled 属性
    - 紧跟的 hashTree（装子 Samplers/HeaderManager 等）**保持不动**
    - 其他 JMX 结构全部原样保留
    """
    validate_thread_group_params(kind, params)

    tree = _parse_tree(xml_bytes)
    top = _top_hashtree(tree)
    target = _locate_by_path(top, path)

    existing_tag = _local(target)
    if _tg_kind_from_tag(existing_tag) is None:
        raise JmxParseError(
            f'path {path} 指向的不是 ThreadGroup（tag={existing_tag}），不能替换'
        )

    preserved_testname = testname if testname is not None else (target.get('testname') or '')
    preserved_enabled = target.get('enabled', 'true')

    builder = _TG_BUILDERS[kind]
    new_el = builder(preserved_testname, preserved_enabled, params)

    parent = target.getparent()
    if parent is None:
        raise JmxParseError('内部错误：ThreadGroup 没有父节点')
    parent.replace(target, new_el)

    return etree.tostring(tree, xml_declaration=True, encoding='UTF-8')


# ─── Component detail (HTTPSampler / HeaderManager 简单编辑) ──────────────

# v1 支持的编辑类型 + 字段清单
_HTTPSAMPLER_FIELDS = ('domain', 'port', 'protocol', 'method', 'path')


def _str_prop(parent: etree._Element, name: str) -> str:
    """读直接子 <stringProp name=".."> 的文本，不存在返回空串。"""
    el = parent.find(f"stringProp[@name='{name}']")
    return (el.text or '') if el is not None else ''


def _set_str_prop(parent: etree._Element, name: str, value: str) -> None:
    """写直接子 <stringProp name=".."> 的文本；不存在则新建。"""
    el = parent.find(f"stringProp[@name='{name}']")
    if el is None:
        el = etree.SubElement(parent, 'stringProp', {'name': name})
    el.text = value or ''


def _bool_prop(parent: etree._Element, name: str) -> bool:
    """读直接子 <boolProp name=".."> 的文本（缺省 / 非 true 都当 false）。"""
    el = parent.find(f"boolProp[@name='{name}']")
    if el is None or el.text is None:
        return False
    return el.text.strip().lower() == 'true'


def _set_bool_prop(parent: etree._Element, name: str, value: bool) -> None:
    el = parent.find(f"boolProp[@name='{name}']")
    if el is None:
        el = etree.SubElement(parent, 'boolProp', {'name': name})
    el.text = 'true' if value else 'false'


def _remove_bool_prop(parent: etree._Element, name: str) -> None:
    for el in parent.findall(f"boolProp[@name='{name}']"):
        parent.remove(el)


def _ensure_http_args_coll(sampler: etree._Element) -> etree._Element:
    """确保 HTTPsampler.Arguments > Arguments.arguments 这个 collection 存在并返回。"""
    wrapper = sampler.find("elementProp[@name='HTTPsampler.Arguments']")
    if wrapper is None:
        wrapper = etree.SubElement(sampler, 'elementProp', {
            'name': 'HTTPsampler.Arguments',
            'elementType': 'Arguments',
            'guiclass': 'HTTPArgumentsPanel',
            'testclass': 'Arguments',
            'testname': 'User Defined Variables',
            'enabled': 'true',
        })
    coll = wrapper.find("collectionProp[@name='Arguments.arguments']")
    if coll is None:
        coll = etree.SubElement(wrapper, 'collectionProp', {'name': 'Arguments.arguments'})
    return coll


def _ensure_http_files_coll(sampler: etree._Element) -> etree._Element:
    """确保 HTTPsampler.Files > HTTPFileArgs.files 这个 collection 存在并返回。"""
    wrapper = sampler.find("elementProp[@name='HTTPsampler.Files']")
    if wrapper is None:
        wrapper = etree.SubElement(sampler, 'elementProp', {
            'name': 'HTTPsampler.Files',
            'elementType': 'HTTPFileArgs',
        })
    coll = wrapper.find("collectionProp[@name='HTTPFileArgs.files']")
    if coll is None:
        coll = etree.SubElement(wrapper, 'collectionProp', {'name': 'HTTPFileArgs.files'})
    return coll


def get_component_detail(xml_bytes: bytes, path: str) -> dict[str, Any]:
    """返回组件的编辑字段结构（按 `kind` 不同 schema）。v1 只支持：
    - HTTPSamplerProxy: `{kind, domain, port, protocol, method, path}`
    - HeaderManager:    `{kind, headers: [{name, value}, ...]}`
    其他 tag 抛 JmxParseError（上层会回 400）。
    """
    tree = _parse_tree(xml_bytes)
    top = _top_hashtree(tree)
    el = _locate_by_path(top, path)
    tag = _local(el)

    if tag == 'HTTPSamplerProxy':
        # Body mode: JMeter 区分"参数列表"(postBodyRaw=false) 和"原始消息体"
        # (postBodyRaw=true)。raw 模式下 Arguments 里只放一条，`Argument.value`
        # 就是整个 body；params 模式下每条 elementProp 是一个 name/value 对。
        body_raw = _bool_prop(el, 'HTTPSampler.postBodyRaw')

        params: list[dict[str, str]] = []
        body = ''
        args_wrapper = el.find("elementProp[@name='HTTPsampler.Arguments']")
        args_coll = (
            args_wrapper.find("collectionProp[@name='Arguments.arguments']")
            if args_wrapper is not None else None
        )
        if args_coll is not None:
            eprops = args_coll.findall('elementProp')
            if body_raw:
                if eprops:
                    body = _str_prop(eprops[0], 'Argument.value')
            else:
                for eprop in eprops:
                    params.append({
                        'name': _str_prop(eprop, 'Argument.name'),
                        'value': _str_prop(eprop, 'Argument.value'),
                    })

        files: list[dict[str, str]] = []
        files_wrapper = el.find("elementProp[@name='HTTPsampler.Files']")
        files_coll = (
            files_wrapper.find("collectionProp[@name='HTTPFileArgs.files']")
            if files_wrapper is not None else None
        )
        if files_coll is not None:
            for eprop in files_coll.findall('elementProp'):
                files.append({
                    'path': _str_prop(eprop, 'File.path'),
                    'paramname': _str_prop(eprop, 'File.paramname'),
                    'mimetype': _str_prop(eprop, 'File.mimetype'),
                })

        return {
            'kind': 'HTTPSamplerProxy',
            'domain': _str_prop(el, 'HTTPSampler.domain'),
            'port': _str_prop(el, 'HTTPSampler.port'),
            'protocol': _str_prop(el, 'HTTPSampler.protocol'),
            'method': _str_prop(el, 'HTTPSampler.method'),
            'path': _str_prop(el, 'HTTPSampler.path'),
            'bodyMode': 'raw' if body_raw else 'params',
            'params': params,
            'body': body,
            'files': files,
        }

    if tag == 'HeaderManager':
        headers: list[dict[str, str]] = []
        coll = el.find("collectionProp[@name='HeaderManager.headers']")
        if coll is not None:
            for eprop in coll.findall('elementProp'):
                headers.append({
                    'name': _str_prop(eprop, 'Header.name'),
                    'value': _str_prop(eprop, 'Header.value'),
                })
        return {'kind': 'HeaderManager', 'headers': headers}

    raise JmxParseError(f'组件 {tag} 暂不支持编辑（v1 仅 HTTPSamplerProxy / HeaderManager）')


def update_component_detail(
    xml_bytes: bytes,
    path: str,
    kind: str,
    fields: dict[str, Any],
) -> bytes:
    """按 `kind` 把 `fields` 写回组件。只动业务字段，其余结构原样保留。"""
    tree = _parse_tree(xml_bytes)
    top = _top_hashtree(tree)
    el = _locate_by_path(top, path)
    actual_tag = _local(el)

    if kind != actual_tag:
        raise JmxParseError(f'kind ({kind}) 和实际组件 ({actual_tag}) 不匹配')

    if kind == 'HTTPSamplerProxy':
        for key in _HTTPSAMPLER_FIELDS:
            if key in fields:
                val = fields[key]
                if not isinstance(val, str):
                    raise JmxParseError(f'字段 {key} 必须是字符串')
                _set_str_prop(el, f'HTTPSampler.{key}', val)

        # Body mode + params 或 raw body（任一变化就整条 collection 重建）
        if 'bodyMode' in fields:
            mode = fields['bodyMode']
            if mode not in ('params', 'raw'):
                raise JmxParseError('bodyMode 必须是 "params" 或 "raw"')
            args_coll = _ensure_http_args_coll(el)
            for child in list(args_coll):
                args_coll.remove(child)

            if mode == 'raw':
                body = fields.get('body', '')
                if not isinstance(body, str):
                    raise JmxParseError('body 必须是字符串')
                eprop = etree.SubElement(args_coll, 'elementProp', {
                    'name': '', 'elementType': 'HTTPArgument',
                })
                etree.SubElement(eprop, 'boolProp', {'name': 'HTTPArgument.always_encode'}).text = 'false'
                etree.SubElement(eprop, 'stringProp', {'name': 'Argument.value'}).text = body
                etree.SubElement(eprop, 'stringProp', {'name': 'Argument.metadata'}).text = '='
                _set_bool_prop(el, 'HTTPSampler.postBodyRaw', True)
            else:
                params = fields.get('params', [])
                if not isinstance(params, list):
                    raise JmxParseError('params 必须是数组 [{name, value}, ...]')
                for p in params:
                    if not isinstance(p, dict):
                        raise JmxParseError('params 每一项必须是 {name, value} 对象')
                    name = str(p.get('name', ''))
                    value = str(p.get('value', ''))
                    eprop = etree.SubElement(args_coll, 'elementProp', {
                        'name': name, 'elementType': 'HTTPArgument',
                    })
                    etree.SubElement(eprop, 'boolProp', {'name': 'HTTPArgument.always_encode'}).text = 'false'
                    etree.SubElement(eprop, 'stringProp', {'name': 'Argument.value'}).text = value
                    etree.SubElement(eprop, 'stringProp', {'name': 'Argument.metadata'}).text = '='
                    etree.SubElement(eprop, 'boolProp', {'name': 'HTTPArgument.use_equals'}).text = 'true'
                    etree.SubElement(eprop, 'stringProp', {'name': 'Argument.name'}).text = name
                _remove_bool_prop(el, 'HTTPSampler.postBodyRaw')

        if 'files' in fields:
            files = fields['files']
            if not isinstance(files, list):
                raise JmxParseError('files 必须是数组 [{path, paramname, mimetype}, ...]')
            files_coll = _ensure_http_files_coll(el)
            for child in list(files_coll):
                files_coll.remove(child)
            for f in files:
                if not isinstance(f, dict):
                    raise JmxParseError('files 每一项必须是 {path, paramname, mimetype} 对象')
                path_v = str(f.get('path', ''))
                paramname = str(f.get('paramname', ''))
                mimetype = str(f.get('mimetype', ''))
                eprop = etree.SubElement(files_coll, 'elementProp', {
                    'name': path_v, 'elementType': 'HTTPFileArg',
                })
                etree.SubElement(eprop, 'stringProp', {'name': 'File.path'}).text = path_v
                etree.SubElement(eprop, 'stringProp', {'name': 'File.paramname'}).text = paramname
                etree.SubElement(eprop, 'stringProp', {'name': 'File.mimetype'}).text = mimetype

    elif kind == 'HeaderManager':
        headers = fields.get('headers')
        if not isinstance(headers, list):
            raise JmxParseError('headers 必须是数组 [{name, value}, ...]')
        # 整个 collectionProp 重建最简单也最稳：保持结构清爽
        for existing in el.findall("collectionProp[@name='HeaderManager.headers']"):
            el.remove(existing)
        coll = etree.SubElement(el, 'collectionProp', {'name': 'HeaderManager.headers'})
        for h in headers:
            if not isinstance(h, dict):
                raise JmxParseError('headers 每一项必须是 {name, value} 对象')
            name = str(h.get('name', ''))
            value = str(h.get('value', ''))
            eprop = etree.SubElement(coll, 'elementProp', {
                'name': name,
                'elementType': 'Header',
            })
            etree.SubElement(eprop, 'stringProp', {'name': 'Header.name'}).text = name
            etree.SubElement(eprop, 'stringProp', {'name': 'Header.value'}).text = value

    else:
        raise JmxParseError(f'组件 {kind} 暂不支持编辑（v1 仅 HTTPSamplerProxy / HeaderManager）')

    return etree.tostring(tree, xml_declaration=True, encoding='UTF-8')
