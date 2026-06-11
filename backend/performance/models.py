from django.conf import settings
from django.db import models
from django.db.models import Q, UniqueConstraint
from django.utils import timezone

from .services.jmeter import delete_csv, delete_script, get_scripts_dir


class BizCategory(models.TextChoices):
    SHARED = 'shared', '共享课'
    AI = 'ai', 'AI 事业中心'
    KG = 'kg', 'KG 知识图谱'
    CUSTOM = 'custom', '定制'


class RunStatus(models.TextChoices):
    PRE_CHECKING = 'pre_checking', '环境检测中'
    PRE_CHECK_FAILED = 'pre_check_failed', '环境检测失败'
    PENDING = 'pending', '待执行'
    RUNNING = 'running', '执行中'
    CANCELLING = 'cancelling', '正在停止'
    SUCCESS = 'success', '成功'
    FAILED = 'failed', '失败'
    TIMEOUT = 'timeout', '超时'
    CANCELLED = 'cancelled', '已取消'


# 非终态：用于唯一约束 + 控制可 cancel
ACTIVE_RUN_STATUSES = (
    RunStatus.PRE_CHECKING,
    RunStatus.PENDING,
    RunStatus.RUNNING,
    RunStatus.CANCELLING,
)
TERMINAL_RUN_STATUSES = (
    RunStatus.PRE_CHECK_FAILED,
    RunStatus.SUCCESS,
    RunStatus.FAILED,
    RunStatus.TIMEOUT,
    RunStatus.CANCELLED,
)


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
        verbose_name = '压测环境'
        verbose_name_plural = '压测环境'
        ordering = ['-is_default', 'name']

    def __str__(self) -> str:
        return self.name + (' (默认)' if self.is_default else '')


class TaskManager(models.Manager):
    """Default manager: hide soft-deleted tasks."""
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


class TaskRunManager(models.Manager):
    """Default manager: hide soft-deleted runs（保留行做大盘统计，但 dropdown / list 不显示）。"""
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

    # 从 JMX 里解析出来的可编辑字段
    virtual_users = models.PositiveIntegerField(default=10)
    ramp_up_seconds = models.PositiveIntegerField(default=0)
    duration_seconds = models.PositiveIntegerField(default=60)

    # thread_groups_config: Step 2 里用户为每个启用的 ThreadGroup 选的
    # 场景 / 类型和参数。跑压测时由 services/jmx.py::build_run_xml 从原件 + 此配置
    # 在内存生成可执行 XML（不再派生 _run.jmx 物理文件）。
    # 形如 [{"path": "0.0", "scenario": "load", "kind": "SteppingThreadGroup", "params": {...}}, ...]
    thread_groups_config = models.JSONField(default=list, blank=True)

    # environment: Step 2 选的压测环境（hosts 映射等）。
    environment = models.ForeignKey(
        'Environment', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tasks',
    )

    # service_names: Step 2 选的"被压测服务"名列表（v1.2 新增；服务库当前为前端 mock，
    # 这里只存名字字符串数组。v1.3 接后端 Service 表后改为 M2M）。
    # 多选语义：一个压测任务可能同时关联上下游多个服务（链路一起测）。
    service_names = models.JSONField(default=list, blank=True)

    # prometheus_source: Step 2 选的 Prometheus 数据源，Step 3 查服务监控指标用。
    # 与 service_names 一起在 Step 2 保存时写入；null = 未选数据源（降级为空面板）。
    prometheus_source = models.ForeignKey(
        'PrometheusDataSource', on_delete=models.SET_NULL,
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
        verbose_name = '压测任务'
        verbose_name_plural = '压测任务'
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

    # ── Soft delete ─────────────────────────────────────
    def _purge_files(self) -> None:
        if self.jmx_filename:
            delete_script(self.jmx_filename)
        for binding in self.csv_bindings.all():
            if binding.filename:
                delete_csv(binding.filename)

    def delete(self, using=None, keep_parents=False):
        """
        Soft-delete: mark is_deleted + deleted_at, physically remove the
        on-disk .jmx + bound CSVs so the JMeter scripts folder doesn't
        accumulate. TaskRun / MetricSample rows stay via FK; queries via
        `Task.objects` won't see this task.
        """
        self._purge_files()
        self.csv_bindings.all().delete()
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.jmx_filename = ''     # path is gone — don't keep dangling reference
        self.save(update_fields=[
            'is_deleted', 'deleted_at', 'jmx_filename', 'updated_at',
        ])

    def hard_delete(self, using=None, keep_parents=False):
        """Escape hatch for genuine DB row removal (e.g. admin). Not used by API."""
        self._purge_files()
        return super().delete(using=using, keep_parents=keep_parents)


class TaskCsvBinding(models.Model):
    """
    每个 CSVDataSet 组件可独立绑定一个 CSV 文件。`component_path` 是组件树的索引路径
    （和 services/jmx.py 的 path 语义一致，例如 "0.0.3"）。物理文件落 scripts/ 下，
    命名 `<jmx_stem>__<safe_path>.csv`。
    """
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='csv_bindings')
    component_path = models.CharField(max_length=64)
    filename = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('task', 'component_path')]
        ordering = ['component_path']

    def __str__(self) -> str:
        return f'{self.task_id}@{self.component_path} → {self.filename}'

    def csv_path(self):
        return get_scripts_dir() / self.filename if self.filename else None

    def read_csv_bytes(self) -> bytes:
        path = self.csv_path()
        return path.read_bytes() if path else b''

    def write_csv_bytes(self, data: bytes) -> None:
        path = self.csv_path()
        if path is not None:
            path.write_bytes(data)


