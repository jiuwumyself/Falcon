from django.conf import settings
from django.db import models
from django.utils import timezone

from .services.jmeter import delete_csv, delete_script, get_scripts_dir


class BizCategory(models.TextChoices):
    SHARED = 'shared', '共享课'
    AI = 'ai', 'AI 事业中心'
    KG = 'kg', 'KG 知识图谱'


class RunStatus(models.TextChoices):
    PENDING = 'pending', '待执行'
    RUNNING = 'running', '执行中'
    SUCCESS = 'success', '成功'
    FAIL = 'fail', '失败'
    CANCELLED = 'cancelled', '已取消'


def csv_upload_path(instance, filename):
    """Legacy — kept only because performance/migrations/0001_initial.py references it
    (old FileField). The `csv_to_scripts` migration drops that FileField; this
    function is no longer called at runtime and can be deleted once 0001 is squashed."""
    return f'csv/{instance.id or "new"}/{filename}'


class Environment(models.Model):
    """
    一个压测环境（测试 / 生产 / UAT …）。承载 hosts 映射，执行时
    注入到 JMX 的 DNSCacheManager，不需要修改远程机的 /etc/hosts。

    创建/编辑走 Django admin（/admin/performance/environment/）；
    前端只做下拉选择（只读）。
    """
    name = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=200, blank=True)
    is_default = models.BooleanField(default=False)
    # [{"hostname": "api.example.com", "ip": "10.0.0.1"}, ...]
    host_entries = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_default', 'name']

    def __str__(self) -> str:
        return self.name + (' (默认)' if self.is_default else '')


