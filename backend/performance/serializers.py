from rest_framework import serializers

from .models import Environment, MetricSample, Task, TaskCsvBinding, TaskRun


class EnvironmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Environment
        fields = [
            'id', 'name', 'description', 'is_default', 'host_entries',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields  # 前端只读，编辑走 admin


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
            'thread_groups_config', 'environment',
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
            'error_message', 'pre_check_log',
            'pid', 'stop_port', 'last_heartbeat_at',
            'cancel_requested_at', 'archived_at',
        ]
        read_only_fields = fields  # 写入由 RunExecutor 控制，不通过 serializer
