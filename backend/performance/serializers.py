from rest_framework import serializers

from .models import (
    Environment, LoadGenerator, MetricSample, RunEventAnchor, RunPinpointTrace,
    Service, Task, TaskCsvBinding, TaskRun,
)


class EnvironmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Environment
        fields = [
            'id', 'name', 'description', 'is_default', 'host_entries',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields  # 前端只读，编辑走 admin


class ServiceSerializer(serializers.ModelSerializer):
    """G2：被压测服务列表（v1.3 Grafana 接入 v0）。前端只读，编辑走 admin。"""
    class Meta:
        model = Service
        fields = [
            'id', 'name', 'description', 'base_url', 'grafana_url',
            'pinpoint_app', 'arthus_endpoint', 'grafana_panels',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields


class TaskCsvBindingSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskCsvBinding
        fields = ['component_path', 'filename']
        read_only_fields = fields


class TaskSerializer(serializers.ModelSerializer):
    csv_bindings = TaskCsvBindingSerializer(many=True, read_only=True)
    status = serializers.SerializerMethodField()
    active_run_id = serializers.SerializerMethodField()
    # 检测 Step 2 入库的 thread_groups_config 是否跟 jmx 当前启用 TG 同步：
    # 用户在 Step 1 toggle 了 TG enabled / 改了类型但没回 Step 2 重新保存时
    # 为 true。前端 ExecuteStage 据此显示警告 banner 并 disable "开始" 按钮。
    config_stale = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            'id', 'title', 'description', 'biz_category',
            'jmx_filename', 'jmx_hash',
            'virtual_users', 'ramp_up_seconds', 'duration_seconds',
            'thread_groups_config', 'environment', 'service_names',
            'csv_bindings', 'status', 'active_run_id', 'config_stale',
            'owner', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'jmx_filename', 'jmx_hash', 'thread_groups_config',
            'csv_bindings', 'status', 'active_run_id', 'config_stale',
            'owner', 'created_at', 'updated_at',
        ]

    def get_config_stale(self, obj: Task) -> bool:
        from .services.jmx import detect_thread_groups_config_stale  # noqa: PLC0415
        try:
            return detect_thread_groups_config_stale(obj)
        except Exception:  # noqa: BLE001
            return False

    def _latest_run(self, obj: Task):
        return obj.runs.order_by('-id').first()

    def get_status(self, obj: Task) -> str:
        """
        前端列表行徽章：
          - 有活跃 run（pre_checking / pending / running / cancelling）→ 直接展示 run 状态
          - 否则有最近终态 run → 展示终态
          - 都没有 → draft / configured
        """
        run = self._latest_run(obj)
        if run is not None:
            return run.status
        return 'configured' if obj.thread_groups_config else 'draft'

    def get_active_run_id(self, obj: Task) -> str | None:
        """前端拉到列表行后，如果有活跃 run 可直接接 metrics 端点。"""
        active = obj.runs.filter(
            status__in=['pre_checking', 'pending', 'running', 'cancelling'],
        ).first()
        return active.run_id if active else None


class MetricSampleSerializer(serializers.ModelSerializer):
    class Meta:
        model = MetricSample
        fields = ['id', 'run', 'timestamp', 'rps', 'p99_ms', 'error_rate', 'active_users']
        read_only_fields = fields


class TaskRunSerializer(serializers.ModelSerializer):
    # 全程预估秒数（含 ramp + steady + cool_down）—— 来自 scheduler.estimate_max_wall_sec。
    # 前端 RunControlBar 进度条用它当分母，避免 elapsed 超过 task.duration_seconds 时进度溢出。
    max_wall_sec = serializers.SerializerMethodField()
    # run.created_at（pre_check 开始时刻），前端进度条起点用
    created_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = TaskRun
        fields = [
            'id', 'run_id', 'task', 'status',
            'created_at', 'started_at', 'finished_at',
            'virtual_users', 'ramp_up_seconds', 'duration_seconds',
            'max_wall_sec',
            'total_requests', 'avg_rps', 'p99_ms', 'error_rate',
            'error_breakdown',  # § 12 S2 失败原因 5 类分桶
            'error_message', 'pre_check_log', 'runtime_log',
            'pid', 'stop_port', 'last_heartbeat_at',
            'cancel_requested_at', 'archived_at',
            'thread_groups_config_snapshot', 'jmx_hash_snapshot',
        ]
        read_only_fields = fields  # 写入由 RunExecutor 控制，不通过 serializer

    def get_max_wall_sec(self, obj):
        from .services.scheduler import estimate_max_wall_sec  # noqa: PLC0415
        try:
            return int(estimate_max_wall_sec(
                obj.task.thread_groups_config or [],
                fallback_seconds=obj.duration_seconds or 0,
            ))
        except Exception:  # noqa: BLE001
            return obj.duration_seconds or 0


class RunEventAnchorSerializer(serializers.ModelSerializer):
    """§ 12 S1：run 期间的关键事件锚点。前端时间轴 markLine 用。"""
    class Meta:
        model = RunEventAnchor
        fields = ['id', 'event_type', 'ts_ms', 'metadata', 'created_at']
        read_only_fields = fields


class RunPinpointTraceSerializer(serializers.ModelSerializer):
    """§ 11 Pinpoint 接入 v0：run 终态拉到的慢 trace 元数据列表。"""
    class Meta:
        model = RunPinpointTrace
        fields = [
            'id', 'service_name', 'trace_id', 'elapsed_ms', 'start_ts_ms',
            'exception_type', 'pinpoint_detail_url', 'created_at',
        ]
        read_only_fields = fields


class LoadGeneratorSerializer(serializers.ModelSerializer):
    """前端只读列出可用压力源；写入由 agent 走内部 register/heartbeat 端点。"""
    base_url = serializers.ReadOnlyField()

    class Meta:
        model = LoadGenerator
        fields = [
            'id', 'pod_name', 'hostname', 'ip', 'port', 'base_url',
            'status', 'cpu_cores', 'memory_gb', 'max_vusers',
            'jmeter_version', 'orchestrator_type',
            'registered_at', 'last_heartbeat_at', 'released_at',
            # token 不暴露给前端
        ]
        read_only_fields = fields