class LoadGeneratorStatus(models.TextChoices):
    """容器化压力源（v1.2）的状态机。"""
    PENDING = 'pending', 'Pending'           # 容器刚拉起，还没注册成功
    IDLE = 'idle', 'Idle'                    # 在线、可派活
    BUSY = 'busy', 'Busy'                    # 正在执行 run
    LOST = 'lost', 'Lost'                    # 心跳超时（>90s 未上报）


class LoadGenerator(models.Model):
    """容器化压力源（v1.2 新增）。
    每台 falcon-agent 容器启动时调 POST /api/internal/agents/register 自注册一行；
    周期性 PUT /api/internal/agents/:id/heartbeat 维持 last_heartbeat_at；
    心跳超 90s 主控标 LOST，超 5min 物理删除（由后台定时任务负责）。
    Step 3 调度时由 services/scheduler.py 按 capacity（max_vusers）切片分发。"""
    pod_name = models.CharField(max_length=120, unique=True, db_index=True)
    hostname = models.CharField(max_length=120, blank=True)
    ip = models.CharField(max_length=45)              # 含 IPv6 兼容
    port = models.PositiveIntegerField(default=9100)  # agent HTTP 监听端口
    token = models.CharField(max_length=80)           # agent ↔ 主控双向 Bearer

    status = models.CharField(
        max_length=12, choices=LoadGeneratorStatus.choices,
        default=LoadGeneratorStatus.PENDING, db_index=True,
    )

    # 资源元数据（注册时自上报）
    cpu_cores = models.PositiveSmallIntegerField(default=0)
    memory_gb = models.FloatField(default=0)
    max_vusers = models.PositiveIntegerField(
        default=100,
        help_text='单台并发上限（plan 决定 100，可在 admin 调）',
    )
    jmeter_version = models.CharField(max_length=20, blank=True)
    orchestrator_type = models.CharField(
        max_length=12, default='docker',
        help_text='k8s / docker / 其他',
    )

    # 传输方式：agent=falcon-agent HTTP（v1.2 原有，K8s 用）；ssh=主控 SSH 进机器直接跑 jmeter
    # （单向网络/没法回连主控时用；无实时 InfluxDB，只有终态 JTL 分析）
    transport = models.CharField(max_length=8, default='agent', db_index=True,
                                 help_text='agent / ssh')
    ssh_user = models.CharField(max_length=64, blank=True, default='root')
    ssh_port = models.PositiveIntegerField(default=22)
    jmeter_home = models.CharField(max_length=300, blank=True,
                                   help_text='ssh 型：机器上 JMeter 目录，如 /usr/local/apache-jmeter-5.6.3')

    registered_at = models.DateTimeField(auto_now_add=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True, db_index=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = '压力机'
        verbose_name_plural = '压力机'
        ordering = ['-registered_at']

    def __str__(self) -> str:
        return f'{self.pod_name} ({self.status}, {self.ip}:{self.port})'

    @property
    def base_url(self) -> str:
        return f'http://{self.ip}:{self.port}'


class TaskRun(models.Model):
    """Task 的一次执行记录。Step 3 (v1.1) 起，由 services/executor.py 的 RunExecutor
    在子线程里编排：pre_checking → pending → running → 终态。run_id 是面向用户的
    短 uuid（运行目录名、InfluxDB tag、URL 都用它，不暴露 DB pk）。"""
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='runs')
    run_id = models.CharField(max_length=32, unique=True, db_index=True)
    status = models.CharField(
        max_length=20, choices=RunStatus.choices, default=RunStatus.PRE_CHECKING,
    )

    # pre_check 起始时刻；进度条用它作起点（覆盖到 pre_check 阶段）
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True, db_index=True)
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

    # § 12 S2：失败原因 5 类分桶（按 responseCode / failureMessage 分类，详见
    # services/jmeter_runner.py::classify_jtl_error）。结构：
    #   {'4xx': N, '5xx': N, 'assertion': N, 'timeout': N, 'connect_error': N, 'other': N}
    # 总和 ≤ 失败样本数（other 桶兜底未识别的）。run 终态填，运行中保持空 dict。
    error_breakdown = models.JSONField(default=dict, blank=True)

    error_message = models.TextField(blank=True)

    # 启动时拷贝的 Step 2 配置 + 脚本指纹快照。运行中 / 历史 run 切换时给前端做
    # "当时是这么跑的"展示；跟当前 task.thread_groups_config / task.jmx_hash 对比
    # 可以判断"配置已变化"，给用户提示。
    thread_groups_config_snapshot = models.JSONField(default=list, blank=True)
    jmx_hash_snapshot = models.CharField(max_length=64, blank=True)

    # 软删除：用户点 history dropdown 的 trash → 标 is_deleted=True，物理清 run_dir
    # + InfluxDB 数据；表行保留供大盘统计任务历史 run 数。默认 manager 过滤掉软删，
    # 大盘走 all_objects.filter(task=...).count()。
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    # 用户在历史 run 列表勾选「保留」：keep=True 的 run 目录永不被 cleanup_old_runs
    # 自动清理（未勾选的超 settings.RUN_RETENTION_DAYS 天才删）；DB 分析行始终保留。
    keep = models.BooleanField(default=False, db_index=True)
    # 历史基准：每 task 单选一个 run 作版本对比基线（BaselineVersionBar 用）。
    # set-baseline 端点设 true 时会清掉同 task 其它 run 的该标记。
    is_baseline = models.BooleanField(default=False, db_index=True)

    objects = TaskRunManager()
    all_objects = models.Manager()

    # Step 3 子进程编排相关
    pre_check_log = models.TextField(blank=True)
    # falcon 层运行事件日志（spawn jmeter / cancel 信号 / 超时兜底 / 分布式调度 /
    # 终态决策等）。每行 `HH:MM:SS.mmm | LEVEL | message` 由 executor._append_runtime_log
    # 追加。JMeter 子进程自己的 stdout/log 仍在 runs/<run_id>/jmeter.log。
    runtime_log = models.TextField(blank=True)
    pid = models.PositiveIntegerField(null=True, blank=True)
    stop_port = models.PositiveIntegerField(null=True, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    cancel_requested_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    # v1.2 容器化压力源：这次 run 用了哪几台 agent（多机调度后按 host tag 切指标）
    load_generators = models.ManyToManyField(
        LoadGenerator, blank=True, related_name='runs',
    )

    class Meta:
        verbose_name = '执行记录'
        verbose_name_plural = '执行记录'
        ordering = ['-started_at']
        constraints = [
            # 同 task 同时只允许一个非终态 run；第二次 INSERT 会撞约束 → views 转 409
            UniqueConstraint(
                fields=['task'],
                condition=Q(status__in=[
                    'pre_checking', 'pending', 'running', 'cancelling',
                ]),
                name='unique_active_run_per_task',
            ),
        ]

    def __str__(self) -> str:
        return f'Run {self.run_id} of "{self.task.title}" [{self.status}]'

    @property
    def is_active(self) -> bool:
        return self.status in {s.value for s in ACTIVE_RUN_STATUSES}

    @property
    def is_terminal(self) -> bool:
        return self.status in {s.value for s in TERMINAL_RUN_STATUSES}


class MetricSample(models.Model):
    """TaskRun 执行过程中的时序采样点（v1 先建表，v1.1 开始写入）"""
    run = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name='samples')
    timestamp = models.DateTimeField()

    rps = models.FloatField()
    p99_ms = models.FloatField()
    error_rate = models.FloatField()
    active_users = models.PositiveIntegerField()

    class Meta:
        verbose_name = '指标采样'
        verbose_name_plural = '指标采样'
        ordering = ['timestamp']
        indexes = [models.Index(fields=['run', 'timestamp'])]


