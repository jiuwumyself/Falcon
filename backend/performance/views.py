import hashlib
import re
import secrets
import shutil
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404, HttpResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from django.utils import timezone

from .models import (
    ACTIVE_RUN_STATUSES, Environment, LoadGenerator, LoadGeneratorStatus,
    RunStatus, Service, Task, TaskCsvBinding, TaskRun,
)
from .serializers import (
    EnvironmentSerializer, LoadGeneratorSerializer,
    RunEventAnchorSerializer, RunPinpointTraceSerializer, ServiceSerializer,
    TaskRunSerializer, TaskSerializer,
)
from .services import executor as executor_svc
from .services import influxdb as influxdb_svc
from .services.jmeter import (
    DiskFullError, delete_csv, delete_script, ensure_jmeter_installed,
    ensure_plugins_installed, get_run_dir, get_runs_dir, get_scripts_dir,
    rename_script, unique_script_filename, write_csv, write_jar, write_script,
)
from .services.jmx import (
    JmxParseError, build_run_xml, get_component_detail, list_components,
    list_thread_groups, parse_jmx, patch_jmx, rename_component, replace_thread_group,
    toggle_component, update_component_detail,
)
from .services.jmeter_runner import JMeterRunError
from .services.validator import validate_task


_SAFE_PATH_RE = re.compile(r'[^A-Za-z0-9]+')

_HIDDEN_COMPONENT_TAGS = frozenset({'BackendListener'})


def _cache_is_fresh(cache_path, *source_paths) -> bool:
    """聚合 / 接口统计端点的本地缓存是否可信。

    有效 = 缓存文件存在 且 mtime ≥ 所有存在数据源(results.jtl / statistics.json)
    里最新的 mtime。数据源全不存在 → False(不可信，重算)。

    解决"缓存毒化":分布式 run 的 results.jtl 执行期周期 merge 一直在变，运行中第一次
    轮询会算出空/半量结果写死缓存，之后(含终态)永远返回旧值。按 mtime 比对后:
    运行中 JTL 持续变新 → 缓存恒过期 → 每次重算(实时);终态 JTL 冻结 → 缓存命中(快);
    已存在的毒化缓存(比终态 JTL 旧)→ 自动失效重算，无需手动删文件。
    """
    if not cache_path.exists():
        return False
    src_mtimes = [p.stat().st_mtime for p in source_paths if p.exists()]
    if not src_mtimes:
        return False
    return cache_path.stat().st_mtime >= max(src_mtimes)


def _path_to_testname(run) -> dict[str, str]:
    """读当前 jmx 拿 path → testname 映射。snapshot 没存 testname，testname 只能从
    当前 jmx 推。jmx 改过 (Step 1 重新上传 / 顺序重排) 时可能跟 snapshot 当时不一致——
    平台限制，但通常 task 改 TG 类型不改 testname，比 path/kind 错配稳定一些。"""
    from .services.jmx import list_thread_groups  # noqa: PLC0415
    try:
        tg_info = list_thread_groups(run.task.read_jmx_bytes())
    except Exception:  # noqa: BLE001
        return {}
    return {tg.get('path') or '': tg.get('testname') or '' for tg in tg_info}


def _compute_tg_planned_users(run) -> dict:
    """按 ThreadGroup testname 算"计划线程数"。

    **重要**：kind + params 必须**配对来自 snapshot**——snapshot 已经存了 (path, kind, params)
    三元组。之前用"jmx 当前 kind + snapshot params"会错配：用户改 TG 类型后（如教师端
    ConcurrencyThreadGroup → SteppingThreadGroup），jmx 拿 SteppingThreadGroup，snapshot
    params 还是 target_concurrency=2，错配后 _planned 走 fallback 默认值算出 100 之类。

    testname 仍从当前 jmx 按 path 推（snapshot 没存 testname）；TG 改名时会错位，但
    比 kind/params 错配影响小。

    per-kind 计算逻辑走 scheduler._planned_vusers_for_tg（同源 single source of
    truth；executor.compute_shards 也用它算分片总数，避免两份分发漂移）。
    """
    from .services.scheduler import _planned_vusers_for_tg  # noqa: PLC0415
    path_to_testname = _path_to_testname(run)
    snap_cfgs = run.thread_groups_config_snapshot or run.task.thread_groups_config or []

    out: dict[str, int] = {}
    for entry in snap_cfgs:
        if not isinstance(entry, dict):
            continue
        path = entry.get('path') or ''
        kind = entry.get('kind') or 'ThreadGroup'
        params = entry.get('params') or {}
        # testname 优先 jmx 推；jmx 找不到（path 重排/jmx 删了 TG）→ 用 path 作兜底 key
        testname = path_to_testname.get(path) or path
        if not testname:
            continue
        out[testname] = _planned_vusers_for_tg(kind, params)
    return out


def _compute_tg_planned_meta(run) -> dict:
    """按 ThreadGroup testname 返回 (kind, params, scenario)，前端 plannedCurve +
    末位卡场景分发用。

    跟 _compute_tg_planned_users 同源数据；字段都来自 snapshot 配对（详见
    _compute_tg_planned_users 注释）。

    scenario 给前端 ScenarioContextChart 用：selectedTg → 直接 lookup 该 TG 的
    scenario，决定末位卡渲染哪个组件；老数据无 scenario 时返回 None，前端走
    inferScenarioFromKind 兜底。
    """
    path_to_testname = _path_to_testname(run)
    snap_cfgs = run.thread_groups_config_snapshot or run.task.thread_groups_config or []

    out: dict[str, dict] = {}
    for entry in snap_cfgs:
        if not isinstance(entry, dict):
            continue
        path = entry.get('path') or ''
        kind = entry.get('kind') or 'ThreadGroup'
        params = entry.get('params') or {}
        scenario = entry.get('scenario')  # 老数据无该字段 → None
        testname = path_to_testname.get(path) or path
        if not testname:
            continue
        out[testname] = {'kind': kind, 'params': params, 'scenario': scenario}
    return out


def _filter_tree_dicts(nodes: list, hidden_tags: frozenset) -> list:
    """从组件树 dict 列表里递归过滤掉指定 tag 的节点（前端不展示 BackendListener 等）。"""
    result = []
    for d in nodes:
        if d.get('tag') in hidden_tags:
            continue
        d = dict(d)  # 浅拷贝避免修改原对象
        d['children'] = _filter_tree_dicts(d.get('children', []), hidden_tags)
        result.append(d)
    return result


def _safe_path_token(path: str) -> str:
    """Component path → 文件名安全片段，例如 '0.0.3' → '0_0_3'。"""
    return _SAFE_PATH_RE.sub('_', path).strip('_') or 'root'


def _purge_run_artifacts(run, *, soft_delete: bool) -> None:
    """清掉单个 TaskRun 的所有物理痕迹：run_dir / archive.tar.gz / InfluxDB 时序数据。

    给 RunViewSet.destroy 和 TaskViewSet.destroy（级联清 task 全部 run）共用。
    soft_delete=True 时同时标 is_deleted（API 走这条）；False 则不动 run 行，仅清磁盘 /
    InfluxDB（task 硬删时 cascade 会带走 run 行本身）。
    """
    if soft_delete and not run.is_deleted:
        run.is_deleted = True
        run.deleted_at = timezone.now()
        run.save(update_fields=['is_deleted', 'deleted_at'])
    rd = get_runs_dir() / run.run_id
    if rd.exists():
        shutil.rmtree(rd, ignore_errors=True)
    archive = get_runs_dir() / f'{run.run_id}.tar.gz'
    archive.unlink(missing_ok=True)
    try:
        influxdb_svc.delete_run_data(run.run_id)
    except Exception:  # noqa: BLE001
        # InfluxDB DELETE 失败不阻断：retention policy 自然 GC
        pass


def _unique_csv_for_binding(jmx_filename: str, component_path: str) -> str:
    """`<jmx_stem>__<safe_path>.csv`，冲突追加 `_2`、`_3`。"""
    stem = Path(jmx_filename).stem if jmx_filename else 'task'
    base = f'{stem}__{_safe_path_token(component_path)}'
    scripts = get_scripts_dir()
    candidate = scripts / f'{base}.csv'
    if not candidate.exists():
        return candidate.name
    n = 2
    while True:
        candidate = scripts / f'{base}_{n}.csv'
        if not candidate.exists():
            return candidate.name
        n += 1


