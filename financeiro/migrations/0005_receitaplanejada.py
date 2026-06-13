# Generated manually for ReceitaPlanejada

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0004_despesafixa_macro_categoria'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ReceitaPlanejada',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(help_text='Ex: Salário CLT, Freelance', max_length=100)),
                ('valor_previsto', models.DecimalField(decimal_places=2, max_digits=10)),
                ('dia_recebimento', models.PositiveIntegerField(default=1, help_text='Dia do mês (1 a 31)')),
                ('ativo', models.BooleanField(default=True)),
                ('data_inicio', models.DateField(default=django.utils.timezone.now)),
                ('data_fim', models.DateField(blank=True, null=True)),
                ('categoria', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='receitas_planejadas_vinculadas', to='financeiro.categoria')),
                ('macro_categoria', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='receitas_planejadas', to='financeiro.macrocategoria')),
                ('usuario', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='receitas_planejadas', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Receita Planejada',
                'verbose_name_plural': 'Receitas Planejadas',
                'ordering': ['dia_recebimento', 'nome'],
            },
        ),
        migrations.AddIndex(
            model_name='receitaplanejada',
            index=models.Index(fields=['usuario', 'macro_categoria', 'ativo'], name='financeiro__usuario_8a1f2c_idx'),
        ),
    ]
