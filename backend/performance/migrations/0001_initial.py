# Rewritten 2026-04-23 from the original tasks/0001_initial.py so the
# renamed app 'performance' takes over the existing `tasks_*` tables
# without recreating them.
#
# Approach: SeparateDatabaseAndState — state_operations mirror the original
# CreateModel structure (so Django's migration graph matches the current
# models.py schema), while database_operations only rename the existing
# tables and reassign Django's bookkeeping rows (django_migrations,
# django_content_type) from app='tasks' to app='performance'.

import django.db.models.deletion
import performance.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name='Task',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('title', models.CharField(max_length=200)),
                        ('description', models.TextField(blank=True)),
                        ('biz_category', models.CharField(choices=[('shared', '共享课'), ('ai', 'AI 事业中心'), ('kg', 'KG 知识图谱')], default='shared', max_length=20)),
                        ('jmx_filename', models.CharField(blank=True, max_length=255)),
                        ('jmx_hash', models.CharField(blank=True, db_index=True, max_length=64)),
                        ('csv_file', models.FileField(blank=True, null=True, upload_to=performance.models.csv_upload_path)),
                        ('virtual_users', models.PositiveIntegerField(default=10)),
                        ('ramp_up_seconds', models.PositiveIntegerField(default=0)),
                        ('duration_seconds', models.PositiveIntegerField(default=60)),
                        ('is_deleted', models.BooleanField(db_index=True, default=False)),
                        ('deleted_at', models.DateTimeField(blank=True, null=True)),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('updated_at', models.DateTimeField(auto_now=True)),
                        ('owner', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tasks', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'ordering': ['-created_at'],
                    },
                ),
                migrations.CreateModel(
                    name='TaskRun',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('status', models.CharField(choices=[('pending', '待执行'), ('running', '执行中'), ('success', '成功'), ('fail', '失败'), ('cancelled', '已取消')], default='pending', max_length=20)),
                        ('started_at', models.DateTimeField(blank=True, null=True)),
                        ('finished_at', models.DateTimeField(blank=True, null=True)),
                        ('virtual_users', models.PositiveIntegerField()),
                        ('ramp_up_seconds', models.PositiveIntegerField(default=0)),
                        ('duration_seconds', models.PositiveIntegerField()),
                        ('total_requests', models.PositiveIntegerField(default=0)),
                        ('avg_rps', models.FloatField(default=0)),
                        ('p99_ms', models.FloatField(default=0)),
                        ('error_rate', models.FloatField(default=0)),
                        ('error_message', models.TextField(blank=True)),
                        ('task', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='runs', to='performance.task')),
                    ],
                    options={
                        'ordering': ['-started_at'],
                    },
                ),
                migrations.CreateModel(
                    name='MetricSample',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('timestamp', models.DateTimeField()),
                        ('rps', models.FloatField()),
                        ('p99_ms', models.FloatField()),
                        ('error_rate', models.FloatField()),
                        ('active_users', models.PositiveIntegerField()),
                        ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='samples', to='performance.taskrun')),
                    ],
                    options={
                        'ordering': ['timestamp'],
                        'indexes': [models.Index(fields=['run', 'timestamp'], name='tasks_metri_run_id_52b55f_idx')],
                    },
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=[
                        # Drop the old 'tasks' migration row so Django can
                        # cleanly INSERT ('performance', '0001_initial') at
                        # the end of this migration.
                        "DELETE FROM django_migrations WHERE app='tasks';",
                        "UPDATE django_content_type SET app_label='performance' WHERE app_label='tasks';",
                        "ALTER TABLE tasks_task RENAME TO performance_task;",
                        "ALTER TABLE tasks_taskrun RENAME TO performance_taskrun;",
                        "ALTER TABLE tasks_metricsample RENAME TO performance_metricsample;",
                    ],
                    reverse_sql=[
                        "ALTER TABLE performance_metricsample RENAME TO tasks_metricsample;",
                        "ALTER TABLE performance_taskrun RENAME TO tasks_taskrun;",
                        "ALTER TABLE performance_task RENAME TO tasks_task;",
                        "UPDATE django_content_type SET app_label='tasks' WHERE app_label='performance';",
                        "DELETE FROM django_migrations WHERE app='performance';",
                        "INSERT OR IGNORE INTO django_migrations (app, name, applied) VALUES ('tasks', '0001_initial', CURRENT_TIMESTAMP);",
                    ],
                ),
            ],
        ),
    ]
