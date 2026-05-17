from django.contrib import admin
from .models import MacroCategoria, Categoria, Transacao, MetaPoupanca, DespesaFixa, RegraClassificacao

@admin.register(MacroCategoria)
class MacroCategoriaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'tipo')
    list_filter = ('tipo',)
    search_fields = ('nome',)

@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'macro_categoria', 'ativo')
    list_filter = ('ativo', 'macro_categoria')
    search_fields = ('nome',)

@admin.register(Transacao)
class TransacaoAdmin(admin.ModelAdmin):
    list_display = ('descricao', 'valor', 'data', 'categoria', 'pago', 'despesa_fixa')
    list_filter = ('pago', 'data', 'categoria')
    search_fields = ('descricao',)
    raw_id_fields = ('despesa_fixa', 'categoria')

@admin.register(DespesaFixa)
class DespesaFixaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'valor_previsto', 'dia_vencimento', 'categoria', 'ativo')
    list_filter = ('ativo', 'categoria')
    search_fields = ('nome',)

@admin.register(RegraClassificacao)
class RegraClassificacaoAdmin(admin.ModelAdmin):
    list_display = ('palavra_chave', 'categoria', 'despesa_vinculada')
    search_fields = ('palavra_chave',)
    raw_id_fields = ('despesa_vinculada', 'categoria')

admin.site.register(MetaPoupanca)