class BackendListenerConfig(models.Model):
    """
    Backend Listener 全局配置（singleton，pk=1）。

    压测时 build_run_xml 会把此配置注入到所有任务的 JMX 内存版——效果等同于
    每个测试计划末尾都有一个 BackendListener，不需要在脚本里手动添加。

    编辑走 Django admin（/admin/performance/backendlistenerconfig/）；
    前端不暴露此配置。
    """
    enabled = models.BooleanField(
        default=False,
        help_text='开关：压测时是否在所有任务的 JMX 中注入 Backend Listener。'
                  '关闭时此配置不生效，脚本里原有的 BackendListener 也会被过滤掉不显示。',
    )
    influxdb_url = models.CharField(
        max_length=500, blank=True,
        help_text='InfluxDB 写入地址，例：http://10.0.0.1:8086/write?db=jmeter。'
                  '留空时即使 enabled=True 也不注入。',
    )
    classname = models.CharField(
        max_length=300,
        default='org.apache.jmeter.visualizers.backend.influxdb.InfluxdbBackendListenerClient',
        help_text='Backend 实现类全名。InfluxDB 用默认值；Graphite 换成 '
                  'org.apache.jmeter.visualizers.backend.graphite.GraphiteBackendListenerClient。',
    )
    application = models.CharField(
        max_length=100, blank=True,
        help_text='应用标识，作为 InfluxDB tag 区分不同应用的压测数据，例：user-service。',
    )
    measurement = models.CharField(
        max_length=100, default='jmeter',
        help_text='InfluxDB measurement 名（即表名），默认 jmeter。',
    )
    extra_args = models.JSONField(
        default=dict, blank=True,
        help_text='额外参数（JSON 对象），key=参数名 value=参数值。'
                  '例：{"percentiles":"90|95|99","summaryOnly":"false","testTitle":"我的压测"}。',
    )

    class Meta:
        verbose_name = '后端监听器配置'
        verbose_name_plural = '后端监听器配置'

    def __str__(self) -> str:
        status = '已启用' if self.enabled else '已禁用'
        return f'Backend Listener 全局配置（{status}）'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_config(cls) -> 'BackendListenerConfig':
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class RunEventType(models.TextChoices):
    """§ 12 关键事件锚点 enum。TextChoices 用 string 不用 int，新加值零 migration。

    分两类语义：
    - **phase 边界**（ramp_done / hold_start / shutdown_start / first_sample）：
      靠进度条 5 段染色（pre_check / startup_wait / ramp / steady / cool_down）表达；
      前端可选择不画圆点（避免跟染色边界重复）。
    - **突发/告警事件**（first_error / first_5xx / error_rate_breached /
      p99_sla_breached）：用色块/圆点画在进度条上，hover 看时刻。
    """
    # phase 边界
    RAMP_DONE = 'ramp_done', 'ramp 完成（所有 vu 起来）'
    HOLD_START = 'hold_start', 'hold 开始（稳态期）'
    SHUTDOWN_START = 'shutdown_start', 'shutdown 开始'
    FIRST_SAMPLE = 'first_sample', '首条 sample 落地（JMeter 真正开跑）'
    # 突发/告警
    FIRST_ERROR = 'first_error', '第一次出现错误'
    FIRST_5XX = 'first_5xx', '第一次出现 5xx 服务端错误'
    ERROR_RATE_BREACHED = 'error_rate_breached', '错误率破阈值'
    P99_SLA_BREACHED = 'p99_sla_breached', 'P99 破 SLA'
    THROUGHPUT_PLATEAU = 'throughput_plateau', '吞吐拐点（加 VU 但 RPS 不涨）'


