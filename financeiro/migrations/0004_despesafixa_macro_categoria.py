import django.db.models.deletion
from django.db import migrations, models


def preencher_macro_categoria(apps, schema_editor):
    DespesaFixa = apps.get_model('financeiro', 'DespesaFixa')
    for despesa in DespesaFixa.objects.select_related('categoria').iterator():
        if despesa.categoria_id:
            despesa.macro_categoria_id = despesa.categoria.macro_categoria_id
            despesa.save(update_fields=['macro_categoria_id'])


class Migration(migrations.Migration):

    dependencies = [
        ('financeiro', '0003_planejamentomensal_orcamentocategoria'),
    ]

    operations = [
        migrations.AddField(
            model_name='despesafixa',
            name='macro_categoria',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='despesas_fixas',
                to='financeiro.macrocategoria',
            ),
        ),
        migrations.RunPython(preencher_macro_categoria, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='despesafixa',
            name='macro_categoria',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='despesas_fixas',
                to='financeiro.macrocategoria',
            ),
        ),
        migrations.AddIndex(
            model_name='despesafixa',
            index=models.Index(
                fields=['usuario', 'macro_categoria', 'ativo'],
                name='financeiro__usuario_8a1f2d_idx',
            ),
        ),
    ]