class TaskManager(models.Manager):
    """Default manager: hide soft-deleted tasks."""
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class Task(models.Model):
    """
    一个压测任务（对应一份 JMX 文件 + 可选的 CSV 参数化文件）。

    JMX / CSV 文件都物理存放在 <JMETER_HOME>/scripts/，由
    performance/services/jmeter.py 管理。`jmx_filename` / `csv_filename`
    只存文件名本身（不含路径）。
    """
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    biz_category = models.CharField(
        max_length=20, choices=BizCategory.choices, default=BizCategory.SHARED,
    )

    jmx_filename = models.CharField(max_length=255, blank=True)
    jmx_hash = models.CharField(max_length=64, blank=True, db_index=True)

    # CSV 参数化文件和 .jmx 存在同一个 scripts/ 目录下，命名 `<jmx_stem>.csv`
    # （冲突追加 `_2`、`_3`）。这里只记文件名，物理文件由 services/jmeter.py 管理。
    csv_filename = models.CharField(max_length=255, blank=True)

    # 从 JMX 里解析出来的可编辑字段
    virtual_users = models.PositiveIntegerField(default=10)
    ramp_up_seconds = models.PositiveIntegerField(default=0)
    duration_seconds = models.PositiveIntegerField(default=60)

    # ── Step 2 派生产物 ──────────────────────────────────
    # run_jmx_filename: 保存 Step 2 配置后生成的可执行脚本文件名，空串 = 尚未配置。
    # 物理文件和原件同在 scripts/ 下，命名 `<jmx_stem>_run.jmx`。
    # 执行压测用这份，不污染原件 jmx_filename。
    run_jmx_filename = models.CharField(max_length=255, blank=True)

    # thread_groups_config: Step 2 里用户为每个启用的 ThreadGroup 选的
    # 类型和参数；保存 Step 2 时从原件 + 此配置重新生成 run_jmx。
    # 形如 [{"path": "0.0", "kind": "ThreadGroup", "params": {...}}, ...]
    thread_groups_config = models.JSONField(default=list, blank=True)

    # environment: Step 2 选的压测环境（hosts 映射等）。
    environment = models.ForeignKey(
        'Environment', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tasks',
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tasks',
    )

    # Soft delete
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TaskManager()           # default: excludes soft-deleted
    all_objects = models.Manager()    # raw, for admin / audit

    class Meta:
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'{self.title} [{self.biz_category}]'

    # ── JMX file convenience ────────────────────────────
    def jmx_path(self):
        """Absolute Path to the on-disk .jmx file (原件)."""
        return get_scripts_dir() / self.jmx_filename

    def read_jmx_bytes(self) -> bytes:
        return self.jmx_path().read_bytes()

    def write_jmx_bytes(self, data: bytes) -> None:
        self.jmx_path().write_bytes(data)

    # ── Run JMX (Step 2 派生产物) ───────────────────────
    def run_jmx_path(self):
        """Absolute Path to the on-disk .run.jmx file, or None when not set."""
        return get_scripts_dir() / self.run_jmx_filename if self.run_jmx_filename else None

    def read_run_jmx_bytes(self) -> bytes:
        path = self.run_jmx_path()
        return path.read_bytes() if path else b''

    def write_run_jmx_bytes(self, data: bytes) -> None:
        path = self.run_jmx_path()
        if path is not None:
            path.write_bytes(data)

    # ── CSV file convenience ────────────────────────────
    def csv_path(self):
        """Absolute Path to the on-disk CSV file, or None when not set."""
        return get_scripts_dir() / self.csv_filename if self.csv_filename else None

    def read_csv_bytes(self) -> bytes:
        path = self.csv_path()
        return path.read_bytes() if path else b''

    def write_csv_bytes(self, data: bytes) -> None:
        path = self.csv_path()
        if path is not None:
            path.write_bytes(data)

    # ── Soft delete ─────────────────────────────────────
    def delete(self, using=None, keep_parents=False):
        """
        Soft-delete: mark is_deleted + deleted_at, physically remove the
        on-disk .jmx + .run.jmx + .csv so the JMeter scripts folder doesn't
        accumulate. TaskRun / MetricSample rows stay via FK; queries via
        `Task.objects` won't see this task.
        """
        if self.jmx_filename:
            delete_script(self.jmx_filename)
        if self.run_jmx_filename:
            delete_script(self.run_jmx_filename)
        if self.csv_filename:
            delete_csv(self.csv_filename)
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.jmx_filename = ''     # path is gone — don't keep dangling reference
        self.run_jmx_filename = ''
        self.csv_filename = ''
        self.save(update_fields=[
            'is_deleted', 'deleted_at',
            'jmx_filename', 'run_jmx_filename', 'csv_filename', 'updated_at',
        ])

    def hard_delete(self, using=None, keep_parents=False):
        """Escape hatch for genuine DB row removal (e.g. admin). Not used by API."""
        if self.jmx_filename:
            delete_script(self.jmx_filename)
        if self.run_jmx_filename:
            delete_script(self.run_jmx_filename)
        if self.csv_filename:
            delete_csv(self.csv_filename)
        return super().delete(using=using, keep_parents=keep_parents)


class TaskRun(models.Model):
    """Task 的一次执行记录（v1 先建表，v1.1 接 JMeter CLI 后往里写）"""
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='runs')
    status = models.CharField(
        max_length=20, choices=RunStatus.choices, default=RunStatus.PENDING,
    )

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    # 执行参数快照
    virtual_users = models.PositiveIntegerField()
    ramp_up_seconds = models.PositiveIntegerField(default=0)
    duration_seconds = models.PositiveIntegerField()

    # 汇总指标
    total_requests = models.PositiveIntegerField(default=0)
    avg_rps = models.FloatField(default=0)
    p99_ms = models.FloatField(default=0)
    error_rate = models.FloatField(default=0)  # 0-100 百分比

    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self) -> str:
        return f'Run #{self.id} of "{self.task.title}" [{self.status}]'


class MetricSample(models.Model):
    """TaskRun 执行过程中的时序采样点（v1 先建表，v1.1 开始写入）"""
    run = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name='samples')
    timestamp = models.DateTimeField()

    rps = models.FloatField()
    p99_ms = models.FloatField()
    error_rate = models.FloatField()
    active_users = models.PositiveIntegerField()

    class Meta:
        ordering = ['timestamp']
        indexes = [models.Index(fields=['run', 'timestamp'])]
