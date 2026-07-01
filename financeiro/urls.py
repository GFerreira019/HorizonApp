from django.urls import path
from django.views.generic import RedirectView, TemplateView
from . import views

urlpatterns = [
    # PWA
    path('manifest.json', TemplateView.as_view(template_name='manifest.json', content_type='application/json'), name='manifest'),
    path('sw.js', TemplateView.as_view(template_name='sw.js', content_type='application/javascript'), name='sw'),

    # Dashboard (Página Inicial)
    path('', views.dashboard, name='dashboard'),

    # Histórico e Gestão
    path('historico/', views.historico_transacoes, name='historico_transacoes'),
    path('editar/<int:pk>/', views.editar_transacao, name='editar_transacao'),
    path('excluir/<int:pk>/', views.excluir_transacao, name='excluir_transacao'),

    # APIs (AJAX) para o Frontend
    path('api/excluir/<int:pk>/', views.excluir_transacao_ajax, name='excluir_transacao_ajax'),
    path('api/toggle-pago/<int:pk>/', views.toggle_pago, name='toggle_pago'),
    path('api/chart-data/', views.get_chart_data, name='get_chart_data'),
    path('api/reclassificar/', views.reclassificar_transacao_ajax, name='reclassificar_transacao_ajax'),
    path('api/atualizar-saldo/', views.atualizar_saldo_livre_ajax, name='atualizar_saldo_livre_ajax'),

    # Exportação
    path('exportar-excel/', views.exportar_financas_excel, name='exportar_financas_excel'),

    # Hub de Integrações (Open Finance + CSV) — antiga rota /importar/
    path('integracoes/', views.integracoes, name='integracoes'),
    path('integracoes/excluir-lote/<int:pk>/', views.excluir_lote, name='excluir_lote'),
    # Integração Telegram
    path('telegram/conectar/', views.conectar_telegram, name='conectar_telegram'),
    path('telegram/desconectar/', views.desconectar_telegram, name='desconectar_telegram'),
    # Redirect de retrocompatibilidade: /importar/ → /integracoes/
    path('importar/', RedirectView.as_view(pattern_name='integracoes', permanent=True), name='importar_extrato'),
    path('auditoria/', views.tela_auditoria, name='tela_auditoria'),
    path('auditoria/consolidar/<int:pk>/', views.consolidar_transacao_ajax, name='consolidar_transacao_ajax'),

    # Controladoria e Gastos Fixos
    path('fixos/', views.controle_gastos_fixos, name='controle_gastos_fixos'),

    # API para buscar transações (filtro avançado)
    path('api/buscar-transacoes/', views.buscar_transacoes_ajax, name='buscar_transacoes_ajax'),

    # Cadastrar, Detalhes, Edição e Exclusão de Gastos Fixos
    path('fixos/cadastrar/', views.cadastrar_despesa_fixa_direta, name='cadastrar_despesa_fixa_direta'),
    path('fixos/<int:pk>/detalhes/', views.detalhes_despesa_fixa_ajax, name='detalhes_despesa_fixa'),
    path('fixos/<int:pk>/editar/', views.editar_despesa_fixa, name='editar_despesa_fixa'),
    path('fixos/<int:pk>/excluir/', views.excluir_despesa_fixa, name='excluir_despesa_fixa'),
    path('fixos/desvincular/<int:pk>/', views.desvincular_transacao_ajax, name='desvincular_transacao_ajax'),

    # Receitas planejadas (Planejamento)
    path('receitas-planejadas/cadastrar/', views.cadastrar_receita_planejada, name='cadastrar_receita_planejada'),
    path('receitas-planejadas/<int:pk>/detalhes/', views.detalhes_receita_planejada_ajax, name='detalhes_receita_planejada'),
    path('receitas-planejadas/<int:pk>/editar/', views.editar_receita_planejada, name='editar_receita_planejada'),
    path('receitas-planejadas/<int:pk>/excluir/', views.excluir_receita_planejada, name='excluir_receita_planejada'),
    path('receitas-planejadas/desvincular/<int:pk>/', views.desvincular_transacao_receita_ajax, name='desvincular_transacao_receita'),

    # Planejamento Mensal
    path('planejamento/', views.tela_planejamento, name='tela_planejamento'),

    # Quick Add — Lançamento avulso de provisionamento (AJAX)
    path('api/quick-add-provisionamento/', views.quick_add_provisionamento_ajax, name='quick_add_provisionamento_ajax'),

    # Gerenciamento de Categorias (AJAX)
    path('categorias/criar/', views.criar_categoria_ajax, name='criar_categoria_ajax'),
    path('categorias/<int:pk>/editar/', views.editar_categoria_ajax, name='editar_categoria_ajax'),
    path('categorias/<int:pk>/excluir/', views.excluir_categoria_ajax, name='excluir_categoria_ajax'),

    # Limites Temporários de Gastos
    path('limites-temporarios/cadastrar/', views.cadastrar_limite_temporario, name='cadastrar_limite_temporario'),
    path('limites-temporarios/<int:pk>/desativar/', views.desativar_limite_temporario, name='desativar_limite_temporario'),

    # Perfil e Configurações
    path('configuracoes/', views.tela_configuracoes, name='tela_configuracoes'),

    # Open Finance — APIs AJAX (a página foi incorporada ao hub /integracoes/)
    path('api/open-finance/gerar-token/', views.gerar_token_pluggy, name='gerar_token_pluggy'),
    path('api/open-finance/salvar-conexao/', views.salvar_conexao_bancaria_ajax, name='salvar_conexao_bancaria_ajax'),
    path('api/open-finance/sincronizar/<int:pk>/', views.sincronizar_conexao_ajax, name='sincronizar_conexao_ajax'),
]