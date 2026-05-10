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

    class Meta:
        model = Task
        fields = [
            'id', 'title', 'description', 'biz_category',
            'jmx_filename', 'jmx_hash',
            'virtual_users', 'ramp_up_seconds', 'duration_seconds',
            'thread_groups_config', 'environment', 'service_names',
            'csv_bindings', 'status', 'active_run_id',
            'owner', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'jmx_filename', 'jmx_hash', 'thread_groups_config',
            'csv_bindings', 'status', 'active_run_id',
            'owner', 'created_at', 'updated_at',
        ]

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
    class Meta:
        model = TaskRun
        fields = [
            'id', 'run_id', 'task', 'status',
            'started_at', 'finished_at',
            'virtual_users', 'ramp_up_seconds', 'duration_seconds',
            'total_requests', 'avg_rps', 'p99_ms', 'error_rate',
            'error_breakdown',  # § 12 S2 失败原因 5 类分桶
            'error_message', 'pre_check_log',
            'pid', 'stop_port', 'last_heartbeat_at',
            'cancel_requested_at', 'archived_at',
        ]
        read_only_fields = fields  # 写入由 RunExecutor 控制，不通过 serializer


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
