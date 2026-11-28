import django.db.models.deletion
import django.utils.timezone
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('directory', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Photo',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('state', models.CharField(choices=[('STAGED', 'Staged'), ('ATTACHED', 'Attached'), ('PENDING_DELETE', 'Pending Delete')], default='STAGED', max_length=14)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('lease_until', models.DateTimeField(null=True)),
                ('byte_size', models.PositiveIntegerField(null=True)),
                ('width', models.PositiveSmallIntegerField(null=True)),
                ('height', models.PositiveSmallIntegerField(null=True)),
                ('next_attempt_at', models.DateTimeField(null=True)),
                ('attempt_count', models.PositiveIntegerField(default=0)),
                ('last_error_code', models.CharField(blank=True, max_length=32)),
            ],
            options={
                'indexes': [models.Index(fields=['state', 'lease_until', 'next_attempt_at'], name='photo_cleanup_idx')],
                'constraints': [models.CheckConstraint(condition=models.Q(('state__in', ['STAGED', 'ATTACHED', 'PENDING_DELETE'])), name='photo_state_valid'), models.CheckConstraint(condition=models.Q(models.Q(('state', 'ATTACHED'), _negated=True), models.Q(('byte_size__gte', 1), ('byte_size__isnull', False), ('byte_size__lte', 1048576), ('height__gte', 1), ('height__isnull', False), ('height__lte', 1200), ('width__gte', 1), ('width__isnull', False), ('width__lte', 1200)), _connector='OR'), name='photo_attached_metadata')],
            },
        ),
        migrations.AddField(
            model_name='entry',
            name='photo',
            field=models.OneToOneField(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, to='directory.photo'),
        ),
    ]
