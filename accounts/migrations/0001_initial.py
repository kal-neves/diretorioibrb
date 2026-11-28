import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Account',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
                ('name', models.CharField(max_length=200, verbose_name='nome')),
                ('login_phone', models.CharField(blank=True, max_length=16, null=True, unique=True, verbose_name='celular de login')),
                ('seed_username', models.CharField(blank=True, editable=False, max_length=32, null=True, unique=True)),
                ('role', models.CharField(choices=[('CONSULTATION', 'Consulta'), ('SECRETARIAT', 'Secretaria'), ('INITIAL_ADMIN', 'Administrador inicial')], default='CONSULTATION', max_length=20, verbose_name='perfil')),
                ('is_active', models.BooleanField(default=True, verbose_name='ativa')),
                ('must_change_password', models.BooleanField(default=True, verbose_name='troca de senha obrigatória')),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('first_password_changed_at', models.DateTimeField(blank=True, editable=False, null=True)),
                ('access_version', models.PositiveBigIntegerField(default=1, editable=False)),
            ],
            options={
                'verbose_name': 'conta de acesso',
                'verbose_name_plural': 'contas de acesso',
                'indexes': [models.Index(condition=models.Q(('first_password_changed_at__isnull', True), models.Q(('role', 'INITIAL_ADMIN'), _negated=True)), fields=['created_at'], name='account_unused_created_idx')],
                'constraints': [models.CheckConstraint(condition=models.Q(('name__regex', '\\S')), name='account_name_not_blank'), models.CheckConstraint(condition=models.Q(models.Q(('is_active', True), ('login_phone__isnull', True), ('role', 'INITIAL_ADMIN'), ('seed_username', 'adminseed'), ('seed_username__isnull', False)), models.Q(('login_phone__isnull', False), ('login_phone__regex', '^\\+[1-9][0-9]{1,14}$'), ('role__in', ['CONSULTATION', 'SECRETARIAT']), ('seed_username__isnull', True)), _connector='OR'), name='account_identity_valid'), models.CheckConstraint(condition=models.Q(('access_version__gte', 1)), name='account_access_version_positive'), models.CheckConstraint(condition=models.Q(('first_password_changed_at__isnull', True), ('first_password_changed_at__gte', models.F('created_at')), _connector='OR'), name='account_first_change_after_creation'), models.CheckConstraint(condition=models.Q(('role', 'INITIAL_ADMIN'), ('first_password_changed_at__isnull', False), ('must_change_password', True), _connector='OR'), name='account_new_requires_password_change')],
            },
        ),
    ]
