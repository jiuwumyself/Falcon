from rest_framework import serializers

from .models import Environment, MetricSample, Task, TaskRun


class EnvironmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Environment
        fields = [
            'id', 'name', 'description', 'is_default', 'host_entries',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields  # 前端只读，编辑走 admin


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = [
            'id', 'title', 'description', 'biz_category',
            'jmx_filename', 'jmx_hash', 'csv_filename',
            'virtual_users', 'ramp_up_seconds', 'duration_seconds',
            'run_jmx_filename', 'thread_groups_config', 'environment',
            'owner', 'created_at', 'updated_at',
        ]
        read_only_fields = [
            'jmx_filename', 'jmx_hash', 'csv_filename',
            'run_jmx_filename', 'thread_groups_config',
            'owner', 'created_at', 'updated_at',
        ]


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
