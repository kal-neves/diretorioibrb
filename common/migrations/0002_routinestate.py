from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('common', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='RoutineState',
            fields=[
                ('key', models.CharField(max_length=40, primary_key=True, serialize=False)),
                ('run_token', models.UUIDField(null=True)),
                ('lease_until', models.DateTimeField(null=True)),
                ('last_started_at', models.DateTimeField(null=True)),
                ('last_succeeded_at', models.DateTimeField(null=True)),
                ('status', models.CharField(default='pending', max_length=16)),
                ('counts', models.JSONField(default=dict)),
                ('last_error_code', models.CharField(blank=True, max_length=40)),
            ],
        ),
    ]
