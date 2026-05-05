from django.contrib import admin

from .models import BackendListenerConfig, Environment, MetricSample, Task, TaskCsvBinding, TaskRun


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


@admin.register(BackendListenerConfig)
class BackendListenerConfigAdmin(admin.ModelAdmin):
    """Backend Listener 全局配置——只允许存在一条（pk=1），不能新增也不能删除。"""
    list_display = ('id', 'enabled', 'influxdb_url', 'application', 'measurement')
    readonly_fields = ('id',)

    def has_add_permission(self, request):
        return not BackendListenerConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
