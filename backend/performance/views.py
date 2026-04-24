import hashlib
import re

from django.conf import settings
from django.http import FileResponse, Http404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import Environment, Task
from .serializers import EnvironmentSerializer, TaskSerializer
from .services.jmeter import (
    delete_csv, delete_script, ensure_jmeter_installed, ensure_plugins_installed,
    rename_script, sanitize_script_name, unique_csv_filename,
    unique_script_filename, write_csv, write_script,
)
from .services.jmx import (
    JmxParseError, get_component_detail, list_components, list_thread_groups,
    parse_jmx, patch_jmx, rename_component, replace_thread_group,
    toggle_component, update_component_detail,
)
from .services.validator import validate_task


_DATE_PREFIX = re.compile(r'^\d{4}-\d{2}-\d{2}_')


def _prefixed_title(raw: str) -> str:
    """'<YYYY-MM-DD>_<raw>' — skip if already prefixed."""
    raw = (raw or '').strip()
    if not raw:
        raw = 'task'
    if _DATE_PREFIX.match(raw):
        return raw
    return f'{timezone.localdate().isoformat()}_{raw}'


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

        # Title = <date>_<user title (or filename fallback)>
        raw_title = request.data.get('title') or jmx_upload.name.rsplit('.', 1)[0]
        full_title = _prefixed_title(raw_title)
        filename = unique_script_filename(full_title)

        write_script(filename, xml_bytes)

        data = request.data.copy()
        data['title'] = full_title
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

    # —— 重新上传：覆盖同一任务的 JMX 文件，保留其余字段 —— #
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

        # 覆盖写入同一文件（title / jmx_filename 不变）
        instance.write_jmx_bytes(xml_bytes)
        instance.jmx_hash = hashlib.sha256(xml_bytes).hexdigest()
        instance.virtual_users = fields.virtual_users
        instance.ramp_up_seconds = fields.ramp_up_seconds
        instance.duration_seconds = fields.duration_seconds or instance.duration_seconds
        instance.save(update_fields=[
            'jmx_hash', 'virtual_users', 'ramp_up_seconds', 'duration_seconds', 'updated_at',
        ])
        return Response(self.get_serializer(instance).data)

    @action(detail=True, methods=['post'], url_path='upload-csv',
            parser_classes=[MultiPartParser, FormParser])
    def upload_csv(self, request, pk=None):
        instance = self.get_object()
        csv_upload = request.FILES.get('csv_file')
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

        # 清掉旧 CSV；新文件按 <jmx_stem>.csv 命名落在 scripts/ 下
        if instance.csv_filename:
            delete_csv(instance.csv_filename)
        new_csv_name = unique_csv_filename(instance.jmx_filename)
        write_csv(new_csv_name, csv_upload.read())
        instance.csv_filename = new_csv_name
        instance.save(update_fields=['csv_filename', 'updated_at'])
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

    # —— 组件树：Step 1 任务配置用 —— #
    @action(detail=True, methods=['get'], url_path='components')
    def components(self, request, pk=None):
        instance = self.get_object()
        try:
            xml_bytes = instance.read_jmx_bytes()
        except (FileNotFoundError, OSError) as e:
            raise Http404(f'JMX 文件不存在: {e}')
        return Response([c.to_dict() for c in list_components(xml_bytes)])

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
        return Response([c.to_dict() for c in list_components(new_xml)])

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
        return Response([c.to_dict() for c in list_components(new_xml)])

    # —— Step 2：任务配置（线程组替换） —— #
    @action(detail=True, methods=['get', 'patch'], url_path='thread-groups')
    def thread_groups(self, request, pk=None):
        """
        GET: 读原件 JMX，返回当前所有 ThreadGroup + DB 里已存的 thread_groups_config
        PATCH: 按 body 的 thread_groups 配置，从原件重新生成 <title>_run.jmx
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

        # 需要 Stepping / Concurrency 的话，确保插件已装
        needs_plugins = any(
            c.get('kind') in ('SteppingThreadGroup', 'ConcurrencyThreadGroup')
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

        # 从原件读 → 逐个替换
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

        # 写入 <jmx_stem>_run.jmx；首次保存才分配文件名
        if not instance.run_jmx_filename:
            stem = instance.jmx_filename.removesuffix('.jmx') if instance.jmx_filename else 'task'
            instance.run_jmx_filename = unique_script_filename(f'{stem}_run')
        instance.write_run_jmx_bytes(xml_bytes)

        # 保存配置 + 同步 virtual_users/ramp_up/duration（用第一个启用 TG 的参数）
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
            'run_jmx_filename', 'thread_groups_config', 'environment',
            'virtual_users', 'ramp_up_seconds', 'duration_seconds', 'updated_at',
        ])

        return Response(self.get_serializer(instance).data)

    # —— Step 2：1 并发校验（用 Python requests 模拟，不走 JMeter CLI） —— #
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

        # Prefer run jmx if it exists (Step 2 saved); otherwise fall back to
        # the original — lets users validate right after upload without
        # going through Save first.
        try:
            if instance.run_jmx_filename:
                xml_bytes = instance.read_run_jmx_bytes()
            else:
                xml_bytes = instance.read_jmx_bytes()
        except (FileNotFoundError, OSError) as e:
            raise Http404(f'JMX 文件不存在: {e}')

        results = validate_task(xml_bytes, host_entries=host_entries)
        return Response([r.to_dict() for r in results])

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
        return Response([c.to_dict() for c in list_components(new_xml)])
