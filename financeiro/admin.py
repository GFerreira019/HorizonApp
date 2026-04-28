from django.contrib import admin
from .models import Categoria, Transacao, MetaPoupanca, DespesaFixa, RegraClassificacao

@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'tipo')

@admin.register(Transacao)
class TransacaoAdmin(admin.ModelAdmin):
    list_display = ('descricao', 'valor', 'data', 'categoria', 'pago')
    list_filter = ('pago', 'categoria')

admin.site.register(MetaPoupanca)

@admin.register(DespesaFixa)
class DespesaFixaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'valor_previsto', 'dia_vencimento', 'categoria', 'ativo')
    list_filter = ('ativo', 'categoria')
    search_fields = ('nome',)

@admin.register(RegraClassificacao)
class RegraClassificacaoAdmin(admin.ModelAdmin):
    list_display = ('palavra_chave', 'categoria', 'despesa_vinculada')
    search_fields = ('palavra_chave',)