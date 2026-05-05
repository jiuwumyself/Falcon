"""Step 3 (v1.1) TaskRun 字段扩展 + 状态枚举扩展 + 唯一约束 + fail→failed 重命名。

v1 阶段 TaskRun 表通常无数据；本迁移仍兜底处理已存在行的 run_id 填充和
fail→failed 状态值改名。
"""
import secrets

from django.db import migrations, models
from django.db.models import Q


def _populate_run_id_and_rename_fail(apps, schema_editor):
    TaskRun = apps.get_model('performance', 'TaskRun')
    for run in TaskRun.objects.all():
        changed = False
        if not run.run_id:
            run.run_id = secrets.token_hex(8)
            changed = True
        if run.status == 'fail':
            run.status = 'failed'
            changed = True
        if changed:
            run.save(update_fields=['run_id', 'status'])


def _reverse_rename_failed(apps, schema_editor):
    TaskRun = apps.get_model('performance', 'TaskRun')
    for run in TaskRun.objects.filter(status='failed'):
        run.status = 'fail'
        run.save(update_fields=['status'])


class Migration(migrations.Migration):

    dependencies = [
        ('performance', '0006_biz_category_add_custom'),
    ]

    operations = [
        # 1) 加新字段。run_id 先 nullable+空默认，数据迁移填好之后再升级唯一约束。
        migrations.AddField(
            model_name='taskrun',
            name='run_id',
            field=models.CharField(blank=True, default='', db_index=True, max_length=32),
        ),
        migrations.AddField(
            model_name='taskrun',
            name='pre_check_log',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='taskrun',
            name='pid',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='taskrun',
            name='stop_port',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='taskrun',
            name='last_heartbeat_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='taskrun',
            name='cancel_requested_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='taskrun',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True),
        ),

        # 2) 数据迁移：填 run_id + fail→failed
        migrations.RunPython(
            _populate_run_id_and_rename_fail,
            _reverse_rename_failed,
        ),

        # 3) status 枚举扩展（choices 在 SQLite 是 Python 层校验，AlterField 实质 SQL no-op）
        migrations.AlterField(
            model_name='taskrun',
            name='status',
            field=models.CharField(
                choices=[
                    ('pre_checking', '环境检测中'),
                    ('pre_check_failed', '环境检测失败'),
                    ('pending', '待执行'),
                    ('running', '执行中'),
                    ('cancelling', '正在停止'),
                    ('success', '成功'),
                    ('failed', '失败'),
                    ('timeout', '超时'),
                    ('cancelled', '已取消'),
                ],
                default='pre_checking',
                max_length=20,
            ),
        ),

        # 4) run_id 升级为唯一非空约束
        migrations.AlterField(
            model_name='taskrun',
            name='run_id',
            field=models.CharField(db_index=True, max_length=32, unique=True),
        ),

        # 5) 同 task 同时只允许一个非终态 run
        migrations.AddConstraint(
            model_name='taskrun',
            constraint=models.UniqueConstraint(
                fields=['task'],
                condition=Q(status__in=[
                    'pre_checking', 'pending', 'running', 'cancelling',
                ]),
                name='unique_active_run_per_task',
            ),
        ),
    ]
