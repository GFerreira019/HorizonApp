from django.urls import path
from . import views

urlpatterns = [
    # Dashboard (Página Inicial)
    path('', views.dashboard, name='dashboard'),

    # Histórico e Gestão
    path('historico/', views.historico_transacoes, name='historico_transacoes'),
    path('editar/<int:pk>/', views.editar_transacao, name='editar_transacao'),
    path('excluir/<int:pk>/', views.excluir_transacao, name='excluir_transacao'),

    # APIs (AJAX) para o Frontend
    path('api/toggle-pago/<int:pk>/', views.toggle_pago, name='toggle_pago'),
    path('api/chart-data/', views.get_chart_data, name='get_chart_data'),

    # Exportação
    path('exportar-excel/', views.exportar_financas_excel, name='exportar_financas_excel'),

    # Importação e Auditoria
    path('importar/', views.importar_extrato, name='importar_extrato'),
    path('importar/excluir/<int:pk>/', views.excluir_lote, name='excluir_lote'),
    path('auditoria/', views.tela_auditoria, name='tela_auditoria'),
    path('auditoria/consolidar/<int:pk>/', views.consolidar_transacao_ajax, name='consolidar_transacao_ajax'),

    # Controladoria e Gastos Fixos
    path('fixos/', views.controle_gastos_fixos, name='controle_gastos_fixos'),
]