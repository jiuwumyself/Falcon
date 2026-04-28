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

    class Meta:
        model = Task
        fields = [
            'id', 'title', 'description', 'biz_category',
            'jmx_filename', 'jmx_hash',
            'virtual_users', 'ramp_up_seconds', 'duration_seconds',
            'thread_groups_config', 'environment',
            'csv_bindings', 'status',
            'owner', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'jmx_filename', 'jmx_hash', 'thread_groups_config',
            'csv_bindings', 'status',
            'owner', 'created_at', 'updated_at',
        ]

    def get_status(self, obj: Task) -> str:
        # v1: 待配置 / 已配置；v1.1+ 加 running / success / failed
        return 'configured' if obj.thread_groups_config else 'draft'


class MetricSampleSerializer(serializers.ModelSerializer):
    class Meta:
        model = MetricSample
        fields = ['id', 'run', 'timestamp', 'rps', 'p99_ms', 'error_rate', 'active_users']
        read_only_fields = fields


class TaskRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaskRun
        fields = [
            'id', 'task', 'status',
            'started_at', 'finished_at',
            'virtual_users', 'ramp_up_seconds', 'duration_seconds',
            'total_requests', 'avg_rps', 'p99_ms', 'error_rate',
            'error_message',
        ]
        read_only_fields = ['status', 'started_at', 'finished_at',
                            'total_requests', 'avg_rps', 'p99_ms', 'error_rate',
                            'error_message']