class EnvironmentViewSet(viewsets.ReadOnlyModelViewSet):
    """只读列表/详情。创建和编辑走 Django admin。"""
    queryset = Environment.objects.all()
    serializer_class = EnvironmentSerializer
    pagination_class = None  # 环境不会太多，直接全返


class ServiceViewSet(viewsets.ReadOnlyModelViewSet):
    """G2：被压测服务列表（v1.3 Grafana 接入 v0）。前端 Step 2 multi-select +
    Step 3 ServicePanelsTab / TraceTab / JVM tab 用 grafana_panels 嵌入。
    创建编辑走 admin。"""
    queryset = Service.objects.all()
    serializer_class = ServiceSerializer
    pagination_class = None  # 服务不会太多


class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all()  # TaskManager already excludes soft-deleted
    serializer_class = TaskSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    # —— 删除：先清所有关联 run 的物理痕迹 + InfluxDB 时序数据，再 task.delete() 软删
    # 用户期望"任何数据都进行删除"，故级联清干净；Task / TaskRun 表行保留（软删
    # 标记），需要彻底删 DB 行走 admin 的 hard_delete
    def destroy(self, request, *args, **kwargs):
        task = self.get_object()
        active_runs = task.runs.filter(
            status__in=[s.value for s in ACTIVE_RUN_STATUSES],
        )
        if active_runs.exists():
            return Response(
                {'detail': '任务有正在执行的 run，请先取消'},
                status=status.HTTP_409_CONFLICT,
            )
        for run in task.runs.all():
            _purge_run_artifacts(run, soft_delete=True)
        task.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # —— 创建：上传 JMX，物理文件落 <JMETER_HOME>/scripts/<title>.jmx —— #
    def create(self, request, *args, **kwargs):
        jmx_upload = request.FILES.get('jmx_file')
        if not jmx_upload:
            return Response(
                {'jmx_file': ['必须上传 .jmx 文件']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not jmx_upload.name.lower().endswith('.jmx'):
            return Response(
                {'jmx_file': ['仅支持 .jmx 文件']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        max_size = getattr(settings, 'MAX_UPLOAD_SIZE', 10 * 1024 * 1024)
        if jmx_upload.size and jmx_upload.size > max_size:
            mb = max_size // (1024 * 1024)
            return Response(
                {'jmx_file': [f'文件超过 {mb}MB 上限']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        xml_bytes = jmx_upload.read()
        try:
            fields = parse_jmx(xml_bytes)
        except JmxParseError as e:
            return Response({'jmx_file': [str(e)]}, status=status.HTTP_400_BAD_REQUEST)

        try:
            ensure_jmeter_installed()
        except Exception as e:  # noqa: BLE001
            return Response(
                {'jmeter': [f'JMeter 工具未就绪: {e}']},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        # Title = 用户输入；不再加日期前缀
        raw_title = (request.data.get('title') or jmx_upload.name.rsplit('.', 1)[0]).strip()
        if not raw_title:
            raw_title = 'task'
        filename = unique_script_filename(raw_title)

        try:
            write_script(filename, xml_bytes)
        except DiskFullError as e:
            return Response(
                {'jmx_file': [str(e)]},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        data = request.data.copy()
        data['title'] = raw_title
        data['virtual_users'] = fields.virtual_users
        data['ramp_up_seconds'] = fields.ramp_up_seconds
        data['duration_seconds'] = fields.duration_seconds or data.get('duration_seconds', 60)

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        try:
            instance = serializer.save(
                jmx_filename=filename,
                jmx_hash=hashlib.sha256(xml_bytes).hexdigest(),
            )
        except Exception:
            # DB save failed — remove orphaned script
            delete_script(filename)
            raise
        return Response(self.get_serializer(instance).data, status=status.HTTP_201_CREATED)

    # —— 编辑：title 变了就重命名文件；vuser/ramp/duration 变了就 patch JMX —— #
    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        old_filename = instance.jmx_filename

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()

        # 1) Title changed → rename file
        if 'title' in request.data:
            new_filename = unique_script_filename(
                updated.title, exclude=instance.jmx_path() if old_filename else None,
            )
            if new_filename != old_filename:
                rename_script(old_filename, new_filename)
                updated.jmx_filename = new_filename
                updated.save(update_fields=['jmx_filename', 'updated_at'])

        # 2) vuser/ramp/duration changed → patch_jmx + rewrite file
        patch_kwargs = {}
        for f in ('virtual_users', 'ramp_up_seconds', 'duration_seconds'):
            if f in request.data:
                patch_kwargs[f] = getattr(updated, f)

        if patch_kwargs:
            try:
                original_bytes = updated.read_jmx_bytes()
                patched = patch_jmx(original_bytes, **patch_kwargs)
            except JmxParseError as e:
                return Response({'jmx_file': [str(e)]}, status=status.HTTP_400_BAD_REQUEST)

            updated.write_jmx_bytes(patched)
            updated.jmx_hash = hashlib.sha256(patched).hexdigest()
            updated.save(update_fields=['jmx_hash', 'updated_at'])

        return Response(self.get_serializer(updated).data)

    # —— 重新上传：覆盖同一任务的 JMX 文件，清空 Step 2 配置 —— #
    @action(detail=True, methods=['post'], url_path='replace-jmx',
            parser_classes=[MultiPartParser, FormParser])
    def replace_jmx(self, request, pk=None):
        instance = self.get_object()
        jmx_upload = request.FILES.get('jmx_file')
        if not jmx_upload:
            return Response(
                {'jmx_file': ['必须上传 .jmx 文件']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not jmx_upload.name.lower().endswith('.jmx'):
            return Response(
                {'jmx_file': ['仅支持 .jmx 文件']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        max_size = getattr(settings, 'MAX_UPLOAD_SIZE', 10 * 1024 * 1024)
        if jmx_upload.size and jmx_upload.size > max_size:
            mb = max_size // (1024 * 1024)
            return Response(
                {'jmx_file': [f'文件超过 {mb}MB 上限']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        xml_bytes = jmx_upload.read()
        try:
            fields = parse_jmx(xml_bytes)
        except JmxParseError as e:
            return Response({'jmx_file': [str(e)]}, status=status.HTTP_400_BAD_REQUEST)

        # 清掉旧 CSV 物理文件 + 解绑（脚本结构变了，老 path 多半失效）
        for binding in instance.csv_bindings.all():
            if binding.filename:
                delete_csv(binding.filename)
        instance.csv_bindings.all().delete()

        # 覆盖写入同一文件（title / jmx_filename 不变）
        instance.write_jmx_bytes(xml_bytes)
        instance.jmx_hash = hashlib.sha256(xml_bytes).hexdigest()
        instance.virtual_users = fields.virtual_users
        instance.ramp_up_seconds = fields.ramp_up_seconds
        instance.duration_seconds = fields.duration_seconds or instance.duration_seconds
        # 清空 Step 2 配置 + 解绑环境（用户需要重新配置）
        instance.thread_groups_config = []
        instance.environment = None
        instance.save(update_fields=[
            'jmx_hash', 'virtual_users', 'ramp_up_seconds', 'duration_seconds',
            'thread_groups_config', 'environment', 'updated_at',
        ])
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['get'], url_path='raw-xml')
    def raw_xml(self, request, pk=None):
        instance = self.get_object()
        try:
            xml_text = instance.read_jmx_bytes().decode('utf-8')
        except (FileNotFoundError, OSError) as e:
            raise Http404(f'JMX 文件不存在: {e}')
        return Response({'xml': xml_text})

    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        instance = self.get_object()
        path = instance.jmx_path()
        if not path.exists():
            raise Http404(f'JMX 文件不存在: {path}')
        response = FileResponse(path.open('rb'), as_attachment=True, filename=instance.jmx_filename)
        response['Content-Type'] = 'application/xml'
        return response

    @action(detail=True, methods=['get'], url_path='preview-run-xml')
    def preview_run_xml(self, request, pk=None):
        """返回内存生成的可执行 JMX，用于调试 / 用户预览。不写盘。"""
        instance = self.get_object()
        try:
            xml = build_run_xml(instance)
        except (FileNotFoundError, OSError) as e:
            raise Http404(f'JMX 文件不存在: {e}')
        except JmxParseError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'xml': xml.decode('utf-8')})

    # —— 组件树：Step 1 任务配置用 —— #
    @action(detail=True, methods=['get'], url_path='components')
    def components(self, request, pk=None):
        instance = self.get_object()
        try:
            xml_bytes = instance.read_jmx_bytes()
        except (FileNotFoundError, OSError) as e:
            raise Http404(f'JMX 文件不存在: {e}')
        tree_dicts = [c.to_dict() for c in list_components(xml_bytes)]
        return Response(_filter_tree_dicts(tree_dicts, _HIDDEN_COMPONENT_TAGS))

    @action(detail=True, methods=['get', 'patch'], url_path='components/detail')
    def component_detail(self, request, pk=None):
        instance = self.get_object()
        try:
            xml_bytes = instance.read_jmx_bytes()
        except (FileNotFoundError, OSError) as e:
            raise Http404(f'JMX 文件不存在: {e}')

        if request.method.lower() == 'get':
            path = request.query_params.get('path')
            if not path:
                return Response(
                    {'path': ['query param path 必填']},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                return Response(get_component_detail(xml_bytes, path))
            except JmxParseError as e:
                return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # PATCH
        path = request.data.get('path')
        kind = request.data.get('kind')
        fields = request.data.get('fields')
        if not isinstance(path, str) or not path:
            return Response({'path': ['必填']}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(kind, str) or not kind:
            return Response({'kind': ['必填']}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(fields, dict):
            return Response({'fields': ['必填，对象']}, status=status.HTTP_400_BAD_REQUEST)

        try:
            new_xml = update_component_detail(xml_bytes, path, kind, fields)
        except JmxParseError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        instance.write_jmx_bytes(new_xml)
        instance.jmx_hash = hashlib.sha256(new_xml).hexdigest()
        instance.save(update_fields=['jmx_hash', 'updated_at'])
        tree_dicts = [c.to_dict() for c in list_components(new_xml)]
        return Response(_filter_tree_dicts(tree_dicts, _HIDDEN_COMPONENT_TAGS))

    @action(detail=True, methods=['post'], url_path='components/rename')
    def rename_component(self, request, pk=None):
        instance = self.get_object()
        path = request.data.get('path')
        testname = request.data.get('testname')
        if not isinstance(path, str) or not path:
            return Response(
                {'path': ['必填，索引路径字符串，如 "0.0.1"']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not isinstance(testname, str):
            return Response(
                {'testname': ['必填，字符串（可空）']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            xml_bytes = instance.read_jmx_bytes()
            new_xml = rename_component(xml_bytes, path, testname)
        except JmxParseError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except (FileNotFoundError, OSError) as e:
            raise Http404(f'JMX 文件不存在: {e}')

        instance.write_jmx_bytes(new_xml)
        instance.jmx_hash = hashlib.sha256(new_xml).hexdigest()
        instance.save(update_fields=['jmx_hash', 'updated_at'])
        tree_dicts = [c.to_dict() for c in list_components(new_xml)]
        return Response(_filter_tree_dicts(tree_dicts, _HIDDEN_COMPONENT_TAGS))

    # —— 单个 CSVDataSet 绑定：上传 / 替换 —— #
    @action(detail=True, methods=['post'], url_path='components/upload-csv',
            parser_classes=[MultiPartParser, FormParser])
    def upload_component_csv(self, request, pk=None):
        instance = self.get_object()
        component_path = request.data.get('path')
        csv_upload = request.FILES.get('csv_file')

        if not isinstance(component_path, str) or not component_path:
            return Response(
                {'path': ['必填，CSVDataSet 组件路径']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not csv_upload:
            return Response(
                {'csv_file': ['必须上传 CSV 文件']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        max_size = getattr(settings, 'MAX_UPLOAD_SIZE', 10 * 1024 * 1024)
        if csv_upload.size and csv_upload.size > max_size:
            mb = max_size // (1024 * 1024)
            return Response(
                {'csv_file': [f'文件超过 {mb}MB 上限']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 校验：path 必须指向当前 JMX 里的 CSVDataSet
        try:
            xml_bytes = instance.read_jmx_bytes()
        except (FileNotFoundError, OSError) as e:
            raise Http404(f'JMX 文件不存在: {e}')

        # 通过组件树扁平化校验 path 存在且 tag == 'CSVDataSet'
        flat: list[tuple[str, str]] = []

        def _flatten(nodes):
            for n in nodes:
                flat.append((n.path, n.tag))
                _flatten(n.children)
        _flatten(list_components(xml_bytes))
        match = next(((p, t) for p, t in flat if p == component_path), None)
        if not match:
            return Response(
                {'path': [f'组件路径 {component_path} 在脚本中不存在']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if match[1] != 'CSVDataSet':
            return Response(
                {'path': [f'组件 {component_path} 不是 CSVDataSet（实际 {match[1]}）']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        binding = TaskCsvBinding.objects.filter(
            task=instance, component_path=component_path,
        ).first()
        # 旧文件先删，新文件名重新生成（避免文件名滚雪球）
        if binding and binding.filename:
            delete_csv(binding.filename)

        new_filename = _unique_csv_for_binding(instance.jmx_filename, component_path)
        try:
            write_csv(new_filename, csv_upload.read())
        except DiskFullError as e:
            return Response(
                {'csv_file': [str(e)]},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if binding:
            binding.filename = new_filename
            binding.save(update_fields=['filename', 'updated_at'])
        else:
            TaskCsvBinding.objects.create(
                task=instance, component_path=component_path, filename=new_filename,
            )

        instance.refresh_from_db()
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'], url_path='components/delete-csv')
    def delete_component_csv(self, request, pk=None):
        instance = self.get_object()
        component_path = request.data.get('path')
        if not isinstance(component_path, str) or not component_path:
            return Response(
                {'path': ['必填']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        binding = TaskCsvBinding.objects.filter(
            task=instance, component_path=component_path,
        ).first()
        if binding:
            if binding.filename:
                delete_csv(binding.filename)
            binding.delete()
        instance.refresh_from_db()
        return Response(self.get_serializer(instance).data)

    # —— BeanShell 预处理器 JAR 上传 —— #
    @action(detail=True, methods=['post'], url_path='components/upload-jar',
            parser_classes=[MultiPartParser, FormParser])
    def upload_jar(self, request, pk=None):
        """把 JAR 文件写入 JMeter lib/ext/（全局共享，所有任务公用）。"""
        self.get_object()  # 只做 404 检查，JAR 不绑定到特定任务
        jar_upload = request.FILES.get('jar_file')
        if not jar_upload:
            return Response(
                {'jar_file': ['必须上传 .jar 文件']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not jar_upload.name.lower().endswith('.jar'):
            return Response(
                {'jar_file': ['仅支持 .jar 文件']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if jar_upload.size and jar_upload.size > 50 * 1024 * 1024:
            return Response(
                {'jar_file': ['JAR 文件超过 50 MB 上限']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            dest = write_jar(jar_upload.name, jar_upload.read())
        except (ValueError, RuntimeError) as e:
            return Response({'jar_file': [str(e)]}, status=status.HTTP_400_BAD_REQUEST)
        except DiskFullError as e:
            return Response({'jar_file': [str(e)]}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({
            'filename': dest.name,
            'message': (
                f'JAR 已安装到 JMeter lib/ext/，'
                f'远程执行时需在所有压力机手动安装相同 JAR（{dest.name}）'
            ),
        })

    # —— Step 2：任务配置（线程组场景 / 参数 / 环境） —— #
    @action(detail=True, methods=['get', 'patch'], url_path='thread-groups')
    def thread_groups(self, request, pk=None):
        """
        GET: 读原件 JMX，返回当前所有 ThreadGroup + DB 里已存的 thread_groups_config
        PATCH: 把配置写到 DB（不再派生 _run.jmx 物理文件，跑压测时 build_run_xml 内存生成）
        """
        instance = self.get_object()

        if request.method.lower() == 'get':
            try:
                xml_bytes = instance.read_jmx_bytes()
            except (FileNotFoundError, OSError) as e:
                raise Http404(f'JMX 文件不存在: {e}')
            return Response({
                'thread_groups': list_thread_groups(xml_bytes),
                'saved_config': instance.thread_groups_config or [],
                'environment': instance.environment_id,
            })

        # PATCH
        tg_configs = request.data.get('thread_groups')
        env_id = request.data.get('environment_id')  # 允许 null 清除

        if not isinstance(tg_configs, list):
            return Response(
                {'thread_groups': ['必填，数组 [{path, kind, params}, ...]']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 校验环境存在
        env_obj: Environment | None = None
        if env_id is not None:
            try:
                env_obj = Environment.objects.get(pk=env_id)
            except Environment.DoesNotExist:
                return Response(
                    {'environment_id': [f'环境 id={env_id} 不存在']},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # 需要 Stepping / Concurrency / Ultimate / Arrivals 都依赖插件
        needs_plugins = any(
            c.get('kind') in (
                'SteppingThreadGroup', 'ConcurrencyThreadGroup',
                'UltimateThreadGroup', 'ArrivalsThreadGroup',
            )
            for c in tg_configs
        )
        if needs_plugins:
            try:
                ensure_plugins_installed()
            except Exception as e:  # noqa: BLE001
                return Response(
                    {'jmeter': [f'插件安装失败: {e}']},
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

        # 用原件 + 配置在内存里 dry-run 一次替换，校验所有 path / kind / params 合法
        try:
            xml_bytes = instance.read_jmx_bytes()
        except (FileNotFoundError, OSError) as e:
            raise Http404(f'JMX 文件不存在: {e}')

        try:
            for cfg in tg_configs:
                path = cfg.get('path')
                kind = cfg.get('kind')
                params = cfg.get('params') or {}
                if not isinstance(path, str) or not path:
                    raise JmxParseError('thread_groups 每项必须有 path')
                if not isinstance(kind, str):
                    raise JmxParseError('thread_groups 每项必须有 kind')
                if not isinstance(params, dict):
                    raise JmxParseError('params 必须是对象')
                xml_bytes = replace_thread_group(xml_bytes, path, kind, params)
        except JmxParseError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        # 配置入库（不写盘）+ 同步 virtual_users/ramp_up/duration（用第一个标准 TG 的参数）
        instance.thread_groups_config = tg_configs
        instance.environment = env_obj
        first_std = next(
            (c for c in tg_configs if c.get('kind') == 'ThreadGroup'),
            None,
        )
        if first_std and isinstance(first_std.get('params'), dict):
            p = first_std['params']
            instance.virtual_users = int(p.get('users', instance.virtual_users) or 0)
            instance.ramp_up_seconds = int(p.get('ramp_up', instance.ramp_up_seconds) or 0)
            instance.duration_seconds = int(p.get('duration', instance.duration_seconds) or 0)
        instance.save(update_fields=[
            'thread_groups_config', 'environment',
            'virtual_users', 'ramp_up_seconds', 'duration_seconds', 'updated_at',
        ])

        return Response(self.get_serializer(instance).data)

    # —— Step 2：试跑（每接口跑 1 次，走真 JMeter CLI） —— #
    @action(detail=True, methods=['post'], url_path='validate')
    def validate(self, request, pk=None):
        instance = self.get_object()
        env_id = request.data.get('environment_id')

        # Load environment hosts (request body wins over Task.environment)
        host_entries: list[dict[str, str]] = []
        env_obj: Environment | None = None
        if env_id is not None:
            try:
                env_obj = Environment.objects.get(pk=env_id)
            except Environment.DoesNotExist:
                return Response(
                    {'environment_id': [f'环境 id={env_id} 不存在']},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif instance.environment_id:
            env_obj = instance.environment
        if env_obj:
            host_entries = list(env_obj.host_entries or [])

        # JMeter CLI 跑 1 线程 × 1 循环：validator 内部
        # build_validate_xml(task) → 写盘到 runs/_validate_<id>/run.jmx →
        # subprocess jmeter -n → 解析 JTL → 返回 (warnings, results, executed_tgs)
        try:
            warnings, results, executed_tgs = validate_task(
                instance, host_entries=host_entries,
            )
        except (FileNotFoundError, OSError) as e:
            raise Http404(f'JMX 文件不存在: {e}')
        except JmxParseError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except JMeterRunError as e:
            return Response(
                {'detail': f'JMeter 执行失败：{e}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        return Response({
            'warnings': warnings,
            'results': [r.to_dict() for r in results],
            'executed_tgs': executed_tgs,
        })

    @action(detail=True, methods=['post'], url_path='components/toggle')
    def toggle_component(self, request, pk=None):
        instance = self.get_object()
        path = request.data.get('path')
        enabled = request.data.get('enabled')
        if not isinstance(path, str) or not path:
            return Response(
                {'path': ['必填，索引路径字符串，如 "0.0.1"']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not isinstance(enabled, bool):
            return Response(
                {'enabled': ['必填，布尔值']},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            xml_bytes = instance.read_jmx_bytes()
            new_xml = toggle_component(xml_bytes, path, enabled)
        except JmxParseError as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except (FileNotFoundError, OSError) as e:
            raise Http404(f'JMX 文件不存在: {e}')

        instance.write_jmx_bytes(new_xml)
        instance.jmx_hash = hashlib.sha256(new_xml).hexdigest()
        instance.save(update_fields=['jmx_hash', 'updated_at'])
        tree_dicts = [c.to_dict() for c in list_components(new_xml)]
        return Response(_filter_tree_dicts(tree_dicts, _HIDDEN_COMPONENT_TAGS))

    # ── Step 3：执行任务 ────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='run')
    def run(self, request, pk=None):
        """创建 TaskRun 并触发 RunExecutor。同 task 已有非终态 run 时返 409。"""
        instance = self.get_object()
        if not instance.thread_groups_config:
            return Response(
                {'detail': '请先完成 Step 2 任务配置再执行'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # 检测 Step 1 改过 TG enabled / kind 但没回 Step 2 重新保存的情况
        # serializer 同源调用，前端 banner / disable 按钮也吃这个值；后端起 run
        # 双保险，避免前端漏拦时跑了过期配置
        from .services.jmx import detect_thread_groups_config_stale  # noqa: PLC0415
        if detect_thread_groups_config_stale(instance):
            return Response(
                {'detail': '线程组配置已过期：你在 Step 1 改过 TG 启用状态或类型，'
                           '请回 Step 2 重新保存后再开始'},
                status=status.HTTP_409_CONFLICT,
            )

        # v1.2 多机调度：前端可选传 load_generator_ids 指定哪些 agent 来跑
        # 不传 / 空 → executor 走 LOCAL_FALLBACK 本机执行（开发态友好）
        lg_ids: list[int] = request.data.get('load_generator_ids') or []
        if lg_ids and not isinstance(lg_ids, list):
            return Response(
                {'detail': 'load_generator_ids must be a list of int'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        selected_lgs = []
        if lg_ids:
            from datetime import timedelta as _td
            from django.utils import timezone as _tz
            cutoff = _tz.now() - _td(minutes=3)
            selected_lgs = list(LoadGenerator.objects.filter(
                id__in=lg_ids,
                status=LoadGeneratorStatus.IDLE,
                last_heartbeat_at__gte=cutoff,
            ))
            if len(selected_lgs) != len(lg_ids):
                return Response(
                    {'detail': '部分压力源不存在 / 非 idle / 心跳超时（≥3min），请刷新列表'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        run_id = secrets.token_hex(8)
        try:
            with transaction.atomic():
                task_run = TaskRun.objects.create(
                    task=instance,
                    run_id=run_id,
                    status=RunStatus.PRE_CHECKING,
                    virtual_users=instance.virtual_users,
                    ramp_up_seconds=instance.ramp_up_seconds,
                    duration_seconds=instance.duration_seconds,
                    # 快照当前 Step 2 配置 + jmx 指纹；切历史 run 时给前端展示"当时是
                    # 这么跑的"，且跟当前 task 对比能提示"已变化"
                    thread_groups_config_snapshot=instance.thread_groups_config or [],
                    jmx_hash_snapshot=instance.jmx_hash or '',
                )
                if selected_lgs:
                    task_run.load_generators.set(selected_lgs)
        except IntegrityError:
            active = instance.runs.filter(
                status__in=[s.value for s in ACTIVE_RUN_STATUSES],
            ).first()
            return Response(
                {
                    'detail': '该任务已有运行中的 run，请先取消',
                    'active_run_id': active.run_id if active else None,
                },
                status=status.HTTP_409_CONFLICT,
            )

        # 子线程编排
        executor_svc.RunExecutor(task_run).start()
        return Response(
            TaskRunSerializer(task_run).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get'], url_path='runs')
    def runs(self, request, pk=None):
        """该 task 的全部 run（分页，最新优先）。"""
        instance = self.get_object()
        qs = instance.runs.order_by('-id')
        page = self.paginate_queryset(qs)
        if page is not None:
            return self.get_paginated_response(TaskRunSerializer(page, many=True).data)
        return Response(TaskRunSerializer(qs, many=True).data)


# ── Step 3：RunViewSet（按 run_id 操作单个 run） ──────────────────────────


class RunViewSet(viewsets.GenericViewSet):
    """按 run_id 操作 TaskRun。run_id 是面向用户的短 uuid，不暴露 DB pk。"""
    queryset = TaskRun.objects.all()
    serializer_class = TaskRunSerializer
    lookup_field = 'run_id'
    lookup_value_regex = r'[0-9a-fA-F]+'
    pagination_class = None  # cancel/metrics/log 都是 detail action

    def retrieve(self, request, run_id=None):
        run = self.get_object()
        return Response(TaskRunSerializer(run).data)

    def destroy(self, request, run_id=None):
        """软删 TaskRun + 物理删 run_dir + 删 InfluxDB 数据。

        - 软删：is_deleted=True / deleted_at=now；表行保留供大盘统计
        - 物理清 run_dir + archive.tar.gz
        - InfluxDB DELETE FROM jmeter WHERE run_id=...
        - 活跃 run（pre_checking/pending/running/cancelling）→ 409 拒绝
        - GenericViewSet 没自带 destroy，DRF Router 仍会按 method=DELETE 路由到这里
        """
        run = self.get_object()
        if run.is_active:
            return Response(
                {'detail': '该 run 仍在执行，先取消'},
                status=status.HTTP_409_CONFLICT,
            )
        _purge_run_artifacts(run, soft_delete=True)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel(self, request, run_id=None):
        run = self.get_object()
        if run.is_terminal:
            return Response(TaskRunSerializer(run).data)  # 幂等
        executor = executor_svc.get_executor(run.run_id)
        if executor is None:
            # 进程内没找到 executor（web 进程重启后 zombie）→ 直接标 failed
            TaskRun.objects.filter(pk=run.pk).update(
                status=RunStatus.FAILED,
                error_message='Web 进程重启或子线程已丢失，无法 graceful 取消；自动标记为 failed',
            )
            run.refresh_from_db()
            return Response(TaskRunSerializer(run).data)
        executor.cancel()
        run.refresh_from_db()
        return Response(TaskRunSerializer(run).data)

    @action(detail=True, methods=['get'], url_path='metrics')
    def metrics(self, request, run_id=None):
        run = self.get_object()
        since_str = request.query_params.get('since')
        since = None
        if since_str:
            from datetime import datetime
            try:
                since = datetime.fromisoformat(since_str.replace('Z', '+00:00'))
            except ValueError:
                return Response(
                    {'since': ['ISO8601 格式']},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        data = influxdb_svc.query_run_realtime(run.run_id, since=since)
        # tg_planned_users: 按 testname 给前端 lookup per-TG 的"计划线程数"。
        # tg_planned_meta: 同步返 {testname: {kind, params}}，前端按曲线算 ramp-up 波动。
        # JMeter Backend Listener 没法拿 per-TG 实测并发（maxAT 是全局），前端 ConcurrencyChart
        # 单 TG 选中时按 meta 算计划曲线渲染，能看到启动 ramp 形态（不再是直平线）。
        data['tg_planned_users'] = _compute_tg_planned_users(run)
        data['tg_planned_meta'] = _compute_tg_planned_meta(run)
        # 顺手附上 run 状态，前端可以一次拿到全部信息
        data['run'] = TaskRunSerializer(run).data
        return Response(data)

    @action(detail=True, methods=['get'], url_path='latency-breakdown')
    def latency_breakdown(self, request, run_id=None):
        """扫 JTL 算 Connect / 服务端处理 / 客户端接收 三段时序，按秒聚合。

        JTL 列含义：
        - elapsed：整请求耗时
        - Latency：到首字节时间（含 TCP connect + 服务端处理）
        - Connect：TCP 握手时间

        三段拆 = Connect + (Latency - Connect) + (elapsed - Latency)
             = Connect + ServerProcessing + ClientReceive

        前端 LatencyChart "拆解" mode 用 —— 一眼看出 RT 高在哪一段。
        非高频接口，前端按需调用（不进 5s metrics 轮询）。

        Query 参数：
          - exclude_ko=true：剔除失败样本（success=false 跳过），看真实业务延迟分布
        """
        import csv as _csv
        run = self.get_object()
        exclude_ko = request.query_params.get('exclude_ko', '').lower() == 'true'
        jtl = get_runs_dir() / run.run_id / 'results.jtl'
        empty = {'connect_ms': [], 'server_ms': [], 'receive_ms': []}
        if not jtl.exists() or jtl.stat().st_size == 0:
            return Response(empty)

        # 按秒聚合：bucket_ms -> [connect_sum, server_sum, receive_sum, count]
        buckets: dict[int, list[float]] = {}
        try:
            with jtl.open('r', encoding='utf-8', errors='replace') as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    if exclude_ko and (row.get('success') or '').lower() != 'true':
                        continue
                    try:
                        ts = int(row.get('timeStamp') or 0)
                        elapsed = float(row.get('elapsed') or 0)
                        latency = float(row.get('Latency') or 0)
                        connect = float(row.get('Connect') or 0)
                    except ValueError:
                        continue
                    if ts <= 0:
                        continue
                    # 异常兜底：latency 不可能 > elapsed，connect 不可能 > latency
                    if connect > latency:
                        connect = latency
                    if latency > elapsed:
                        latency = elapsed
                    server = max(0.0, latency - connect)
                    receive = max(0.0, elapsed - latency)
                    bucket = (ts // 1000) * 1000
                    b = buckets.get(bucket)
                    if b is None:
                        buckets[bucket] = [connect, server, receive, 1]
                    else:
                        b[0] += connect
                        b[1] += server
                        b[2] += receive
                        b[3] += 1
        except OSError as e:
            return Response({'detail': f'read jtl: {e}'}, status=500)

        connect_pts: list[list[float]] = []
        server_pts: list[list[float]] = []
        receive_pts: list[list[float]] = []
        for ts in sorted(buckets.keys()):
            c, s, r, n = buckets[ts]
            connect_pts.append([ts, round(c / n, 2)])
            server_pts.append([ts, round(s / n, 2)])
            receive_pts.append([ts, round(r / n, 2)])
        return Response({
            'connect_ms': connect_pts,
            'server_ms': server_pts,
            'receive_ms': receive_pts,
        })

    @action(detail=True, methods=['get'], url_path='error-breakdown-timeseries')
    def error_breakdown_timeseries(self, request, run_id=None):
        """扫 JTL 按秒聚合错误类型 5 桶时序（4xx / 5xx / timeout / connect_error /
        assertion / other），让 stress 场景末位图运行中也能看到错误类型转移。

        终态 `TaskRun.error_breakdown` 只有总数；本端点给的是**时序**：每秒一个点，
        每个桶一条时序。前端 ErrorBreakdownStackedChart 堆叠面积图渲染。

        返回 shape：
          {
            "4xx":           [[ts_ms, count], ...],
            "5xx":           [[ts_ms, count], ...],
            "timeout":       [[ts_ms, count], ...],
            "connect_error": [[ts_ms, count], ...],
            "assertion":     [[ts_ms, count], ...],
            "other":         [[ts_ms, count], ...],
          }
        """
        import csv as _csv
        from .services.jmeter_runner import classify_jtl_error, empty_error_breakdown  # noqa: PLC0415
        run = self.get_object()
        jtl = get_runs_dir() / run.run_id / 'results.jtl'
        buckets_template = empty_error_breakdown()
        if not jtl.exists() or jtl.stat().st_size == 0:
            return Response({k: [] for k in buckets_template})

        # 按秒聚合：bucket_sec_ms → {bucket_name: count}
        per_sec: dict[int, dict[str, int]] = {}
        try:
            with jtl.open('r', encoding='utf-8', errors='replace') as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    if (row.get('success') or '').lower() == 'true':
                        continue
                    try:
                        ts = int(row.get('timeStamp') or 0)
                    except ValueError:
                        continue
                    if ts <= 0:
                        continue
                    bucket_name = classify_jtl_error(row)
                    sec_ms = (ts // 1000) * 1000
                    slot = per_sec.get(sec_ms)
                    if slot is None:
                        slot = dict(buckets_template)
                        per_sec[sec_ms] = slot
                    slot[bucket_name] = slot.get(bucket_name, 0) + 1
        except OSError as e:
            return Response({'detail': f'read jtl: {e}'}, status=500)

        out: dict[str, list[list[int]]] = {k: [] for k in buckets_template}
        for ts in sorted(per_sec.keys()):
            slot = per_sec[ts]
            for bname in out:
                out[bname].append([ts, slot.get(bname, 0)])
        return Response(out)

    @action(detail=True, methods=['get'], url_path='log')
    def log(self, request, run_id=None):
        run = self.get_object()
        tail = request.query_params.get('tail', '200')
        try:
            tail_n = max(1, min(int(tail), 5000))
        except ValueError:
            tail_n = 200
        log_path = get_runs_dir() / run.run_id / 'jmeter.log'
        if not log_path.exists():
            return Response({'lines': []})
        try:
            with log_path.open('r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            return Response({'lines': lines[-tail_n:]})
        except OSError as e:
            return Response(
                {'detail': f'读 log 失败: {e}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=['get'], url_path='jtl')
    def jtl(self, request, run_id=None):
        run = self.get_object()
        jtl_path = get_runs_dir() / run.run_id / 'results.jtl'
        if not jtl_path.exists():
            raise Http404(f'JTL 不存在: {jtl_path}')
        response = FileResponse(
            jtl_path.open('rb'),
            as_attachment=True,
            filename=f'{run.run_id}.jtl',
        )
        response['Content-Type'] = 'text/csv; charset=utf-8'
        return response

    @action(detail=True, methods=['get'], url_path=r'report(?:/(?P<sub>.+))?')
    def report(self, request, run_id=None, sub=None):
        """JMeter -e -o 生成的 HTML 报告。GET /report/ → index.html；
        子路径（CSS/JS/sbadmin2 资源）通过 sub 透传。"""
        run = self.get_object()
        report_dir = get_runs_dir() / run.run_id / 'report'
        if not report_dir.is_dir():
            raise Http404('报告尚未生成（仅 success/cancelled/timeout 后可看）')

        rel = sub or 'index.html'
        # 防路径穿越
        target = (report_dir / rel).resolve()
        if not str(target).startswith(str(report_dir.resolve())):
            raise Http404('非法路径')
        if not target.exists() or not target.is_file():
            raise Http404(f'文件不存在: {rel}')

        # 简单 content-type 判定
        ext = target.suffix.lower()
        content_types = {
            '.html': 'text/html; charset=utf-8',
            '.css': 'text/css; charset=utf-8',
            '.js': 'application/javascript; charset=utf-8',
            '.json': 'application/json; charset=utf-8',
            '.png': 'image/png',
            '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.svg': 'image/svg+xml',
        }
        return HttpResponse(
            target.read_bytes(),
            content_type=content_types.get(ext, 'application/octet-stream'),
        )

    # ── v1.2 Step 3 下半部分真端点（取代 mock）──────────────────────────

    @action(detail=True, methods=['get'], url_path='sampler-stats')
    def sampler_stats(self, request, run_id=None):
        """
        每接口聚合统计。优先从 JMeter HTML 报告的 statistics.json 读，没生成时
        流式扫 jtl 自己聚合（精度较粗，但保证有数据）。
        """
        import csv as _csv
        import json as _json
        run = self.get_object()
        run_dir = get_runs_dir() / run.run_id

        # 数据源：优先 statistics.json（JMeter -e -o 出），没有则扫 results.jtl
        stats_json = run_dir / 'report' / 'statistics.json'
        jtl = run_dir / 'results.jtl'

        # --- 缓存优先：仅当缓存比两个数据源都新才信(防毒化，详见 _cache_is_fresh) ---
        cached = run_dir / 'cached_sampler_stats.json'
        if _cache_is_fresh(cached, stats_json, jtl):
            try:
                return Response(_json.loads(cached.read_text(encoding='utf-8')))
            except (OSError, _json.JSONDecodeError):
                pass

        # 优先 statistics.json（JMeter -e -o 自动出）
        if stats_json.exists():
            try:
                data = _json.loads(stats_json.read_text(encoding='utf-8'))
            except (OSError, _json.JSONDecodeError):
                data = {}
            results = []
            for label, s in data.items():
                if label == 'Total':
                    continue
                results.append({
                    'label': label,
                    'total': int(s.get('sampleCount', 0)),
                    'success': int(s.get('sampleCount', 0)) - int(s.get('errorCount', 0)),
                    'error': int(s.get('errorCount', 0)),
                    'avg_ms': float(s.get('meanResTime', 0)),
                    'min_ms': float(s.get('minResTime', 0)),
                    'max_ms': float(s.get('maxResTime', 0)),
                    'p50_ms': float(s.get('medianResTime', 0)),
                    'p90_ms': float(s.get('pct1ResTime', 0)),
                    'p99_ms': float(s.get('pct3ResTime', 0)),
                    'avg_rps': float(s.get('throughput', 0)),
                    'avg_bytes': float(s.get('receivedKBytesPerSec', 0)) * 1024 / max(s.get('throughput', 1), 1),
                    'top_errors': [],  # statistics.json 不分错误类型；要细的看 error-samples
                })
            try:
                cached.write_text(_json.dumps(results, ensure_ascii=False), encoding='utf-8')
            except OSError:
                pass
            return Response(results)

        # fallback：扫 jtl（jtl 变量已在方法开头定义）
        if not jtl.exists() or jtl.stat().st_size == 0:
            # JTL 缺失/空时不落缓存——否则运行早期的空结果会毒化整个 run 的查询
            return Response([])

        agg: dict[str, dict] = {}
        try:
            with jtl.open('r', encoding='utf-8', errors='replace') as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    label = row.get('label') or ''
                    rec = agg.setdefault(label, {
                        'label': label, 'total': 0, 'success': 0, 'error': 0,
                        'elapsed': [], 'first_ts': None, 'last_ts': None,
                        'bytes_sum': 0, 'top_errors': {},
                    })
                    rec['total'] += 1
                    if (row.get('success') or '').lower() == 'true':
                        rec['success'] += 1
                    else:
                        rec['error'] += 1
                        msg = row.get('failureMessage') or row.get('responseMessage') or '(unknown)'
                        rec['top_errors'][msg] = rec['top_errors'].get(msg, 0) + 1
                    try:
                        rec['elapsed'].append(int(row.get('elapsed') or 0))
                        ts = int(row.get('timeStamp') or 0)
                        rec['first_ts'] = ts if rec['first_ts'] is None else min(rec['first_ts'], ts)
                        rec['last_ts'] = ts if rec['last_ts'] is None else max(rec['last_ts'], ts)
                        rec['bytes_sum'] += int(row.get('bytes') or 0)
                    except (TypeError, ValueError):
                        pass
        except OSError as e:
            return Response({'detail': f'read jtl: {e}'}, status=500)

        out = []
        for r in agg.values():
            elapsed = sorted(r['elapsed'])
            n = len(elapsed)
            def pct(p):
                return float(elapsed[max(0, int(n * p) - 1)]) if n else 0.0
            span = max((r['last_ts'] - r['first_ts']) / 1000.0, 0.001) if r['first_ts'] else 1
            top = sorted(r['top_errors'].items(), key=lambda x: -x[1])[:3]
            out.append({
                'label': r['label'],
                'total': r['total'],
                'success': r['success'],
                'error': r['error'],
                'avg_ms': float(sum(elapsed) / n) if n else 0.0,
                'min_ms': float(elapsed[0]) if n else 0.0,
                'max_ms': float(elapsed[-1]) if n else 0.0,
                'p50_ms': pct(0.5),
                'p90_ms': pct(0.9),
                'p99_ms': pct(0.99),
                'avg_rps': r['total'] / span if span > 0 else 0,
                'avg_bytes': r['bytes_sum'] / r['total'] if r['total'] else 0,
                'top_errors': [{'reason': k, 'count': v} for k, v in top],
            })
        try:
            cached.write_text(_json.dumps(out, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass
        return Response(out)

    @action(detail=True, methods=['get'], url_path='error-samples')
    def error_samples(self, request, run_id=None):
        """流式扫 jtl 找 success=false 的行；按 sampler / code_bucket 过滤。

        两种返回模式：
        - 默认（aggregate=false）：返 samples（被 limit 截，最多 500）+ total（真实总数）
        - aggregate=true：按 (code, label, msg_norm) 服端聚合 —— 同一接口同 code 下
          不同 message 算独立组合（HTTP/2 时 message 多为空 → msg_norm='' 自然合并）
          每组带真实 count + 一条代表 url
          → 用于 ErrorByEndpointTable，sum 永远 = 真实总错误数（不被 limit 影响）
        """
        import csv as _csv
        import json as _json
        run = self.get_object()
        jtl = get_runs_dir() / run.run_id / 'results.jtl'
        aggregate = (request.query_params.get('aggregate') or '').lower() in ('1', 'true', 'yes')

        # --- 缓存优先（仅对无额外过滤条件的查询做缓存）---
        run_dir = get_runs_dir() / run.run_id
        use_cache = not any([
            request.query_params.get('sampler'),
            request.query_params.get('code_bucket'),
            request.query_params.get('response_code'),
        ])
        if use_cache:
            cache_name = 'cached_error_samples_agg.json' if aggregate else 'cached_error_samples_detail.json'
            cached = run_dir / cache_name
            # 仅当缓存比 results.jtl 新才信(防毒化，详见 _cache_is_fresh)
            if _cache_is_fresh(cached, jtl):
                try:
                    return Response(_json.loads(cached.read_text(encoding='utf-8')))
                except (OSError, _json.JSONDecodeError):
                    pass

        if not jtl.exists() or jtl.stat().st_size == 0:
            # JTL 缺失/空时不落缓存——否则运行早期写下的空结果会毒化整个 run 的查询
            return Response({'aggregates': [], 'total': 0} if aggregate else {'samples': [], 'total': 0})

        try:
            limit = max(1, min(int(request.query_params.get('limit', 50)), 500))
        except ValueError:
            limit = 50
        sampler = request.query_params.get('sampler') or ''
        code_bucket = (request.query_params.get('code_bucket') or 'all').lower()
        # 精确 code 过滤（下钻聚合行用）：code_bucket 太宽（401/404/422 都归 4xx），
        # 用户在聚合表看到一行精确 code=500 要看具体样本时，应按 500 严格匹配，
        # 不应被 4xx/5xx 桶宽过滤。空值 = 不过滤；保留 code_bucket 给粗粒度场景用。
        response_code = (request.query_params.get('response_code') or '').strip()

        def bucket_of(code: str, msg: str) -> str:
            if code.startswith('Non HTTP'):
                return 'timeout'
            if (msg or '').startswith('Assertion'):
                return 'assertion'
            if code.startswith('5'):
                return '5xx'
            if code.startswith('4'):
                return '4xx'
            return 'other'

        # errors.xml 扫描已移至独立的 response-body 端点（按需加载）。
        # 列表加载不再扫描 errors.xml，彻底消除 lxml iterparse 耗时导致的 502。
        # body_index 置空；聚合表 / 明细表的 response_body 字段返回空字符串，
        # 前端点击某行时调 response-body 端点按需拉取。
        body_index: dict[tuple[str, str], str] = {}

        samples: list[dict] = []
        agg: dict[tuple[str, str], dict] = {}
        total = 0
        try:
            with jtl.open('r', encoding='utf-8', errors='replace') as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    if (row.get('success') or '').lower() == 'true':
                        continue
                    label = row.get('label') or ''
                    if sampler and sampler not in label:
                        continue
                    code = row.get('responseCode') or ''
                    msg = row.get('responseMessage') or ''
                    fmsg = row.get('failureMessage') or ''
                    url = row.get('URL') or ''  # 需要 -Jjmeter.save.saveservice.url=true（新版 executor 默认开）
                    bucket = bucket_of(code, fmsg or msg)
                    if code_bucket != 'all' and bucket != code_bucket:
                        continue
                    if response_code and code != response_code:
                        continue
                    total += 1
                    if aggregate:
                        # 按 (code, label) 二键聚合：同接口同 code 不同 message 文本
                        # 合并为一行（之前三键含 msg_norm，HTTP 500 不同异常栈会分多行
                        # 用户反馈"重复看了"）。代表 message 取首条样本的 fmsg/msg，
                        # 前端按 code 派生 HTTP_REASON 兜底；要看不同 message 走行展开
                        # 看具体样本。
                        key = (code, label)
                        existing = agg.get(key)
                        if existing is None:
                            agg[key] = {
                                'response_code': code,
                                'label': label,
                                'count': 1,
                                'sample_message': msg,
                                'sample_failure_message': fmsg,
                                'sample_url': url,
                                # body 从 errors.xml 拿（双轨注入，仅失败样本带）
                                'sample_response_body': body_index.get((label, code), ''),
                            }
                        else:
                            existing['count'] += 1
                    elif len(samples) < limit:
                        samples.append({
                            'timestamp': int(row.get('timeStamp') or 0),
                            'label': label,
                            'method': '',  # JMeter CSV 默认不写 method（要 -Jjmeter.save.saveservice.method=true）
                            'response_code': code,
                            'response_message': msg,
                            'failure_message': fmsg,
                            'url': url,
                            'elapsed_ms': int(row.get('elapsed') or 0),
                            # body 从 errors.xml 双轨拿；旧 run（未注入 listener）→ 空字符串
                            'response_body': body_index.get((label, code), ''),
                        })
        except OSError as e:
            return Response({'detail': f'read jtl: {e}'}, status=500)

        if aggregate:
            rows = sorted(agg.values(), key=lambda r: r['count'], reverse=True)[:limit]
            resp_data = {'aggregates': rows, 'total': total}
        else:
            resp_data = {'samples': samples, 'total': total}
        if use_cache:
            try:
                cached.write_text(_json.dumps(resp_data, ensure_ascii=False), encoding='utf-8')
            except OSError:
                pass
        return Response(resp_data)

    @action(detail=True, methods=['get'], url_path='response-body')
    def response_body(self, request, run_id=None):
        """按需从 errors.xml 拉取单条错误样本的 response body。

        前端在错误明细表点击某行时调用，传 label + response_code 定位首条匹配样本。
        只扫到第一个匹配 key 就退出，避免全量 iterparse。"""
        label = (request.query_params.get('label') or '').strip()
        code = (request.query_params.get('response_code') or '').strip()
        if not label and not code:
            return Response({'body': ''})

        run = self.get_object()
        run_dir = get_runs_dir() / run.run_id
        if not run_dir.exists():
            return Response({'body': ''})

        from lxml import etree as _etree  # noqa: PLC0415
        for errors_xml in sorted(run_dir.glob('errors*.xml')):
            if errors_xml.stat().st_size == 0:
                continue
            try:
                ctx = _etree.iterparse(
                    str(errors_xml),
                    events=('end',),
                    recover=True,
                )
                for _ev, el in ctx:
                    if el.tag not in ('sample', 'httpSample'):
                        continue
                    if (el.get('s') or '').lower() == 'true':
                        el.clear()
                        parent = el.getparent()
                        if parent is not None:
                            parent.remove(el)
                        continue
                    # 匹配 label + code
                    lab = el.get('lb') or ''
                    rc = el.get('rc') or ''
                    matched = True
                    if label and lab != label:
                        matched = False
                    if code and rc != code:
                        matched = False
                    if matched:
                        body_el = el.find('responseData')
                        txt = (body_el.text or '').strip() if body_el is not None else ''
                        el.clear()
                        return Response({'body': txt[:2000]})
                    el.clear()
                    parent = el.getparent()
                    if parent is not None:
                        parent.remove(el)
            except OSError:
                continue
        return Response({'body': ''})

    @action(detail=True, methods=['get'], url_path='timeline')
    def timeline(self, request, run_id=None):
        """运行时间轴：返回 phases + 各阶段时间戳。RuntimeStatusPanel 子段 1 用。"""
        run = self.get_object()
        phases = []
        if run.started_at:
            phases.append({
                'name': 'pre_check',
                'start': run.created_at.timestamp() * 1000 if hasattr(run, 'created_at') and run.started_at else 0,
                'end': run.started_at.timestamp() * 1000,
                'label': '预检',
            })
            ramp_end = run.started_at.timestamp() * 1000 + (run.ramp_up_seconds or 0) * 1000
            phases.append({
                'name': 'ramp_up',
                'start': run.started_at.timestamp() * 1000,
                'end': ramp_end,
                'label': '加压（ramp）',
            })
            steady_end = ramp_end + (run.duration_seconds or 0) * 1000
            phases.append({
                'name': 'steady',
                'start': ramp_end,
                'end': min(steady_end,
                           run.finished_at.timestamp() * 1000 if run.finished_at else steady_end),
                'label': '稳态',
            })
            if run.finished_at and run.finished_at.timestamp() * 1000 > steady_end:
                phases.append({
                    'name': 'cool_down',
                    'start': steady_end,
                    'end': run.finished_at.timestamp() * 1000,
                    'label': '收尾',
                })
        return Response({
            'run_id': run.run_id,
            'status': run.status,
            'started_at': run.started_at.isoformat() if run.started_at else None,
            'finished_at': run.finished_at.isoformat() if run.finished_at else None,
            'duration_seconds': run.duration_seconds,
            'ramp_up_seconds': run.ramp_up_seconds,
            'phases': phases,
        })

    @action(detail=True, methods=['get'], url_path='events')
    def events(self, request, run_id=None):
        """§ 12 S1：返回该 run 的关键事件锚点列表（按 ts_ms 升序）。

        来源：executor 状态切换时主动写（ramp_done / hold_start / shutdown_start /
        error_rate_breached）+ _on_finish 扫 InfluxDB 补 first_error。前端时间轴
        markLine 用。
        """
        from .models import RunEventAnchor  # noqa: PLC0415
        run = self.get_object()
        events = RunEventAnchor.objects.filter(run=run).order_by('ts_ms')
        return Response(RunEventAnchorSerializer(events, many=True).data)

    @action(detail=True, methods=['get'], url_path='pinpoint-traces')
    def pinpoint_traces(self, request, run_id=None):
        """§ 11 Pinpoint 接入 v0：返回该 run 的慢 trace 元数据列表（按 service
        分组 + elapsed desc 排）。

        数据由 _on_finish 异步触发的 pinpoint_collector 写入；PinpointConfig 禁用
        / 无 Service 配置 / Pinpoint 不可达时返回空列表（前端按 placeholder 渲染）。
        """
        from .models import RunPinpointTrace  # noqa: PLC0415
        run = self.get_object()
        traces = RunPinpointTrace.objects.filter(run=run).order_by('service_name', '-elapsed_ms')
        return Response(RunPinpointTraceSerializer(traces, many=True).data)


# ── v1.2 LoadGenerator：列表 + agent 自注册 / 心跳 ──────────────────────────

def _check_agent_token(request) -> bool:
    """
    Agent ↔ 主控用共享 token（settings.FALCON_AGENT_TOKEN）做 Bearer 鉴权。
    开发期 token 留空 = 不校验（方便本地 curl 联调）；生产期 .env 里设上即可启用。
    """
    expected = getattr(settings, 'FALCON_AGENT_TOKEN', '') or ''
    if not expected:
        return True  # 未配置 → 不强校验
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        return auth.removeprefix('Bearer ').strip() == expected
    return False


class LoadGeneratorViewSet(viewsets.ReadOnlyModelViewSet):
    """容器化压力源（v1.2）。前端只读列出 + 看详情；写入由 agent 走 register/heartbeat
    端点。Phase C 会再加 scale-up / scale-down / system-metrics 代理端点。"""
    queryset = LoadGenerator.objects.all()
    serializer_class = LoadGeneratorSerializer
    pagination_class = None  # 单部署内压力源数量有限，全返

    @action(detail=False, methods=['post'], url_path='register')
    def register(self, request):
        """
        Agent 启动时调：POST /api/performance/load-generators/register/
        body: {pod_name, hostname, ip, port, token, cpu_cores, memory_gb,
               max_vusers, jmeter_version, orchestrator_type}
        语义 = upsert（按 pod_name 唯一）：第一次创建，后续重启更新。
        """
        if not _check_agent_token(request):
            return Response({'detail': 'Invalid agent token'}, status=401)

        data = request.data
        pod_name = data.get('pod_name')
        if not pod_name:
            return Response({'detail': 'pod_name required'}, status=400)

        defaults = {
            'hostname': data.get('hostname', ''),
            'ip': data.get('ip', ''),
            'port': int(data.get('port', 9100)),
            'token': data.get('token', ''),
            'cpu_cores': int(data.get('cpu_cores', 0) or 0),
            'memory_gb': float(data.get('memory_gb', 0) or 0),
            'max_vusers': int(data.get('max_vusers', 100) or 100),
            'jmeter_version': data.get('jmeter_version', ''),
            'orchestrator_type': data.get('orchestrator_type', 'docker'),
            'status': LoadGeneratorStatus.IDLE,
            'last_heartbeat_at': timezone.now(),
            'released_at': None,
        }
        lg, created = LoadGenerator.objects.update_or_create(
            pod_name=pod_name, defaults=defaults,
        )
        return Response(
            LoadGeneratorSerializer(lg).data,
            status=201 if created else 200,
        )

    @action(detail=False, methods=['post'], url_path='scale-up')
    def scale_up(self, request):
        """
        POST /api/performance/load-generators/scale-up/  body: {count: int}
        前端「+ 扩容 N 台」按钮调；编排适配器拉起新副本，agent 起来后自调 register。
        立即返回当前已知 pod_name 列表（不阻塞等 register）。
        """
        try:
            count = int(request.data.get('count', 1))
        except (TypeError, ValueError):
            return Response({'detail': 'count must be int'}, status=400)
        if count < 1 or count > 20:
            return Response({'detail': 'count must be in [1, 20]'}, status=400)

        from .services.orchestrator import OrchestratorError, get_adapter
        try:
            adapter = get_adapter()
            new_pods = adapter.scale_up(count)
        except (OrchestratorError, NotImplementedError) as e:
            return Response({'detail': f'编排适配器: {e}'}, status=503)
        except Exception as e:  # noqa: BLE001
            return Response({'detail': f'扩容失败: {e}'}, status=500)
        return Response({'new_pods': new_pods, 'count': count}, status=202)

    @action(detail=False, methods=['post'], url_path='scale-down')
    def scale_down(self, request):
        """
        POST body: {pod_names?: [str]} 或 {idle_only: true}
        - pod_names：明确缩这几台
        - idle_only：把所有 idle 的容器都释放（v1.2 release_idle_agents 命令也调它）
        """
        pod_names = request.data.get('pod_names')
        idle_only = request.data.get('idle_only')

        if idle_only:
            idle_lgs = LoadGenerator.objects.filter(status=LoadGeneratorStatus.IDLE)
            pod_names = [lg.pod_name for lg in idle_lgs]
        if not pod_names:
            return Response({'detail': '请指定 pod_names 或 idle_only=true'}, status=400)

        from .services.orchestrator import OrchestratorError, get_adapter
        try:
            adapter = get_adapter()
            removed = adapter.scale_down(pod_names)
        except (OrchestratorError, NotImplementedError) as e:
            return Response({'detail': f'编排适配器: {e}'}, status=503)
        # 同步把 DB 行也标记 released（避免心跳超时窗口里前端还看到僵尸 idle）
        LoadGenerator.objects.filter(pod_name__in=removed).update(
            status=LoadGeneratorStatus.LOST,
            released_at=timezone.now(),
        )
        return Response({'removed': removed})

    @action(detail=True, methods=['get'], url_path='system-metrics')
    def system_metrics(self, request, pk=None):
        """
        前端弹窗轮询：GET /api/performance/load-generators/:id/system-metrics/
        主控代理到 agent /system-metrics（5s timeout，agent 不可达 → 503）。
        """
        import requests as _requests  # 局部 import 避 view 文件顶部装一堆
        try:
            lg = LoadGenerator.objects.get(pk=pk)
        except LoadGenerator.DoesNotExist:
            return Response({'detail': 'load generator not found'}, status=404)
        try:
            r = _requests.get(f'{lg.base_url}/system-metrics', timeout=5)
            if r.status_code != 200:
                return Response({'detail': f'agent returned {r.status_code}'}, status=503)
            return Response(r.json())
        except _requests.RequestException as e:
            return Response({'detail': f'agent unreachable: {e}'}, status=503)

    @action(detail=True, methods=['put'], url_path='heartbeat')
    def heartbeat(self, request, pk=None):
        """
        Agent 周期性调：PUT /api/performance/load-generators/:id/heartbeat/
        body 可选 {status} 上报当前状态（idle/busy）；默认保留现有 status。
        """
        if not _check_agent_token(request):
            return Response({'detail': 'Invalid agent token'}, status=401)

        try:
            lg = LoadGenerator.objects.get(pk=pk)
        except LoadGenerator.DoesNotExist:
            return Response({'detail': 'load generator not found'}, status=404)

        next_status = request.data.get('status')
        update_fields = ['last_heartbeat_at']
        lg.last_heartbeat_at = timezone.now()
        # lost 状态收到心跳 → 自动复活回 idle
        if lg.status == LoadGeneratorStatus.LOST:
            lg.status = LoadGeneratorStatus.IDLE
            update_fields.append('status')
        if next_status in {s.value for s in LoadGeneratorStatus}:
            lg.status = next_status
            if 'status' not in update_fields:
                update_fields.append('status')
        lg.save(update_fields=update_fields)
        return Response(LoadGeneratorSerializer(lg).data)
