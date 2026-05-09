from django.contrib import admin

from .models import (
    BackendListenerConfig, Environment, LoadGenerator, MetricSample,
    PinpointConfig, RunPinpointTrace, Service, Task, TaskCsvBinding, TaskRun,
)


@admin.register(Environment)
class EnvironmentAdmin(admin.ModelAdmin):
    """压测环境（hosts 映射）在这里维护；前端只读。"""
    list_display = ('id', 'name', 'is_default', 'host_entries', 'updated_at')
    list_filter = ('is_default',)
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at')


class TaskCsvBindingInline(admin.TabularInline):
    model = TaskCsvBinding
    extra = 0
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    """Admin: use all_objects so soft-deleted tasks remain visible for audit."""
    list_display = (
        'id', 'title', 'biz_category', 'virtual_users', 'duration_seconds',
        'environment', 'owner', 'is_deleted', 'deleted_at', 'created_at',
    )
    list_filter = ('biz_category', 'environment', 'is_deleted', 'created_at')
    search_fields = ('title', 'description', 'jmx_filename')
    readonly_fields = (
        'jmx_filename', 'jmx_hash', 'thread_groups_config',
        'created_at', 'updated_at', 'deleted_at',
    )
    inlines = [TaskCsvBindingInline]

    def get_queryset(self, request):
        return Task.all_objects.all()


@admin.register(TaskRun)
class TaskRunAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'run_id', 'task', 'status',
        'started_at', 'finished_at',
        'avg_rps', 'p99_ms', 'error_rate', 'archived_at',
    )
    list_filter = ('status', 'archived_at')
    search_fields = ('run_id', 'task__title')
    readonly_fields = (
        'run_id', 'pre_check_log', 'pid', 'stop_port',
        'last_heartbeat_at', 'cancel_requested_at', 'archived_at',
    )


@admin.register(MetricSample)
class MetricSampleAdmin(admin.ModelAdmin):
    list_display = ('id', 'run', 'timestamp', 'rps', 'p99_ms', 'error_rate', 'active_users')
    list_filter = ('run',)


@admin.register(LoadGenerator)
class LoadGeneratorAdmin(admin.ModelAdmin):
    """容器化压力源（v1.2）。注册由 agent 调 /api/internal/agents/register 完成；
    admin 主要用于查看状态、手动调整 max_vusers / 释放卡死的 lost 行。"""
    list_display = (
        'id', 'pod_name', 'status', 'ip', 'port',
        'cpu_cores', 'memory_gb', 'max_vusers',
        'orchestrator_type', 'last_heartbeat_at', 'registered_at',
    )
    list_filter = ('status', 'orchestrator_type')
    search_fields = ('pod_name', 'hostname', 'ip')
    readonly_fields = ('registered_at', 'last_heartbeat_at', 'released_at')


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    """被压测服务（v1.3 Grafana 接入 v0）。Step 2 task.service_names 多选基于
    service.name 反查；Step 3 ServicePanelsTab / TraceTab / JVM tab 用
    grafana_panels 嵌入 iframe。前端只读，编辑走这里。"""
    list_display = ('id', 'name', 'pinpoint_app', 'base_url', 'updated_at')
    search_fields = ('name', 'description', 'pinpoint_app')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('基本信息', {'fields': ('name', 'description', 'base_url')}),
        ('监控接入', {'fields': ('grafana_url', 'grafana_panels', 'pinpoint_app')}),
        ('诊断接入（v1.5+）', {'fields': ('arthus_endpoint',)}),
        ('元信息', {'fields': ('created_at', 'updated_at')}),
    )


@admin.register(BackendListenerConfig)
class BackendListenerConfigAdmin(admin.ModelAdmin):
    """Backend Listener 全局配置——只允许存在一条（pk=1），不能新增也不能删除。"""
    list_display = ('id', 'enabled', 'influxdb_url', 'application', 'measurement')
    readonly_fields = ('id',)

    def has_add_permission(self, request):
        return not BackendListenerConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PinpointConfig)
class PinpointConfigAdmin(admin.ModelAdmin):
    """Pinpoint 全局配置（v1.3，singleton）。enabled=False 时整个 collector 流程
    skip，前端 TracePanelsTab 显示"未启用"占位。"""
    list_display = ('id', 'enabled', 'base_url', 'request_timeout_sec')
    readonly_fields = ('id',)

    def has_add_permission(self, request):
        return not PinpointConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RunPinpointTrace)
class RunPinpointTraceAdmin(admin.ModelAdmin):
    """run 终态从 Pinpoint 拉的慢 trace 元数据（v1.3）。仅查看 / 排查用，自动入库。"""
    list_display = ('id', 'run', 'service_name', 'trace_id', 'elapsed_ms', 'exception_type', 'created_at')
    list_filter = ('service_name', 'exception_type')
    search_fields = ('trace_id', 'service_name', 'run__run_id')
    readonly_fields = (
        'run', 'service_name', 'trace_id', 'elapsed_ms', 'start_ts_ms',
        'exception_type', 'pinpoint_detail_url', 'created_at',
    )

    def has_add_permission(self, request):
        return False  # 只能由 pinpoint_collector 写入