class RunEventAnchor(models.Model):
    """§ 12 S1：run 期间的关键事件锚点（v1.3）。

    AI 看时序图能看出"P99 在 t=80s 跳了"，但没事件锚点 AI 推不出"这是 hold 开始的
    瞬间还是中段抖动"——event 锚点提供因果关联。

    写入路径：
    - executor 状态切换时主动写（ramp_done / hold_start / shutdown_start /
      error_rate_breached）
    - _on_finish 扫 InfluxDB 一次性补录（first_error / p99_sla_breached）

    前端 TrendsLayout / 焦点图按 ts_ms 在时间轴上画 markLine + 文字标注。
    生命周期：与 run 一起 cascade（FK on_delete=CASCADE）。
    """
    run = models.ForeignKey('TaskRun', on_delete=models.CASCADE, related_name='event_anchors')
    event_type = models.CharField(
        max_length=40, choices=RunEventType.choices,
        help_text='事件类型；按 RunEventType TextChoices 取值。',
    )
    ts_ms = models.BigIntegerField(help_text='事件时刻（ms epoch）；与 InfluxDB 时序对齐。')
    metadata = models.JSONField(
        default=dict, blank=True,
        help_text='额外参数，例：error_rate_breached → {"threshold":0.8,"actual":0.95}；'
                  'p99_sla_breached → {"sla_ms":500,"actual_ms":680}。',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = '运行事件锚点'
        verbose_name_plural = '运行事件锚点'
        ordering = ['ts_ms']
        indexes = [
            models.Index(fields=['run', 'event_type']),
            models.Index(fields=['run', 'ts_ms']),
        ]

    def __str__(self) -> str:
        return f'{self.run_id}/{self.event_type}@{self.ts_ms}'


class PinpointConfig(models.Model):
    """Pinpoint 接入全局配置（v1.3，singleton pk=1）。

    run 终态时 pinpoint_collector 检查 enabled 决定是否调 Pinpoint API；禁用时
    整个流程 skip，前端 TracePanelsTab 显示"未启用 Pinpoint"占位。

    编辑走 admin（/admin/performance/pinpointconfig/），前端不暴露。

    设计模式参考 BackendListenerConfig（同一项目内 singleton 一致写法）。
    """
    enabled = models.BooleanField(
        default=False,
        help_text='开关：run 终态时是否调 Pinpoint API 拉慢 trace。'
                  '关闭时 pinpoint_collector 立即返回，TracePanelsTab 显示占位。',
    )
    base_url = models.CharField(
        max_length=500, blank=True,
        help_text='Pinpoint Web 服务 URL，例：http://pinpoint.internal.com:8079。'
                  '留空时即使 enabled=True 也跳过。',
    )
    auth_token = models.CharField(
        max_length=500, blank=True,
        help_text='Bearer token（按客户实际鉴权方式调整）。客户内网无鉴权时留空。',
    )
    request_timeout_sec = models.IntegerField(
        default=10,
        help_text='HTTP 请求超时秒数；超时后该次 collect 静默失败，不污染 run 状态。',
    )

    class Meta:
        verbose_name = 'Pinpoint 全局配置'
        verbose_name_plural = 'Pinpoint 全局配置'

    def __str__(self) -> str:
        status = '已启用' if self.enabled else '已禁用'
        return f'Pinpoint 全局配置（{status}）'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_config(cls) -> 'PinpointConfig':
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class RunPinpointTrace(models.Model):
    """run 终态拉到的 Pinpoint 慢 trace 元数据（v1.3）。

    span tree 不存（体积太大），只存定位信息——前端表格展示 + 点击外链跳到 Pinpoint
    原生界面看 span tree。

    采样规则（pinpoint_collector）：elapsed_ms > P99 阈值（来自 InfluxDB）的 trace
    100% 留；正常 trace 不存。每 service 默认 limit=100。

    生命周期：与 baseline run 90 天保留期对齐（§ 4.4 #7），cleanup 任务一并清。
    """
    run = models.ForeignKey('TaskRun', on_delete=models.CASCADE, related_name='pinpoint_traces')
    service_name = models.CharField(max_length=100, help_text='对应 task.service_names 中的服务名。')
    trace_id = models.CharField(max_length=200, help_text='Pinpoint transaction ID。')
    elapsed_ms = models.IntegerField(help_text='整 trace 总耗时（ms）。')
    start_ts_ms = models.BigIntegerField(help_text='trace 起始时刻（ms epoch）。')
    exception_type = models.CharField(
        max_length=200, blank=True,
        help_text='Pinpoint 标识的异常类型（如 java.net.SocketTimeoutException），无异常留空。',
    )
    pinpoint_detail_url = models.CharField(
        max_length=1000, blank=True,
        help_text='Pinpoint 原生 transactionInfo 详情页 URL，前端外链跳转看 span tree。',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Pinpoint 慢调用'
        verbose_name_plural = 'Pinpoint 慢调用'
        ordering = ['-elapsed_ms']
        constraints = [
            models.UniqueConstraint(
                fields=['run', 'trace_id'],
                name='unique_pinpoint_trace_per_run',
            ),
        ]
        indexes = [
            models.Index(fields=['run', 'service_name']),
        ]

    def __str__(self) -> str:
        return f'{self.service_name} / {self.trace_id} / {self.elapsed_ms}ms'


class Service(models.Model):
    """
    被压测的服务（v1.3 落地，替代前端 servicesMock.ts）。

    Step 2 的 Task.service_names 多选基于 Service.name 做反查；Step 3 的
    ServicePanelsTab / TraceTab / JVM tab 拿 Service.grafana_panels 嵌入 iframe。

    grafana_panels 用 JSONField 存 [{name, url, type}, ...]，type ∈
    'service' / 'trace' / 'jvm'，前端按 type 分到不同 tab 展示。

    创建/编辑走 admin（/admin/performance/service/），前端只读。
    v1.4 接 Grafana HTTP API 拉 metric 序列时再扩 grafana_url 字段（已预留）。
    """
    name = models.CharField(max_length=100, unique=True, help_text='服务名，task.service_names 引用此值。')
    description = models.TextField(blank=True, help_text='服务说明。')
    base_url = models.CharField(max_length=500, blank=True, help_text='服务对外地址（仅展示）。')
    grafana_url = models.CharField(
        max_length=500, blank=True,
        help_text='Grafana dashboard 根 URL（兜底，没配 grafana_panels 时用）。'
                  '后端 v1.4 query Grafana HTTP API 时也用这个根 URL。',
    )
    pinpoint_app = models.CharField(max_length=100, blank=True, help_text='Pinpoint application name。')
    arthus_endpoint = models.CharField(
        max_length=500, blank=True,
        help_text='Arthas tunnel endpoint（v1.5 接入用，当前 placeholder）。',
    )
    grafana_panels = models.JSONField(
        default=list, blank=True,
        help_text='Grafana panel 列表，每项 {"name": ..., "url": ..., "type": "service"|"trace"|"jvm"}。'
                  'service → 服务面板 tab；trace → 链路面板 tab；jvm → JVM tab（v1 dump 按钮 disabled）。',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '被压测服务'
        verbose_name_plural = '被压测服务'
        ordering = ['name']

    def __str__(self) -> str:
        return self.name


# ── 终态分析数据(2026-05 资源治理)──────────────────────────────────────────
# 跑完后台一次扫 JTL,把分析数据抽进下面 3 张表,然后删 errors.xml(数据已入库)。
# 显示 / 查历史全走 DB,不再依赖原始文件还在不在(results.jtl 只留供按需生成原生报告)。
# 字段命名对齐前端 TS 类型(SamplerStat / ErrorAggregateRow / ConcurrencyResponse 等),
# 序列化形状跟原文件扫描端点完全一致 → 前端显示组件零改动。

class RunSamplerStat(models.Model):
    """接口级统计,一个 run 的每个 sampler 一行(对齐前端 SamplerStat)。"""
    run = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name='sampler_stats')
    label = models.CharField(max_length=255)
    total = models.PositiveIntegerField(default=0)
    success = models.PositiveIntegerField(default=0)
    error = models.PositiveIntegerField(default=0)
    avg_ms = models.FloatField(default=0)
    min_ms = models.FloatField(default=0)
    max_ms = models.FloatField(default=0)
    p50_ms = models.FloatField(default=0)
    p90_ms = models.FloatField(default=0)
    p99_ms = models.FloatField(default=0)
    avg_rps = models.FloatField(default=0)
    avg_bytes = models.FloatField(default=0)
    top_errors = models.JSONField(default=list, blank=True)  # [{reason, count}, ...]

    class Meta:
        indexes = [models.Index(fields=['run'])]
        constraints = [
            models.UniqueConstraint(fields=['run', 'label'], name='uniq_run_sampler'),
        ]


class RunErrorAggregate(models.Model):
    """错误明细聚合,一个 run 的每个 (response_code, label) 一行(对齐前端 ErrorAggregateRow)。

    sample_response_body 是从 errors.xml 抽的代表 body(每组一条够用,用户确认);抽完
    errors.xml 即删。
    """
    run = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name='error_aggregates')
    response_code = models.CharField(max_length=255)
    label = models.CharField(max_length=255)
    count = models.PositiveIntegerField(default=0)
    sample_message = models.TextField(blank=True)
    sample_failure_message = models.TextField(blank=True)
    sample_url = models.TextField(blank=True)
    sample_response_body = models.TextField(blank=True)  # 截断 ≤500 字

    class Meta:
        indexes = [models.Index(fields=['run'])]
        constraints = [
            models.UniqueConstraint(
                fields=['run', 'response_code', 'label'], name='uniq_run_err_agg',
            ),
        ]


class RunAnalysis(models.Model):
    """run 的时序分析(并发 / 延迟拆解 / 错误时序),JSON 存。都来自 JTL,入库后 JTL
    删了也能查历史。按秒桶 → 体积受时长约束(1 小时 run ~3600 点/series),适合 JSON。
    """
    run = models.OneToOneField(TaskRun, on_delete=models.CASCADE, related_name='analysis')
    # {overall: [[ts,n]], by_tg: {name: [[ts,n]]}}
    concurrency = models.JSONField(default=dict, blank=True)
    # {connect_ms, server_ms, receive_ms: [[ts,ms]]}
    latency_breakdown = models.JSONField(default=dict, blank=True)
    # {4xx, 5xx, assertion, timeout, connect_error, other: [[ts,count]]}
    error_breakdown_ts = models.JSONField(default=dict, blank=True)
    # 真·每秒整体延迟分位(从 JTL 重算,替代 InfluxDB 跨 agent 平均预聚合分位的虚高):
    # {p50_ms,p95_ms,p99_ms, p50_ok_ms,p95_ok_ms,p99_ok_ms: [[ts,ms]]}
    latency_overall = models.JSONField(default=dict, blank=True)
    # Step 4「AI 分析」结果缓存：同一 run 不重复烧 token。重新生成会覆盖。
    ai_summary = models.TextField(blank=True, default='')
    ai_summary_meta = models.JSONField(default=dict, blank=True)  # {model, scenarios, generated_at}
    created_at = models.DateTimeField(auto_now_add=True)


class RunServiceDiagnosis(models.Model):
    """run 终态时,每个被压测服务的「服务诊断」数据快照(JSON):服务拓扑 / Pinpoint 详情 /
    Pod 时序。历史 run 直接读这里(秒开,不再慢吞吞实时拉 Pinpoint),读不到/出错再回退实时
    连接。与 run 一起 cascade —— 用户删 run 即物理删这些快照(数据全在 DB,无文件)。
    """
    run = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name='service_diagnoses')
    service = models.CharField(max_length=200)
    servermap = models.JSONField(default=dict, blank=True)    # ServerMapResponse(单服务,深度2)
    diagnosis = models.JSONField(default=dict, blank=True)    # DiagnosisResponse(全量)
    prometheus = models.JSONField(default=dict, blank=True)   # PrometheusMetricsResponse(Pod 时序)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['run', 'service'],
                                    name='unique_run_service_diagnosis'),
        ]

    def __str__(self) -> str:
        return f'{self.run.run_id}/{self.service}'


