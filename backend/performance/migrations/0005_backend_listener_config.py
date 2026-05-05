from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('performance', '0004_drop_run_jmx_csv_add_csv_binding'),
    ]

    operations = [
        migrations.CreateModel(
            name='BackendListenerConfig',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('enabled', models.BooleanField(default=False, help_text='开关：压测时是否在所有任务的 JMX 中注入 Backend Listener。关闭时此配置不生效，脚本里原有的 BackendListener 也会被过滤掉不显示。')),
                ('influxdb_url', models.CharField(blank=True, help_text='InfluxDB 写入地址，例：http://10.0.0.1:8086/write?db=jmeter。留空时即使 enabled=True 也不注入。', max_length=500)),
                ('classname', models.CharField(default='org.apache.jmeter.visualizers.backend.influxdb.InfluxdbBackendListenerClient', help_text='Backend 实现类全名。InfluxDB 用默认值；Graphite 换成 org.apache.jmeter.visualizers.backend.graphite.GraphiteBackendListenerClient。', max_length=300)),
                ('application', models.CharField(blank=True, help_text='应用标识，作为 InfluxDB tag 区分不同应用的压测数据，例：user-service。', max_length=100)),
                ('measurement', models.CharField(default='jmeter', help_text='InfluxDB measurement 名（即表名），默认 jmeter。', max_length=100)),
                ('extra_args', models.JSONField(blank=True, default=dict, help_text='额外参数（JSON 对象），key=参数名 value=参数值。例：{"percentiles":"90|95|99","summaryOnly":"false","testTitle":"我的压测"}。')),
            ],
            options={
                'verbose_name': 'Backend Listener 全局配置',
                'verbose_name_plural': 'Backend Listener 全局配置',
            },
        ),
    ]
