from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='LoginCounter',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('scope', models.CharField(choices=[('IP', 'IP'), ('IDENTIFIER_IP', 'Identificador e IP')], max_length=16)),
                ('key_digest', models.CharField(max_length=64)),
                ('window_started_at', models.DateTimeField()),
                ('expires_at', models.DateTimeField(db_index=True)),
                ('count', models.PositiveIntegerField(default=0)),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('scope', 'key_digest'), name='login_counter_scope_key_unique'), models.CheckConstraint(condition=models.Q(('scope__in', ['IP', 'IDENTIFIER_IP'])), name='login_counter_scope_valid'), models.CheckConstraint(condition=models.Q(('expires_at__gt', models.F('window_started_at'))), name='login_counter_window_valid')],
            },
        ),
    ]
