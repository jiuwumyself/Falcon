"""
取消 _run.jmx 物理派生 + CSV 改为按 CSVDataSet path 绑定。

数据清理：本地调试期，迁移自动 hard-delete 全部 Task（含软删的）并清空
scripts/ 下所有文件。生产环境跑这条迁移前请人工评估。
"""
from pathlib import Path

import django.db.models.deletion
from django.db import migrations, models


def _scripts_dir() -> Path | None:
    """Resolve scripts/ at runtime (apps registry won't help here)."""
    try:
        from performance.services.jmeter import get_scripts_dir  # noqa: PLC0415
        return get_scripts_dir()
    except Exception:
        return None


def hard_delete_all(apps, schema_editor):
    """Wipe every Task row (incl. soft-deleted) and physically clean scripts/."""
    Task = apps.get_model('performance', 'Task')
    Task.objects.all().delete()  # default manager is plain in migrations

    scripts = _scripts_dir()
    if scripts and scripts.exists():
        for child in scripts.iterdir():
            if child.is_file() and child.suffix.lower() in ('.jmx', '.csv'):
                child.unlink(missing_ok=True)


def noop(apps, schema_editor):
    """Reverse migration: nothing to do — data already gone."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('performance', '0003_environment_task_run_jmx_filename_and_more'),
    ]

    operations = [
        # 1) Wipe data + physical files BEFORE dropping columns
        migrations.RunPython(hard_delete_all, noop),

        # 2) Drop legacy fields
        migrations.RemoveField(
            model_name='task',
            name='run_jmx_filename',
        ),
        migrations.RemoveField(
            model_name='task',
            name='csv_filename',
        ),

        # 3) Add new TaskCsvBinding table
        migrations.CreateModel(
            name='TaskCsvBinding',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('component_path', models.CharField(max_length=64)),
                ('filename', models.CharField(max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('task', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='csv_bindings', to='performance.task')),
            ],
            options={
                'ordering': ['component_path'],
                'unique_together': {('task', 'component_path')},
            },
        ),
    ]
