import hashlib
import re
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import Environment, Task, TaskCsvBinding
from .serializers import EnvironmentSerializer, TaskSerializer
from .services.jmeter import (
    DiskFullError, delete_csv, delete_script, ensure_jmeter_installed,
    ensure_plugins_installed, get_scripts_dir, rename_script,
    unique_script_filename, write_csv, write_jar, write_script,
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


class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all()  # TaskManager already excludes soft-deleted
    serializer_class = TaskSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

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
