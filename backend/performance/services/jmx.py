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
    kind: str = ''         # 前端规范化类型（通常等于 tag；ConfigTestElement 按 guiclass 区分）
    children: list['JmxComponent'] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'path': self.path,
            'tag': self.tag,
            'testname': self.testname,
            'enabled': self.enabled,
            'kind': self.kind,
            'children': [c.to_dict() for c in self.children],
        }


def _compute_kind(tag: str, guiclass: str) -> str:
    """把 tag + guiclass 映射成前端可用的规范化 kind 字符串。

    - ConfigTestElement+HttpDefaultsGui → 'HttpDefaults'
    - 插件型 ThreadGroup（含包名的 tag）→ 短名（'SteppingThreadGroup' 等），
      与 _TG_KIND_TO_TAG / 前端 TG_KINDS 集合对齐，避免双方各自维护两套字符串
    - 其它情况 kind == tag
    """
    if tag == 'ConfigTestElement' and guiclass == 'HttpDefaultsGui':
        return 'HttpDefaults'
    tg_kind = _TAG_TO_TG_KIND.get(tag)
    if tg_kind is not None:
        return tg_kind
    return tag


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
        tag = _local(el)
        guiclass = el.get('guiclass', '') or ''
        kind = _compute_kind(tag, guiclass)
        children = (
            _walk_components(child_ht, f'{path}.') if child_ht is not None else []
        )
        out.append(JmxComponent(
            path=path,
            tag=tag,
            testname=el.get('testname') or '',
            enabled=(el.get('enabled', 'true') or 'true').lower() == 'true',
            kind=kind,
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
        def _parse_row(row_el: etree._Element) -> dict[str, int]:
            def _ri(idx: str, fb: int) -> int:
                e = row_el.find(f"stringProp[@name='{idx}']")
                try:
                    return int((e.text or '').strip()) if e is not None else fb
                except (ValueError, AttributeError):
                    return fb
            return {
                'users': _ri('1', 100),
                'initial_delay': _ri('2', 0),
                'ramp_up': _ri('3', 5),
                'hold': _ri('4', 60),
                'shutdown': _ri('5', 5),
            }
        data = el.find("collectionProp[@name='ultimatethreadgroupdata']")
        if data is not None:
            xml_rows = data.findall('collectionProp')
            if xml_rows:
                return {'rows': [_parse_row(r) for r in xml_rows]}
        return {'rows': [{'users': 100, 'initial_delay': 0, 'ramp_up': 5, 'hold': 60, 'shutdown': 5}]}
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
        _int('steps', 0, 1000)
        unit = params.get('unit', 'S')
        if unit not in ('S', 'M'):
            raise JmxParseError("unit 必须是 'S' 或 'M'")
        # ramp_up / hold 单位跟随 Unit：S 时 cap 12 小时 = 43200 秒；M 时 cap 720 分钟
        cap = MAX_DURATION_SECONDS if unit == 'S' else MAX_DURATION_SECONDS // 60
        _int('ramp_up', 0, cap)
        _int('hold', 0, cap)
    elif kind == 'ArrivalsThreadGroup':
        _int('target_rps', 1, 1_000_000)  # RPS 不按用户数限
        _int('steps', 0, 1000)
        unit = params.get('unit', 'M')
        if unit not in ('S', 'M'):
            raise JmxParseError("unit 必须是 'S' 或 'M'")
        cap = MAX_DURATION_SECONDS if unit == 'S' else MAX_DURATION_SECONDS // 60
        _int('ramp_up', 0, cap)
        _int('hold', 0, cap)
    elif kind == 'UltimateThreadGroup':
        # 兼容老格式（flat dict）→ 包成 rows
        if 'rows' not in params and 'users' in params:
            rows_to_validate = [params]
        else:
            rows_to_validate = params.get('rows', [])
        if not rows_to_validate:
            raise JmxParseError('峰值场景至少要有一个波峰')
        for peak_idx, row in enumerate(rows_to_validate, 1):
            label = f'波峰 {peak_idx}'
            def _row_int(name: str, min_v: int = 0, max_v: int | None = None,
                         _row: dict = row, _lbl: str = label) -> int:
                v = _row.get(name)
                if not isinstance(v, int):
                    try:
                        v = int(v)
                    except (TypeError, ValueError):
                        raise JmxParseError(f'{_lbl} 的 {name} 必须是整数')
                if v < min_v:
                    raise JmxParseError(f'{_lbl} 的 {name} 不能小于 {min_v}')
                if max_v is not None and v > max_v:
                    raise JmxParseError(f'{_lbl} 的 {name} 不能超过 {max_v}')
                return v
            _row_int('users', 1, MAX_USERS)
            _row_int('initial_delay', 0, MAX_DURATION_SECONDS)
            _row_int('ramp_up', 0, MAX_DURATION_SECONDS)
            _row_int('hold', 0, MAX_DURATION_SECONDS)
            _row_int('shutdown', 0, MAX_DURATION_SECONDS)


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

    # SteppingTG 必须写入 ThreadGroup.num_threads (= 总目标用户数)，否则 JMeter
    # 默认 0，整个组空跑。total = 初始 + 每步 × 步数。
    total = int(p['initial_threads']) + int(p['step_users']) * int(p['step_count'])
    etree.SubElement(el, 'stringProp', {'name': 'ThreadGroup.num_threads'}).text = str(total)
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
    data = etree.SubElement(el, 'collectionProp', {'name': 'ultimatethreadgroupdata'})
    # 兼容老格式（flat dict）→ 包成 rows
    rows = p['rows'] if 'rows' in p else [p]
    for i, row_data in enumerate(rows):
        row_el = etree.SubElement(data, 'collectionProp', {'name': str(i)})
        etree.SubElement(row_el, 'stringProp', {'name': '1'}).text = str(row_data.get('users', 100))
        etree.SubElement(row_el, 'stringProp', {'name': '2'}).text = str(row_data.get('initial_delay', 0))
        etree.SubElement(row_el, 'stringProp', {'name': '3'}).text = str(row_data.get('ramp_up', 5))
        etree.SubElement(row_el, 'stringProp', {'name': '4'}).text = str(row_data.get('hold', 60))
        etree.SubElement(row_el, 'stringProp', {'name': '5'}).text = str(row_data.get('shutdown', 5))

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


def _set_any_prop(parent: etree._Element, name: str, value: str) -> None:
    """更新已有的 stringProp/intProp（任意一种），不存在则新建 stringProp。"""
    el = _find_prop(parent, name)
    if el is None:
        el = etree.SubElement(parent, 'stringProp', {'name': name})
    el.text = value or ''


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

    guiclass = el.get('guiclass', '') or ''
    kind = _compute_kind(tag, guiclass)

    if kind == 'HttpDefaults':
        connect_el = _find_prop(el, 'HTTPSampler.connect_timeout')
        response_el = _find_prop(el, 'HTTPSampler.response_timeout')
        return {
            'kind': 'HttpDefaults',
            'domain': _str_prop(el, 'HTTPSampler.domain'),
            'port': _str_prop(el, 'HTTPSampler.port'),
            'protocol': _str_prop(el, 'HTTPSampler.protocol'),
            'path': _str_prop(el, 'HTTPSampler.path'),
            'contentEncoding': _str_prop(el, 'HTTPSampler.contentEncoding'),
            'connectTimeout': (connect_el.text or '') if connect_el is not None else '',
            'responseTimeout': (response_el.text or '') if response_el is not None else '',
            'implementation': _str_prop(el, 'HTTPSampler.implementation'),
            'followRedirects': _bool_prop(el, 'HTTPSampler.follow_redirects'),
            'useKeepAlive': _bool_prop(el, 'HTTPSampler.use_keepalive'),
        }

    if tag == 'JSONPathAssertion':
        return {
            'kind': 'JSONPathAssertion',
            'jsonPath': _str_prop(el, 'JSON_PATH'),
            'expectedValue': _str_prop(el, 'EXPECTED_VALUE'),
            'jsonValidation': _bool_prop(el, 'JSONVALIDATION'),
            'expectNull': _bool_prop(el, 'EXPECT_NULL'),
            'invert': _bool_prop(el, 'INVERT'),
            'isRegex': _bool_prop(el, 'ISREGEX'),
        }

    if tag in ('BeanShellPostProcessor', 'BeanShellPreProcessor'):
        return {
            'kind': tag,
            'script': _str_prop(el, 'script'),
            'parameters': _str_prop(el, 'parameters'),
            'resetInterpreter': _bool_prop(el, 'resetInterpreter'),
        }

    if tag == 'RegexExtractor':
        return {
            'kind': 'RegexExtractor',
            'refname': _str_prop(el, 'RegexExtractor.refname'),
            'regex': _str_prop(el, 'RegexExtractor.regex'),
            'template': _str_prop(el, 'RegexExtractor.template'),
            'default': _str_prop(el, 'RegexExtractor.default'),
            'matchNumber': _str_prop(el, 'RegexExtractor.match_number'),
            'useHeaders': _str_prop(el, 'RegexExtractor.useHeaders'),
        }

    if tag == 'JSONPathExtractor':
        return {
            'kind': 'JSONPathExtractor',
            'varName': _str_prop(el, 'JSONPostProcessor.referenceNames'),
            'jsonpath': _str_prop(el, 'JSONPostProcessor.jsonPathExprs'),
            'default': _str_prop(el, 'JSONPostProcessor.defaultValues'),
            'matchNo': _str_prop(el, 'JSONPostProcessor.match_numbers'),
        }

    if tag == 'CSVDataSet':
        return {
            'kind': 'CSVDataSet',
            'variableNames': _str_prop(el, 'variableNames'),
            'delimiter': _str_prop(el, 'delimiter'),
            'fileEncoding': _str_prop(el, 'fileEncoding'),
            'ignoreFirstLine': _bool_prop(el, 'ignoreFirstLine'),
            'quotedData': _bool_prop(el, 'quotedData'),
            'recycle': _bool_prop(el, 'recycle'),
            'stopThread': _bool_prop(el, 'stopThread'),
            'shareMode': _str_prop(el, 'shareMode'),
        }

    raise JmxParseError(f'组件 {tag} 暂不支持编辑')


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

    # HttpDefaults 的 kind 和 actual_tag 不同（ConfigTestElement），单独允许
    _KIND_EXPECTED_TAG: dict[str, str] = {'HttpDefaults': 'ConfigTestElement'}
    expected_tag = _KIND_EXPECTED_TAG.get(kind, kind)
    if actual_tag != expected_tag:
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

    elif kind == 'HttpDefaults':
        for key in ('domain', 'port', 'protocol', 'path', 'contentEncoding', 'implementation'):
            if key in fields:
                val = fields[key]
                if not isinstance(val, str):
                    raise JmxParseError(f'字段 {key} 必须是字符串')
                _set_any_prop(el, f'HTTPSampler.{key}', val)
        if 'connectTimeout' in fields:
            _set_any_prop(el, 'HTTPSampler.connect_timeout', str(fields['connectTimeout']))
        if 'responseTimeout' in fields:
            _set_any_prop(el, 'HTTPSampler.response_timeout', str(fields['responseTimeout']))
        if 'followRedirects' in fields:
            _set_bool_prop(el, 'HTTPSampler.follow_redirects', bool(fields['followRedirects']))
        if 'useKeepAlive' in fields:
            _set_bool_prop(el, 'HTTPSampler.use_keepalive', bool(fields['useKeepAlive']))

    elif kind == 'JSONPathAssertion':
        if 'jsonPath' in fields:
            _set_str_prop(el, 'JSON_PATH', str(fields['jsonPath']))
        if 'expectedValue' in fields:
            _set_str_prop(el, 'EXPECTED_VALUE', str(fields['expectedValue']))
        _JSON_ASSERT_BOOL_MAP = {
            'jsonValidation': 'JSONVALIDATION',
            'expectNull': 'EXPECT_NULL',
            'invert': 'INVERT',
            'isRegex': 'ISREGEX',
        }
        for fk, pk in _JSON_ASSERT_BOOL_MAP.items():
            if fk in fields:
                _set_bool_prop(el, pk, bool(fields[fk]))

    elif kind in ('BeanShellPostProcessor', 'BeanShellPreProcessor'):
        if 'script' in fields:
            _set_str_prop(el, 'script', str(fields['script']))
        if 'parameters' in fields:
            _set_str_prop(el, 'parameters', str(fields['parameters']))
        if 'resetInterpreter' in fields:
            _set_bool_prop(el, 'resetInterpreter', bool(fields['resetInterpreter']))

    elif kind == 'RegexExtractor':
        _REGEX_FIELD_MAP = {
            'refname': 'RegexExtractor.refname',
            'regex': 'RegexExtractor.regex',
            'template': 'RegexExtractor.template',
            'default': 'RegexExtractor.default',
            'matchNumber': 'RegexExtractor.match_number',
            'useHeaders': 'RegexExtractor.useHeaders',
        }
        for fk, pk in _REGEX_FIELD_MAP.items():
            if fk in fields:
                _set_str_prop(el, pk, str(fields[fk]))

    elif kind == 'JSONPathExtractor':
        _JSON_EXT_FIELD_MAP = {
            'varName': 'JSONPostProcessor.referenceNames',
            'jsonpath': 'JSONPostProcessor.jsonPathExprs',
            'default': 'JSONPostProcessor.defaultValues',
            'matchNo': 'JSONPostProcessor.match_numbers',
        }
        for fk, pk in _JSON_EXT_FIELD_MAP.items():
            if fk in fields:
                _set_str_prop(el, pk, str(fields[fk]))

    elif kind == 'CSVDataSet':
        for fk in ('variableNames', 'delimiter', 'fileEncoding', 'shareMode'):
            if fk in fields:
                _set_str_prop(el, fk, str(fields[fk]))
        for bool_key in ('ignoreFirstLine', 'quotedData', 'recycle', 'stopThread'):
            if bool_key in fields:
                _set_bool_prop(el, bool_key, bool(fields[bool_key]))
        # Never write 'filename' — that's managed by TaskCsvBinding

    else:
        raise JmxParseError(f'组件 {kind} 暂不支持编辑')

    return etree.tostring(tree, xml_declaration=True, encoding='UTF-8')


# ─── 内存生成可执行 JMX（取代 _run.jmx 物理派生） ─────────────────────────


def _set_csv_filename_at_path(xml_bytes: bytes, path: str, filename: str) -> bytes:
    """把 path 位置（必须是 CSVDataSet）的 filename 字段设为指定绝对路径。"""
    tree = _parse_tree(xml_bytes)
    top = _top_hashtree(tree)
    el = _locate_by_path(top, path)
    if _local(el) != 'CSVDataSet':
        raise JmxParseError(
            f'path {path} 指向的不是 CSVDataSet（tag={_local(el)}）'
        )
    _set_str_prop(el, 'filename', filename)
    return etree.tostring(tree, xml_declaration=True, encoding='UTF-8')


def _parse_host_entry(entry: dict | str) -> tuple[str, str] | None:
    """
    把单条 host_entries 条目统一成 (hostname, ip)。
    支持两种格式：
      - dict: {"hostname": "api.foo.com", "ip": "10.0.0.1"}
      - str:  "10.0.0.1 api.foo.com"（/etc/hosts 风格，# 开头为注释）
    无法解析或注释行返回 None。
    """
    if isinstance(entry, dict):
        h = (entry.get('hostname') or '').strip()
        i = (entry.get('ip') or '').strip()
        return (h, i) if h and i else None
    if isinstance(entry, str):
        line = entry.split('#')[0].strip()
        parts = line.split()
        if len(parts) >= 2:
            return (parts[1].strip(), parts[0].strip())
    return None


def _inject_dns_cache_manager(
    xml_bytes: bytes, host_entries: list,
    *, warnings: list[str] | None = None,
) -> bytes:
    """
    在 TestPlan 的 hashTree 顶部注入一个 DNSCacheManager，把指定 hostname 直接
    映射到 ip——执行压测时 JMeter 走 IP 直连，不依赖系统 DNS。

    `host_entries`: dict 列表 `[{"hostname": ..., "ip": ...}]` 或
                    /etc/hosts 风格字符串列表 `["10.0.0.1 api.foo.com"]`，两种格式均支持。
    空列表 / None → 不注入，原样返回。
    `warnings`: 调用方传入的列表，用于收集"为什么没注入"的人话提示（比如域名对不上）。
    """
    pairs = [r for e in (host_entries or []) if (r := _parse_host_entry(e))]
    if not pairs:
        return xml_bytes

    # 只注入 JMX 里实际用到的域名，避免冗余 StaticHost 条目干扰
    tree = _parse_tree(xml_bytes)
    used_domains: set[str] = set()
    for sampler in tree.iter('HTTPSamplerProxy'):
        if sampler.get('enabled', 'true').lower() == 'false':
            continue
        for sp in sampler.findall('stringProp'):
            if sp.get('name') == 'HTTPSampler.domain' and sp.text:
                d = sp.text.strip()
                if d:
                    used_domains.add(d)
    matched = [(h, i) for h, i in pairs if h in used_domains]
    if not matched:
        if warnings is not None and used_domains:
            doms = ', '.join(sorted(used_domains))
            warnings.append(
                f'环境 hosts 里没有匹配脚本域名的条目（脚本用到：{doms}），'
                f'DNS 注入跳过；JMeter 将走系统 DNS 解析'
            )
        return xml_bytes
    pairs = matched
    top = _top_hashtree(tree)

    # TestPlan 的 hashTree 是 top 的第一个 hashTree 子节点（或 top 自己——我们就放在 top 里）
    dns_mgr = etree.SubElement(top, 'DNSCacheManager', {
        'guiclass': 'DNSCachePanel',
        'testclass': 'DNSCacheManager',
        'testname': 'Falcon Environment DNS',
        'enabled': 'true',
    })
    coll = etree.SubElement(dns_mgr, 'collectionProp', {
        'name': 'DNSCacheManager.hosts',
    })
    for hostname, ip in pairs:
        eprop = etree.SubElement(coll, 'elementProp', {
            'name': hostname, 'elementType': 'StaticHost',
        })
        etree.SubElement(eprop, 'stringProp', {'name': 'StaticHost.Name'}).text = hostname
        etree.SubElement(eprop, 'stringProp', {'name': 'StaticHost.Address'}).text = ip
    etree.SubElement(dns_mgr, 'collectionProp', {'name': 'DNSCacheManager.servers'})
    etree.SubElement(dns_mgr, 'boolProp', {'name': 'DNSCacheManager.clearEachIteration'}).text = 'false'
    etree.SubElement(dns_mgr, 'boolProp', {'name': 'DNSCacheManager.isCustomResolver'}).text = 'true'

    # DNSCacheManager 后面紧跟一个空 hashTree（JMeter 配对结构要求）
    etree.SubElement(top, 'hashTree')

    return etree.tostring(tree, xml_declaration=True, encoding='UTF-8')


def _inject_backend_listener(
    xml_bytes: bytes,
    *,
    run_id: str,
    task_id: int,
    influxdb_url: str,
    influxdb_db: str,
) -> bytes:
    """
    在 TestPlan 顶层 hashTree 注入一个 BackendListener，把全部 sampler 数据推到
    InfluxDB v1.x 的 `/write?db=<db>` 端点。前端实时图、跑完归档查询都靠这条线。

    - 用 JMeter 内置 `org.apache.jmeter.visualizers.backend.influxdb.InfluxdbBackendListenerClient`
    - tag `run_id=<run_id>` `task_id=<task_id>` 让多 run 数据共表也能切片
    - 不破坏 Step 2 配置：build_run_xml 仅在 inject_backend_listener=True 时调
    """
    if not (run_id and influxdb_url and influxdb_db):
        return xml_bytes

    tree = _parse_tree(xml_bytes)
    top = _top_hashtree(tree)

    listener = etree.SubElement(top, 'BackendListener', {
        'guiclass': 'BackendListenerGui',
        'testclass': 'BackendListener',
        'testname': f'Falcon BackendListener ({run_id})',
        'enabled': 'true',
    })
    args = etree.SubElement(listener, 'elementProp', {
        'name': 'arguments',
        'elementType': 'Arguments',
        'guiclass': 'ArgumentsPanel',
        'testclass': 'Arguments',
        'enabled': 'true',
    })
    coll = etree.SubElement(args, 'collectionProp', {'name': 'Arguments.arguments'})

    # 走 v1 协议：URL = http://host:8086/write?db=<bucket>
    write_url = influxdb_url.rstrip('/') + f'/write?db={influxdb_db}'

    backend_args = [
        ('influxdbMetricsSender',
         'org.apache.jmeter.visualizers.backend.influxdb.HttpMetricsSender'),
        ('influxdbUrl', write_url),
        ('application', 'falcon'),
        ('measurement', 'jmeter'),
        ('summaryOnly', 'false'),
        # JMeter 5.6.3 BackendListener 链路有两层独立的 sampler 过滤：
        #   1. 父类 BackendListener (Filter): samplersList + useRegexpForSamplersList
        #      过滤 sampleOccurred 事件 — 决定这条 sample 要不要分发给 client
        #   2. InfluxdbBackendListenerClient 自己 (samplersToFilter Pattern):
        #      samplersRegex 单独再过滤 — 决定这条 sample 要不要进 SamplerMetric
        # 两层任一拒绝 sampler-级数据就不会写到 InfluxDB（之前只配上一层 →
        # InfluxDB 里只有 transaction=internal 的活跃线程数据）
        ('samplersList', '.*'),
        ('useRegexpForSamplersList', 'true'),
        ('samplersRegex', '.*'),
        ('testTitle', f'Falcon-Run-{run_id}'),
        # 自定义 tags：JMeter 把 TAG_<key>=<val> 自动加到每条数据点
        ('TAG_run_id', run_id),
        ('TAG_task_id', str(task_id)),
        ('percentiles', '90;95;99'),
    ]
    for k, v in backend_args:
        arg = etree.SubElement(coll, 'elementProp', {
            'name': k,
            'elementType': 'Argument',
        })
        etree.SubElement(arg, 'stringProp', {'name': 'Argument.name'}).text = k
        etree.SubElement(arg, 'stringProp', {'name': 'Argument.value'}).text = v
        etree.SubElement(arg, 'stringProp', {'name': 'Argument.metadata'}).text = '='

    etree.SubElement(listener, 'stringProp', {
        'name': 'classname',
    }).text = 'org.apache.jmeter.visualizers.backend.influxdb.InfluxdbBackendListenerClient'

    # BackendListener 后面紧跟空 hashTree（配对结构要求）
    etree.SubElement(top, 'hashTree')

    return etree.tostring(tree, xml_declaration=True, encoding='UTF-8')


def build_run_xml(
    task,
    *,
    inject_environment_dns: bool = False,
    inject_backend_listener: bool = False,
    run_id: str | None = None,
    warnings: list[str] | None = None,
) -> bytes:
    """
    从 Task 原件 + DB 配置在内存里组装出可执行 JMX，**不写盘**。

    - 读原件 `<title>.jmx` 字节流
    - 对 `task.thread_groups_config` 中每条调 `replace_thread_group` 链式 patch
    - 对 `task.csv_bindings` 中每条把 CSVDataSet 的 filename 改成绝对路径（scripts/ 下）
    - `inject_environment_dns=True` 时把 `task.environment.host_entries` 注入成
      `DNSCacheManager`（v1.1 真跑 JMeter 用，validate 不用）
    - `inject_backend_listener=True`（必须配 run_id）时注入 InfluxDB BackendListener，
      Step 3 真跑时用；preview / validate 不传保持纯净

    返回最终 XML bytes。Step 1（脚本结构）+ Step 2（跑法）+ Environment（DNS）+
    Step 3（指标推送）四类配置在这里汇合。
    """
    # 局部 import 避免循环依赖（jmx.py 是底层服务，不应依赖 models.py / settings）
    from django.conf import settings  # noqa: PLC0415
    from .jmeter import get_scripts_dir  # noqa: PLC0415

    xml = task.read_jmx_bytes()

    # 1) Thread Groups 替换
    for entry in task.thread_groups_config or []:
        path = entry.get('path')
        kind = entry.get('kind')
        params = entry.get('params') or {}
        if not path or not kind:
            continue
        xml = replace_thread_group(xml, path=path, kind=kind, params=params)

    # 2) CSVDataSet filename 改写到绝对路径
    scripts_dir = get_scripts_dir()
    for binding in task.csv_bindings.all():
        if not binding.component_path or not binding.filename:
            continue
        abs_path = str((scripts_dir / binding.filename).resolve())
        try:
            xml = _set_csv_filename_at_path(xml, binding.component_path, abs_path)
        except JmxParseError:
            # 配置悬空（path 不再指向 CSVDataSet）→ 跳过；上层 replace-jmx 已经清空过
            continue

    # 3) Environment DNS 注入（仅执行时需要）
    if inject_environment_dns and task.environment_id:
        xml = _inject_dns_cache_manager(
            xml, task.environment.host_entries or [], warnings=warnings,
        )

    # 4) BackendListener → InfluxDB（仅 Step 3 真跑时用，按 run_id 切片）
    if inject_backend_listener and run_id:
        xml = _inject_backend_listener(
            xml,
            run_id=run_id,
            task_id=task.id,
            influxdb_url=getattr(settings, 'INFLUXDB_URL', ''),
            influxdb_db=getattr(settings, 'INFLUXDB_DB', 'jmeter'),
        )

    return xml


# ─── Step 2 校验专用：所有 TG 替换成 1 线程 1 循环 ────────────────────────


def _build_validate_tg_element(testname: str, enabled: str) -> etree._Element:
    """1 thread × 1 loop × 0 ramp，无 scheduler。Step 2 "每个接口跑一次"用。"""
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
    etree.SubElement(controller, 'stringProp', {'name': 'LoopController.loops'}).text = '1'

    etree.SubElement(el, 'stringProp', {'name': 'ThreadGroup.num_threads'}).text = '1'
    etree.SubElement(el, 'stringProp', {'name': 'ThreadGroup.ramp_time'}).text = '0'
    etree.SubElement(el, 'boolProp', {'name': 'ThreadGroup.scheduler'}).text = 'false'
    etree.SubElement(el, 'stringProp', {'name': 'ThreadGroup.delay'}).text = ''
    etree.SubElement(el, 'stringProp', {'name': 'ThreadGroup.duration'}).text = ''
    return el


def replace_tgs_for_validate(xml_bytes: bytes) -> bytes:
    """把所有**启用**的 ThreadGroup-like 元素替换成 1 线程 1 循环的标准 ThreadGroup。

    Step 2 校验调用：用户配置的 5 种 TG（标准/Stepping/Concurrency/Ultimate/Arrivals）
    在校验期统统降级为 1 用户跑 1 圈，目的只是把每个 Sampler 真跑一次确认接口通不通。
    禁用的 TG 原样保留（JMeter 不会执行）。紧跟的子 hashTree 不动。"""
    tree = _parse_tree(xml_bytes)
    top = _top_hashtree(tree)

    # 先抓出所有目标元素（不能边遍历边改）
    enabled_tgs: list[etree._Element] = []
    def _walk(ht: etree._Element) -> None:
        for el, child_ht, _idx in _hashtree_pairs(ht):
            tag = _local(el)
            if _tg_kind_from_tag(tag) is not None:
                if (el.get('enabled', 'true') or 'true').lower() == 'true':
                    enabled_tgs.append(el)
            if child_ht is not None:
                _walk(child_ht)
    _walk(top)

    for old_el in enabled_tgs:
        new_el = _build_validate_tg_element(
            testname=old_el.get('testname') or 'Validate TG',
            enabled='true',
        )
        parent = old_el.getparent()
        if parent is None:
            continue
        parent.replace(old_el, new_el)

    return etree.tostring(tree, xml_declaration=True, encoding='UTF-8')


def build_validate_xml(
    task, host_entries: list | None = None,
    *, warnings: list[str] | None = None,
) -> bytes:
    """Step 2 试跑用 XML：原件 → 所有启用 TG 降级为 1 线程 1 循环 → 套 CSV 绑定 →
    可选注入 Environment DNS。**不写盘**（runner 自己写到 runs/ 目录）。

    host_entries: 显式覆盖；None 时回落到 task.environment。
    warnings: 收集生成期间的人话提示（比如 DNS 注入跳过的原因）。"""
    from .jmeter import get_scripts_dir  # noqa: PLC0415

    xml = task.read_jmx_bytes()
    xml = replace_tgs_for_validate(xml)

    scripts_dir = get_scripts_dir()
    for binding in task.csv_bindings.all():
        if not binding.component_path or not binding.filename:
            continue
        abs_path = str((scripts_dir / binding.filename).resolve())
        try:
            xml = _set_csv_filename_at_path(xml, binding.component_path, abs_path)
        except JmxParseError:
            continue

    if host_entries is None and task.environment_id:
        host_entries = list(task.environment.host_entries or [])
    if host_entries:
        xml = _inject_dns_cache_manager(xml, host_entries, warnings=warnings)

    return xml