class RunArthasCapture(models.Model):
    """Step 3 Arthas 诊断输出留存：用户在 Arthas 里跑某命令（dashboard/thread/jvm/trace…）
    拿到的关键问题数据，按 run + service 存下来，供 Step 4 分析进一步确诊。

    网页终端接入前的过渡用法：用户在脚本终端里跑 arthas，把关键输出粘贴进来保存；
    接入后由前端自动抓取命令输出落库。与 run cascade（run 删则连带删）。
    """
    run = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name='arthas_captures')
    service = models.CharField(max_length=200, blank=True)
    pod = models.CharField(max_length=200, blank=True)       # 哪个 pod/agent 抓的
    command = models.CharField(max_length=300)               # 如 dashboard / thread -n 3 / jvm
    output = models.TextField()                              # arthas 输出文本
    note = models.CharField(max_length=300, blank=True)      # 备注 / 自动标的问题（如「Full GC 频繁」）
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']

    def __str__(self) -> str:
        return f'{self.run.run_id}/{self.service}/{self.command}'


class PrometheusDataSource(models.Model):
    """Prometheus 数据源配置（多条记录，每条对应一个集群 / 命名空间）。

    Step 2 从选定的数据源拉服务列表（job names），
    Step 3 根据 task.service_names 查这些服务的监控指标。

    创建/编辑走 Django admin（/admin/performance/prometheusdatasource/）。
    """
    name = models.CharField(
        max_length=100, unique=True,
        help_text='数据源名称，如 ali-k8s-new、ali-k8s-online。',
    )
    url = models.CharField(
        max_length=500,
        help_text='Prometheus 兼容 API 根地址（到 /api/v1 之前的部分）。'
                  '阿里云 ARMS 示例：https://cn-hangzhou.arms.aliyuncs.com:9443/api/v1/prometheus/xxx/cn-hangzhou',
    )
    auth_token = models.CharField(
        max_length=500, blank=True,
        help_text='Bearer token（内网免认证时留空）。',
    )
    enabled = models.BooleanField(
        default=True,
        help_text='禁用后前端不展示该数据源。',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Prometheus 数据源'
        verbose_name_plural = 'Prometheus 数据源'
        ordering = ['name']

    def __str__(self) -> str:
        return f'{self.name}（{"启用" if self.enabled else "禁用"}）'


class TaskScheduleType(models.TextChoices):
    ONCE = 'once', '一次性'
    RECURRING = 'recurring', '周期性'


class TaskSchedule(models.Model):
    """定时压测任务（后台调度）。到点由 `manage.py run_due_schedules` 命令 HTTP 触发
    web 的 run 接口起 RunExecutor —— executor 线程必须活在长驻 web 进程里，故走 HTTP
    而非命令进程直接 start()（命令一退线程就死=孤儿）。"""
    name = models.CharField(max_length=120, help_text='定时任务名称')
    task = models.ForeignKey(
        'Task', on_delete=models.CASCADE, related_name='schedules',
        help_text='要定时跑的压测任务（须已完成 Step 2 配置）',
    )
    schedule_type = models.CharField(
        max_length=12, choices=TaskScheduleType.choices,
        default=TaskScheduleType.ONCE, help_text='一次性 / 周期性',
    )
    run_at = models.DateTimeField(
        null=True, blank=True, help_text='【一次性】执行的日期时间',
    )
    cron = models.CharField(
        max_length=120, blank=True,
        help_text='【周期性】cron 表达式（5 段，按 Asia/Shanghai 时区）。'
                  '例：0 2 * * * = 每天凌晨 2 点；*/30 * * * * = 每 30 分钟；0 9 * * 1 = 每周一 9 点',
    )
    load_generators = models.ManyToManyField(
        'LoadGenerator', blank=True,
        help_text='用哪些压力机跑（留空 = 主控本机直跑 LOCAL_FALLBACK）',
    )
    enabled = models.BooleanField(default=True, help_text='禁用后不再触发')
    next_run_at = models.DateTimeField(
        null=True, blank=True, db_index=True,
        help_text='下次触发时间（保存时自动算，调度单一真相）',
    )
    last_triggered_at = models.DateTimeField(null=True, blank=True)
    last_run = models.ForeignKey(
        'TaskRun', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+', help_text='最近一次触发创建的 run',
    )
    last_error = models.TextField(blank=True, help_text='最近一次触发失败原因')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '定时任务'
        verbose_name_plural = '定时任务'
        ordering = ['-created_at']

    def __str__(self) -> str:
        return f'{self.name}（{self.get_schedule_type_display()}）'

    def compute_next_run(self, base=None):
        """算下次触发时间。
        - 一次性：只在还没触发过时返回 run_at，否则 None（不重复）。
        - 周期性：按 Asia/Shanghai 本地时间算 cron 的下一个点（避免 UTC 错位）。
        """
        from django.utils import timezone as _tz  # noqa: PLC0415
        import datetime as _dt  # noqa: PLC0415
        base = base or _tz.now()
        if self.schedule_type == TaskScheduleType.ONCE:
            return self.run_at if (self.run_at and not self.last_triggered_at) else None
        if not self.cron:
            return None
        from croniter import croniter  # noqa: PLC0415
        try:
            # 用本地时区算，cron 的 "2 点" = Asia/Shanghai 的 2 点
            local_base = _tz.localtime(base)
            return croniter(self.cron, local_base).get_next(_dt.datetime)
        except (ValueError, KeyError):
            return None

    def save(self, *args, **kwargs):
        # 创建 / 改配置时重算 next_run_at；禁用则清空（不触发）
        self.next_run_at = self.compute_next_run() if self.enabled else None
        super().save(*args, **kwargs)
