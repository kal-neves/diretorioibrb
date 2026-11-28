from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Entry',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='nome')),
                ('search_name', models.CharField(editable=False, max_length=600)),
                ('category', models.CharField(choices=[('MEMBER', 'Membro'), ('PASTOR', 'Pastor'), ('DEACON', 'Diácono')], max_length=6, verbose_name='categoria')),
                ('contact_phone', models.CharField(blank=True, max_length=16, null=True, verbose_name='contato')),
                ('email', models.EmailField(blank=True, max_length=254, null=True, verbose_name='e-mail')),
                ('birth_day', models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='dia')),
                ('birth_month', models.PositiveSmallIntegerField(blank=True, null=True, verbose_name='mês')),
                ('spouse_name', models.CharField(blank=True, max_length=200, null=True, verbose_name='cônjuge')),
            ],
            options={
                'verbose_name': 'entrada do diretório',
                'verbose_name_plural': 'entradas do diretório',
                'indexes': [models.Index(fields=['birth_month', 'birth_day'], name='directory_birthday_idx')],
                'constraints': [models.CheckConstraint(condition=models.Q(('name__regex', '\\S')), name='directory_name_present'), models.CheckConstraint(condition=models.Q(('search_name__regex', '\\S')), name='directory_search_present'), models.CheckConstraint(condition=models.Q(('category__in', ['MEMBER', 'PASTOR', 'DEACON'])), name='directory_category_valid'), models.CheckConstraint(condition=models.Q(('contact_phone__isnull', True), ('contact_phone__regex', '^\\+[1-9][0-9]{1,14}$'), _connector='OR'), name='directory_phone_format'), models.CheckConstraint(condition=models.Q(models.Q(('birth_day__isnull', True), ('birth_month__isnull', True)), models.Q(('birth_day__gte', 1), ('birth_day__isnull', False), ('birth_month__isnull', False), models.Q(models.Q(('birth_day__lte', 31), ('birth_month__in', [1, 3, 5, 7, 8, 10, 12])), models.Q(('birth_day__lte', 30), ('birth_month__in', [4, 6, 9, 11])), models.Q(('birth_day__lte', 29), ('birth_month', 2)), _connector='OR')), _connector='OR'), name='directory_birthday_valid')],
            },
        ),
    ]
