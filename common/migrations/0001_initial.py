import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='FormSubmission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token_digest', models.CharField(max_length=64, unique=True)),
                ('session_scope_digest', models.CharField(max_length=64)),
                ('operation', models.CharField(max_length=40)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('consumed_at', models.DateTimeField(null=True)),
            ],
            options={
                'constraints': [models.CheckConstraint(condition=models.Q(('expires_at__gt', models.F('created_at'))), name='submission_valid_window'), models.CheckConstraint(condition=models.Q(('consumed_at__isnull', True), ('consumed_at__gte', models.F('created_at')), _connector='OR'), name='submission_consumed_after_creation')],
            },
        ),
    ]
