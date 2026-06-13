import json
import logging
import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.urls import reverse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q
from django.utils import timezone

from financeiro.signals import ICONES_MACRO

# Imports locais
from .services import processar_extrato_nubank, sincronizar_transacoes_open_finance, PluggyAPIClient
from .models import (
    Transacao,
    Categoria,
    MacroCategoria,
    RegraClassificacao,
    LoteImportacao,
    DespesaFixa,
    ReceitaPlanejada,
    PlanejamentoMensal,
    OrcamentoCategoria,
    LimiteTemporario,
    PerfilUsuario,
    ConexaoBancaria,
)
from .forms import (
    DespesaFixaForm, ReceitaPlanejadaForm, TransacaoForm, LimiteTemporarioForm,
    UsuarioForm, PerfilUsuarioForm,
)

logger = logging.getLogger(__name__)


def _sync_conexao_em_background(conexao_pk: int) -> None:
    """
    Worker que executa a sincronização de uma ConexaoBancaria em uma thread separada.

    Projetado para ser chamado via `threading.Thread(target=..., daemon=True)` a partir
    de `salvar_conexao_bancaria_ajax`, de modo que o response ao browser seja imediato
    enquanto as transações são importadas em background.

    Nota: em produção, o ideal é migrar para Celery. Esta abordagem com thread é adequada
    para o MVP e no máximo 1-2 segundos de latencia extra na thread de sync é imperceptivel.
    """
    try:
        conexao = ConexaoBancaria.objects.get(pk=conexao_pk)
        sincronizar_transacoes_open_finance(conexao=conexao)
        logger.info('Sync em background concluída para conexão pk=%s', conexao_pk)
    except ConexaoBancaria.DoesNotExist:
        logger.error('Conexão pk=%s não encontrada para sync em background.', conexao_pk)
    except Exception as exc:
        logger.error('Erro na sync em background da conexão pk=%s: %s', conexao_pk, exc)


def _redirect_pos_fixo(request: HttpRequest, default_view: str = 'controle_gastos_fixos') -> HttpResponse:
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url and next_url.startswith('/') and not next_url.startswith('//'):
        return redirect(next_url)
    return redirect(default_view)


# ==============================================================================
# 1. DASHBOARD E OPERAÇÃO PRINCIPAL
# ==============================================================================

@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """
    Visão central do aplicativo, onde o usuário tem um panorama geral do seu fluxo de caixa.
    """
    today = date.today()
    MESES_PT = {
        1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril', 5: 'Maio', 6: 'Junho',
        7: 'Julho', 8: 'Agosto', 9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
    }
    user = request.user
    
    periodo = request.GET.get('periodo')
    mes_param = request.GET.get('mes')
    ano_param = int(request.GET.get('ano', today.year))
    
    query_filtro = Q(usuario=user)
    periodo_tudo = False
    
    if periodo == 'tudo':
        filtro_ativo = "Todo o Período"
        periodo_tudo = True
        mes = today.month 
    elif mes_param:
        mes = int(mes_param)
        query_filtro &= Q(data__month=mes, data__year=ano_param)
        filtro_ativo = f"{MESES_PT[mes]} / {ano_param}"
    else:
        mes = today.month
        query_filtro &= Q(data__month=mes, data__year=ano_param)
        filtro_ativo = f"{MESES_PT[mes]} / {ano_param}"
    
    if request.method == 'POST':
        form = TransacaoForm(request.POST, user=user)
        if form.is_valid():
            transacao = form.save(commit=False)
            transacao.usuario = user 
            transacao.save()
            
            if form.cleaned_data.get('fixo'):
                nova_despesa = DespesaFixa.objects.create(
                    usuario=user,
                    nome=transacao.descricao,
                    valor_previsto=transacao.valor,
                    dia_vencimento=transacao.data.day,
                    categoria=transacao.categoria,
                    data_inicio=form.cleaned_data.get('data_inicio_fixo') or transacao.data,
                    data_fim=form.cleaned_data.get('data_fim_fixo')
                )
                transacao.despesa_fixa = nova_despesa
                transacao.save(update_fields=['despesa_fixa'])
                
                transacao_padrao_id = request.POST.get('transacao_padrao_id')
                if transacao_padrao_id:
                    t_padrao = Transacao.objects.filter(id=transacao_padrao_id, usuario=user).first()
                    if t_padrao:
                        desc_limpa = t_padrao.descricao.replace("Compra no débito - ", "") \
                                                       .replace("Transferência enviada pelo Pix - ", "") \
                                                       .replace("Transferência recebida pelo Pix - ", "") \
                                                       .strip()
                        
                        regra, created = RegraClassificacao.objects.get_or_create(
                            usuario=user,
                            palavra_chave=desc_limpa,
                            defaults={'categoria': transacao.categoria, 'despesa_vinculada': nova_despesa}
                        )

                        if not created:
                            regra.despesa_vinculada = nova_despesa
                            regra.save(update_fields=['despesa_vinculada'])

                        Transacao.objects.filter(
                            Q(id=t_padrao.id) | Q(descricao__icontains=desc_limpa),
                            usuario=user
                        ).update(despesa_fixa=nova_despesa)
                
            messages.success(request, 'Lançamento adicionado com sucesso!')
            return redirect('dashboard')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro no campo '{field}': {error}")
            logger.warning('Falha na validação do formulário de transação: %s', form.errors)
    else:
        form = TransacaoForm(user=user, initial={'data': today})

    transacoes = Transacao.objects.filter(query_filtro).select_related('categoria__macro_categoria')

    totais = transacoes.aggregate(
        receitas=Sum('valor', filter=Q(categoria__macro_categoria__tipo='receita')),
        despesas=Sum('valor', filter=Q(categoria__macro_categoria__tipo='despesa')),
        reservados=Sum('valor', filter=Q(categoria__macro_categoria__tipo='reservado'))
    )

    receitas = totais['receitas'] or Decimal('0.00')
    despesas = totais['despesas'] or Decimal('0.00')
    reservados = totais['reservados'] or Decimal('0.00')
    saldo_atual = receitas - despesas - reservados

    # -------------------------------------------------------------------------
    # Dataset 1 — Fluxo de Caixa: entradas vs. saídas nos últimos 6 meses.
    # Calculamos sempre em cima do mês corrente, independente do filtro ativo,
    # para que o gráfico de linha reflita a tendência histórica real do usuário.
    # -------------------------------------------------------------------------
    fluxo_labels: List[str] = []
    fluxo_entradas: List[float] = []
    fluxo_saidas: List[float] = []

    for i in range(5, -1, -1):
        # Retroage i meses a partir do mês atual, tratando a virada de ano
        mes_alvo = today.month - i
        ano_alvo = today.year
        while mes_alvo <= 0:
            mes_alvo += 12
            ano_alvo -= 1

        totais_mes = Transacao.objects.filter(
            usuario=user,
            data__month=mes_alvo,
            data__year=ano_alvo,
        ).aggregate(
            entrada=Sum('valor', filter=Q(categoria__macro_categoria__tipo='receita')),
            saida=Sum('valor', filter=Q(categoria__macro_categoria__tipo__in=['despesa', 'reservado'])),
        )

        fluxo_labels.append(MESES_PT[mes_alvo][:3])  # ex: "Jan", "Fev"
        fluxo_entradas.append(float(totais_mes['entrada'] or 0))
        fluxo_saidas.append(float(totais_mes['saida'] or 0))

    dados_fluxo: Dict[str, Any] = {
        'labels': fluxo_labels,
        'entradas': fluxo_entradas,
        'saidas': fluxo_saidas,
    }

    # -------------------------------------------------------------------------
    # Dataset 2 — Planejado vs. Realizado por Macro-categoria (mês do filtro).
    # Cruza OrcamentoCategoria (expectativa do PlanejamentoMensal) com as
    # transações reais. Trata ausência de PlanejamentoMensal com planejado=0.
    # -------------------------------------------------------------------------
    macros_labels: List[str] = []
    macros_planejado: List[float] = []
    macros_realizado: List[float] = []

    # Busca o planejamento mensal ativo para o mês do filtro
    planejamento_atual = PlanejamentoMensal.objects.filter(
        usuario=user,
        mes=mes,
        ano=ano_param,
    ).prefetch_related('orcamentos__macro_categoria').first()

    # Monta dicionário {macro_id: valor_planejado} para lookup O(1)
    orcamento_por_macro: Dict[int, float] = {}
    if planejamento_atual:
        for orc in planejamento_atual.orcamentos.all():
            orcamento_por_macro[orc.macro_categoria_id] = float(orc.valor_planejado)

    # Agrega o gasto real por macro-categoria (despesa) no período filtrado
    gastos_por_macro = (
        Transacao.objects.filter(
            query_filtro,
            categoria__macro_categoria__tipo='despesa',
        )
        .values('categoria__macro_categoria__id', 'categoria__macro_categoria__nome')
        .annotate(total=Sum('valor'))
        .order_by('categoria__macro_categoria__nome')
    )

    # Combina macros com gastos e macros que só têm orçamento (sem gastos ainda)
    macros_com_dados: Dict[int, Dict[str, Any]] = {}
    for item in gastos_por_macro:
        macro_id = item['categoria__macro_categoria__id']
        macros_com_dados[macro_id] = {
            'nome': item['categoria__macro_categoria__nome'],
            'planejado': orcamento_por_macro.get(macro_id, 0.0),
            'realizado': float(item['total']),
        }

    # Inclui macros que têm orçamento mas nenhum gasto no período
    for macro_id, valor_plan in orcamento_por_macro.items():
        if macro_id not in macros_com_dados:
            macro_obj = MacroCategoria.objects.filter(
                id=macro_id, usuario=user, tipo='despesa'
            ).first()
            if macro_obj:
                macros_com_dados[macro_id] = {
                    'nome': macro_obj.nome,
                    'planejado': valor_plan,
                    'realizado': 0.0,
                }

    for entry in sorted(macros_com_dados.values(), key=lambda x: x['nome']):
        macros_labels.append(entry['nome'])
        macros_planejado.append(entry['planejado'])
        macros_realizado.append(entry['realizado'])

    dados_macros: Dict[str, Any] = {
        'labels': macros_labels,
        'planejado': macros_planejado,
        'realizado': macros_realizado,
    }

    context = {
        'titulo': 'Fluxo de Caixa',
        'saldo': saldo_atual,
        'receitas': receitas,
        'despesas': despesas,
        'reservados': reservados,
        'ultimas_transacoes': transacoes.order_by('-data', '-id')[:5],
        'filtro_ativo': filtro_ativo,
        'periodo_tudo': periodo_tudo,
        'mes_atual': mes,
        'ano_atual': ano_param,
        'hoje': today,
        'form': form,
        'nome_mes': MESES_PT[mes],
        # Dados para os dois modos do gráfico de alternância
        'dados_fluxo_json': json.dumps(dados_fluxo),
        'dados_macros_json': json.dumps(dados_macros),
    }
    return render(request, 'financeiro/dashboard.html', context)


# ==============================================================================
# 2. HISTÓRICO E CRUD
# ==============================================================================

@login_required
def historico_transacoes(request: HttpRequest) -> HttpResponse:
    """
    Tela de histórico de lançamentos, onde o usuário pode visualizar, filtrar e acessar ações de edição/exclusão.
    """
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    tipo_filtro = request.GET.get('tipo')
    mes = request.GET.get('mes')
    ano = request.GET.get('ano')
    periodo = request.GET.get('periodo')

    today = date.today()
    
    if periodo == 'tudo':
        start_date = None
        end_date = None
    elif mes and ano:
        mes_int = int(mes)
        ano_int = int(ano)
        ultimo_dia = calendar.monthrange(ano_int, mes_int)[1]
        start_date = date(ano_int, mes_int, 1)
        end_date = date(ano_int, mes_int, ultimo_dia)
    elif start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            start_date = date(today.year, today.month, 1)
            end_date = today
    else:
        start_date = date(today.year, today.month, 1)
        end_date = today

    queryset = Transacao.objects.select_related('categoria__macro_categoria').filter(
        usuario=request.user
    ).order_by('-data', '-id')

    if start_date and end_date:
        queryset = queryset.filter(data__range=(start_date, end_date))

    if tipo_filtro in ['receita', 'despesa', 'reservado']:
        queryset = queryset.filter(categoria__macro_categoria__tipo=tipo_filtro)

    totais = queryset.aggregate(
        receitas=Sum('valor', filter=Q(categoria__macro_categoria__tipo='receita')),
        despesas=Sum('valor', filter=Q(categoria__macro_categoria__tipo='despesa')),
        reservados=Sum('valor', filter=Q(categoria__macro_categoria__tipo='reservado'))
    )
    
    rec = totais['receitas'] or Decimal('0.00')
    desp = totais['despesas'] or Decimal('0.00')
    res = totais['reservados'] or Decimal('0.00')

    if tipo_filtro == 'reservado':
        total_periodo = res
    elif tipo_filtro == 'receita':
        total_periodo = rec
    elif tipo_filtro == 'despesa':
        total_periodo = desp
    else:
        total_periodo = rec - desp - res

    MESES_PT = {
        1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril', 5: 'Maio', 6: 'Junho',
        7: 'Julho', 8: 'Agosto', 9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
    }

    if periodo == 'tudo':
        texto_periodo = "Todo o Período"
    elif mes and ano:
        texto_periodo = f"{MESES_PT[int(mes)]} / {ano}"
    elif start_date and end_date:
        texto_periodo = f"{start_date.strftime('%d/%m')} a {end_date.strftime('%d/%m')}"
    else:
        texto_periodo = f"{MESES_PT[today.month]} (Até Hoje)"

    if tipo_filtro == 'receita':
        filtro_ativo = f"Entradas • {texto_periodo}"
    elif tipo_filtro == 'despesa':
        filtro_ativo = f"Saídas • {texto_periodo}"
    elif tipo_filtro == 'reservado':
        filtro_ativo = f"Reservado • {texto_periodo}"
    else:
        filtro_ativo = texto_periodo

    # Monta JSON de macros e subcategorias para o modal de reclassificação
    todas_macros = MacroCategoria.objects.filter(usuario=request.user, ativo=True).order_by('tipo', 'ordem', 'nome')
    todas_cats = Categoria.objects.select_related('macro_categoria').filter(usuario=request.user, ativo=True).order_by('nome')

    categorias_reclassificacao = {
        'macros': [{'id': m.id, 'nome': m.nome, 'tipo': m.tipo} for m in todas_macros],
        'subcategorias': [{'id': c.id, 'nome': c.nome, 'macro_id': c.macro_categoria_id} for c in todas_cats],
    }

    context = {
        'titulo': 'Histórico de Lançamentos',
        'transacoes': queryset,
        'start_date': start_date.strftime('%Y-%m-%d') if start_date else '',
        'end_date': end_date.strftime('%Y-%m-%d') if end_date else '',
        'total_periodo': total_periodo,
        'tipo_filtro': tipo_filtro or '',
        'filtro_ativo': filtro_ativo,
        'hoje': today,
        'categorias_reclassificacao_json': json.dumps(categorias_reclassificacao),
    }
    return render(request, 'financeiro/historico.html', context)


@login_required
def editar_transacao(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Edita uma transação existente.
    """
    transacao = get_object_or_404(Transacao, pk=pk, usuario=request.user)
    
    if request.method == 'POST':
        form = TransacaoForm(request.POST, instance=transacao, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Registro atualizado com sucesso.")
            return redirect('historico_transacoes')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro no campo '{field}': {error}")
    else:
        form = TransacaoForm(instance=transacao, user=request.user)
    
    context = {
        'titulo': 'Editar Lançamento',
        'form': form,
        'is_editing': True,
        'transacao_id': pk
    }
    return render(request, 'financeiro/form_generico.html', context)


@login_required
def excluir_transacao(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Exclui uma transação existente.
    """
    transacao = get_object_or_404(Transacao, pk=pk, usuario=request.user)
    transacao.delete()
    messages.success(request, "Lançamento removido.")
    return redirect('historico_transacoes')


# ==============================================================================
# 3. APIS AJAX & INTEGRAÇÕES
# ==============================================================================

@login_required
def toggle_pago(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Alterna o status "Pago" de uma transação via AJAX, garantindo que apenas o dono da transação possa realizar a ação.
    """
    transacao = get_object_or_404(Transacao, pk=pk, usuario=request.user)
    transacao.pago = not transacao.pago
    transacao.save(update_fields=['pago'])
    
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({
            'status': 'success', 
            'novo_estado': transacao.pago,
            'mensagem': 'Status atualizado!'
        })
    return redirect('historico_transacoes')


@login_required
def get_chart_data(request: HttpRequest) -> JsonResponse:
    """
    Fornece dados agregados para gráficos, como total por Macro Categoria, com filtros de período e tipo.
    """
    periodo = request.GET.get('periodo')
    mes = request.GET.get('mes')
    ano = request.GET.get('ano')
    
    query = Q(usuario=request.user, categoria__macro_categoria__tipo='despesa')
    
    if periodo != 'tudo' and mes and ano:
        query &= Q(data__month=mes, data__year=ano)
    
    dados = Transacao.objects.filter(query).values('categoria__macro_categoria__nome').annotate(total=Sum('valor')).order_by('-total')

    labels = [item['categoria__macro_categoria__nome'] for item in dados]
    values = [float(item['total']) for item in dados]

    return JsonResponse({'labels': labels, 'values': values})


@login_required
def consolidar_transacao_ajax(request: HttpRequest, pk: int) -> JsonResponse:
    """
    Consolida uma transação pendente, atribuindo a categoria selecionada e opcionalmente criando uma regra de classificação.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'invalid_method'}, status=405)

    try:
        data = json.loads(request.body)
        categoria_id = data.get('categoria_id')
        criar_regra = data.get('criar_regra', False)
        
        transacao = get_object_or_404(Transacao, pk=pk, usuario=request.user)
        categoria = get_object_or_404(Categoria, pk=categoria_id, usuario=request.user)
        
        transacao.categoria = categoria
        transacao.status_auditoria = 'consolidado'
        transacao.save(update_fields=['categoria', 'status_auditoria'])
        
        ids_consolidados = [transacao.id]
        
        if criar_regra:
            desc_limpa = transacao.descricao.replace("Compra no débito - ", "") \
                                            .replace("Transferência enviada pelo Pix - ", "") \
                                            .replace("Transferência recebida pelo Pix - ", "") \
                                            .strip()
            
            RegraClassificacao.objects.get_or_create(
                usuario=request.user,
                palavra_chave=desc_limpa,
                defaults={'categoria': categoria}
            )
            
            outras_pendentes = Transacao.objects.filter(
                usuario=request.user,
                status_auditoria='pendente',
                descricao__icontains=desc_limpa
            ).exclude(id=transacao.id)
            
            ids_consolidados.extend(list(outras_pendentes.values_list('id', flat=True)))
            
            outras_pendentes.update(
                categoria=categoria,
                status_auditoria='consolidado'
            )
            
        return JsonResponse({
            'status': 'success', 
            'ids_consolidados': ids_consolidados
        })
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'mensagem': str(e)}, status=400)


@login_required
def reclassificar_transacao_ajax(request: HttpRequest) -> JsonResponse:
    """
    Motor de reclassificação retroativa do Extrato.

    Payload JSON esperado:
        {
            "transacao_id": <int>,
            "categoria_id": <int>,
            "aplicar_lote": <bool>   # true → cria regra + atualiza todos com mesma descrição
        }

    Retorno:
        { "status": "success", "atualizadas": <int> }
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'invalid_method'}, status=405)

    try:
        body = json.loads(request.body)
        transacao_id = body.get('transacao_id')
        categoria_id = body.get('categoria_id')
        aplicar_lote = bool(body.get('aplicar_lote', False))

        transacao = get_object_or_404(Transacao, pk=transacao_id, usuario=request.user)
        categoria = get_object_or_404(Categoria, pk=categoria_id, usuario=request.user)

        if not aplicar_lote:
            # Atualiza apenas esta transação
            transacao.categoria = categoria
            transacao.status_auditoria = Transacao.StatusAuditoria.CONSOLIDADO
            transacao.save(update_fields=['categoria', 'status_auditoria'])
            return JsonResponse({'status': 'success', 'atualizadas': 1})

        # Modo lote: cria/atualiza regra e reclassifica todas as transações com a mesma descrição
        desc_limpa = (
            transacao.descricao
            .replace("Compra no débito - ", "")
            .replace("Transferência enviada pelo Pix - ", "")
            .replace("Transferência recebida pelo Pix - ", "")
            .strip()
        )

        regra, _ = RegraClassificacao.objects.get_or_create(
            usuario=request.user,
            palavra_chave=desc_limpa,
            defaults={'categoria': categoria},
        )
        if regra.categoria_id != categoria.id:
            regra.categoria = categoria
            regra.save(update_fields=['categoria'])

        atualizadas = Transacao.objects.filter(
            usuario=request.user,
            descricao=transacao.descricao,
        ).update(
            categoria=categoria,
            status_auditoria=Transacao.StatusAuditoria.CONSOLIDADO,
        )

        return JsonResponse({'status': 'success', 'atualizadas': atualizadas})

    except Exception as e:
        return JsonResponse({'status': 'error', 'mensagem': str(e)}, status=400)


# ==============================================================================
# 4. EXPORTAÇÃO EXCEL & IMPORTAÇÃO
# ==============================================================================

@login_required
def exportar_financas_excel(request: HttpRequest) -> HttpResponse:
    """
    Exporta as transações do usuário para um arquivo Excel, aplicando os mesmos filtros de data e tipo do histórico.
    """
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    queryset = Transacao.objects.select_related('categoria__macro_categoria').filter(
        usuario=request.user
    ).order_by('data')

    if start_date_str and end_date_str:
        try:
            start = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            queryset = queryset.filter(data__range=(start, end))
        except ValueError:
            pass

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Relatorio Financeiro"

    headers = ["Data", "Descrição", "Macro Categoria", "Subcategoria", "Tipo", "Valor (R$)", "Status", "Fixo?"]
    ws.append(headers)

    header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
    white_font = Font(bold=True, color="FFFFFF")
    
    for cell in ws[1]:
        cell.font = white_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')

    for item in queryset:
        tipo = item.categoria.macro_categoria.tipo
        tipo_str = "ENTRADA" if tipo == 'receita' else "SAÍDA"
        status_str = "PAGO" if item.pago else "PENDENTE"
        fixo_str = "SIM" if item.fixo else "-"

        row = [
            item.data.strftime('%d/%m/%Y'), 
            item.descricao, 
            item.categoria.macro_categoria.nome,
            item.categoria.nome, 
            tipo_str, 
            item.valor, 
            status_str, 
            fixo_str
        ]
        ws.append(row)

        current_row = ws.max_row
        valor_cell = ws.cell(row=current_row, column=6)
        valor_cell.number_format = '#,##0.00'

        if tipo == 'receita':
            valor_cell.font = Font(color="10B981", bold=True)
        else:
            valor_cell.font = Font(color="EF4444", bold=True)

    for col in ws.columns:
        max_length = max((len(str(cell.value)) for cell in col if cell.value), default=0)
        ws.column_dimensions[col[0].column_letter].width = max_length + 2

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f"attachment; filename=Financas_{timezone.now().strftime('%Y%m%d_%H%M')}.xlsx"
    wb.save(response)
    
    return response


@login_required
def integracoes(request: HttpRequest) -> HttpResponse:
    """
    Hub central de integrações de dados: unifica o fluxo Open Finance (automático)
    e a importação manual de CSV (alternativa).

    Mantinha-se separada em `importar_extrato` + `tela_conexoes_open_finance`.
    A consolidação aqui reduz a fragmentação da UX e simplifica a navegação.
    """
    from django.conf import settings as django_settings

    if request.method == 'POST' and request.FILES.get('extrato'):
        arquivo = request.FILES['extrato']
        if not arquivo.name.endswith('.csv'):
            messages.error(request, "Por favor, envie um arquivo CSV.")
            return redirect('integracoes')

        try:
            resultado = processar_extrato_nubank(arquivo, usuario=request.user)
            messages.success(request, f"Importação concluída! {resultado['novos']} novos lançamentos.")
        except Exception as e:
            messages.error(request, f"Falha ao processar o arquivo: {e}")

        return redirect('integracoes')

    context = {
        'titulo': 'Integrações',
        'conexoes': ConexaoBancaria.objects.filter(usuario=request.user).order_by('-criado_em'),
        'lotes': LoteImportacao.objects.filter(usuario=request.user).order_by('-data_importacao'),
        'qtd_pendente': Transacao.objects.filter(usuario=request.user, status_auditoria='pendente').count(),
        # Apenas CLIENT_ID (pública) vai ao template — NUNCA a CLIENT_SECRET.
        'pluggy_client_id': getattr(django_settings, 'PLUGGY_CLIENT_ID', ''),
    }
    return render(request, 'financeiro/integracoes.html', context)


@login_required
def excluir_lote(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Exclui um lote de importação e todas as transações associadas.
    """
    lote = get_object_or_404(LoteImportacao, pk=pk, usuario=request.user)
    lote.delete()
    messages.success(request, "Arquivo e lançamentos removidos com sucesso.")
    return redirect('integracoes')


@login_required
def tela_auditoria(request: HttpRequest) -> HttpResponse:
    """
    Tela de auditoria, onde o usuário pode revisar e categorizar manualmente as transações pendentes.
    """
    pendencias = Transacao.objects.select_related('categoria__macro_categoria').filter(
        usuario=request.user, 
        status_auditoria='pendente'
    ).order_by('data')
    
    macro_categorias = MacroCategoria.objects.filter(
        usuario=request.user, ativo=True
    ).order_by('tipo', 'ordem', 'nome')

    categorias = Categoria.objects.select_related('macro_categoria').filter(
        usuario=request.user,
        ativo=True
    ).order_by('macro_categoria__ordem', 'nome')

    # JSON para os selects encadeados no frontend
    macros_json = [
        {'id': m.id, 'nome': m.nome, 'tipo': m.tipo}
        for m in macro_categorias
    ]
    subcategorias_json = [
        {'id': c.id, 'nome': c.nome, 'macro_id': c.macro_categoria_id}
        for c in categorias
        if 'Classificar' not in c.nome   # oculta categorias genéricas de sistema
    ]

    context = {
        'titulo': 'Auditoria de Lançamentos',
        'pendencias': pendencias,
        'categorias': categorias,
        'qtd_pendente': pendencias.count(),
        'macros_json': json.dumps(macros_json),
        'subcategorias_json': json.dumps(subcategorias_json),
    }
    return render(request, 'financeiro/auditoria.html', context)


# ==============================================================================
# 5. CONTROLADORIA (CARRY-OVER E PREVISIBILIDADE)
# ==============================================================================

def _calcular_status_despesa_fixa(despesa: DespesaFixa, today: date, usuario) -> List[Dict[str, Any]]:
    """
    Calcula o status de uma despesa fixa, considerando pagamentos históricos, vencimentos futuros e carry-over.
    Retorna uma lista de eventos relacionados à despesa fixa, incluindo o status atual e o próximo vencimento.
    """
    eventos = []
    
    is_futura = (despesa.data_inicio.year > today.year) or \
                (despesa.data_inicio.year == today.year and despesa.data_inicio.month > today.month)
                
    if is_futura:
        ultimo_dia_futuro = calendar.monthrange(despesa.data_inicio.year, despesa.data_inicio.month)[1]
        dia_venc_futuro = min(despesa.dia_vencimento, ultimo_dia_futuro)
        
        eventos.append({
            'despesa': despesa,
            'data_vencimento': date(despesa.data_inicio.year, despesa.data_inicio.month, dia_venc_futuro),
            'status': 'pendente',
            'valor': despesa.valor_previsto,
            'valido_mes_atual': False 
        })
        return eventos

    meses_passados = (today.year - despesa.data_inicio.year) * 12 + (today.month - despesa.data_inicio.month) + 1
    if despesa.data_fim:
        meses_totais = (despesa.data_fim.year - despesa.data_inicio.year) * 12 + (despesa.data_fim.month - despesa.data_inicio.month) + 1
        meses_passados = min(meses_passados, meses_totais)

    esperado_historico = Decimal(meses_passados) * despesa.valor_previsto
    
    pago_historico = Transacao.objects.filter(
        usuario=usuario, despesa_fixa=despesa, pago=True
    ).aggregate(Sum('valor'))['valor__sum'] or Decimal('0.00')
    
    falta_pagar = max(Decimal('0.00'), esperado_historico - Decimal(str(pago_historico)))

    ultimo_dia_mes = calendar.monthrange(today.year, today.month)[1]
    dia_venc_atual = min(despesa.dia_vencimento, ultimo_dia_mes)
    data_vencimento_atual = date(today.year, today.month, dia_venc_atual)

    status_atual = 'pago' if falta_pagar == Decimal('0.00') else ('atrasado' if today > data_vencimento_atual else 'pendente')

    eventos.append({
        'despesa': despesa,
        'data_vencimento': data_vencimento_atual,
        'status': status_atual,
        'valor': despesa.valor_previsto,
        'valido_mes_atual': True,
        'falta_pagar': falta_pagar
    })

    if status_atual == 'pago':
        next_month = today.month + 1 if today.month < 12 else 1
        next_year = today.year if today.month < 12 else today.year + 1
        ultimo_dia_next = calendar.monthrange(next_year, next_month)[1]
        
        data_venc_next = date(next_year, next_month, min(despesa.dia_vencimento, ultimo_dia_next))

        if not despesa.data_fim or data_venc_next <= despesa.data_fim:
            eventos.append({
                'despesa': despesa,
                'data_vencimento': data_venc_next,
                'status': 'pendente',
                'valor': despesa.valor_previsto,
                'valido_mes_atual': False
            })

    return eventos


@login_required
def controle_gastos_fixos(request: HttpRequest) -> HttpResponse:
    """
    Tela de controle de gastos fixos, onde o usuário pode visualizar o status atual de cada despesa fixa, incluindo o que já foi pago, o que falta pagar e os próximos vencimentos.
    """
    today = date.today()
    user = request.user
    
    despesas_ativas = DespesaFixa.objects.filter(
        usuario=user, 
        ativo=True,
        macro_categoria__tipo='despesa'
    )

    painel = []
    total_previsto = Decimal('0.00')
    total_pago_mes = Decimal('0.00')
    total_falta = Decimal('0.00')

    for despesa in despesas_ativas:
        eventos_despesa = _calcular_status_despesa_fixa(despesa, today, user)
        painel.extend(eventos_despesa)
        
        for evento in eventos_despesa:
            if evento.get('valido_mes_atual'):
                pago_este_mes = Transacao.objects.filter(
                    usuario=user, despesa_fixa=despesa, data__month=today.month, data__year=today.year, pago=True
                ).aggregate(Sum('valor'))['valor__sum'] or Decimal('0.00')
                
                total_falta += evento['falta_pagar']
                total_pago_mes += Decimal(str(pago_este_mes))
                total_previsto += evento['falta_pagar'] + Decimal(str(pago_este_mes))

    painel.sort(key=lambda x: x['data_vencimento'])

    categorias = Categoria.objects.filter(
        usuario=user,
        ativo=True,
        macro_categoria__tipo='despesa',
    ).select_related('macro_categoria').order_by('macro_categoria__nome', 'nome')

    categorias_por_macro: Dict[int, List[Dict[str, Any]]] = {}
    for cat in categorias:
        categorias_por_macro.setdefault(cat.macro_categoria_id, []).append({
            'id': cat.id,
            'nome': cat.nome,
        })

    context = {
        'titulo': 'Custos Fixos',
        'painel': painel,
        'total_previsto': total_previsto,
        'total_pago': total_pago_mes,
        'restante': total_falta,
        'categorias': categorias,
        'categorias_por_macro_json': json.dumps(categorias_por_macro),
        'redirect_next': request.get_full_path(),
    }
    return render(request, 'financeiro/gastos_fixos.html', context)

@login_required
def cadastrar_despesa_fixa_direta(request):
    """
    Cadastra uma despesa fixa diretamente no banco de dados
    """
    if request.method == 'POST':
        form = DespesaFixaForm(request.POST, user=request.user)
        if form.is_valid():
            despesa = form.save(commit=False)
            despesa.usuario = request.user
            despesa.save()

            transacao_padrao_id = request.POST.get('transacao_padrao_id')
            if transacao_padrao_id:
                t_padrao = Transacao.objects.filter(id=transacao_padrao_id, usuario=request.user).first()
                if t_padrao:
                    desc_limpa = t_padrao.descricao.replace("Compra no débito - ", "") \
                                                   .replace("Transferência enviada pelo Pix - ", "") \
                                                   .replace("Transferência recebida pelo Pix - ", "") \
                                                   .strip()
                    regra, created = RegraClassificacao.objects.get_or_create(
                        usuario=request.user,
                        palavra_chave=desc_limpa,
                        defaults={'categoria': despesa.categoria, 'despesa_vinculada': despesa}
                    )
                    if not created:
                        regra.despesa_vinculada = despesa
                        regra.save(update_fields=['despesa_vinculada'])
                    Transacao.objects.filter(
                        Q(id=t_padrao.id) | Q(descricao__icontains=desc_limpa),
                        usuario=request.user
                    ).update(despesa_fixa=despesa)
            messages.success(request, f"Plano para '{despesa.nome}' cadastrado com sucesso!")
        else:
            messages.error(request, "Erro ao validar o cadastro da conta fixa.")
    return _redirect_pos_fixo(request)

@login_required
def buscar_transacoes_ajax(request: HttpRequest) -> JsonResponse:
    """
    Busca as transações dos últimos 60 dias para o Modal de Vínculo Fixo.
    Suporta ?tipo=receita para buscar entradas (default: despesa).
    Permite filtrar por termo de descrição para facilitar a localização.
    """
    termo = request.GET.get('q', '').strip()
    tipo = request.GET.get('tipo', 'despesa')  # 'receita' ou 'despesa'
    data_limite = date.today() - timedelta(days=60)

    if tipo == 'receita':
        tipo_macro = ['receita']
    elif tipo == 'reservado':
        tipo_macro = ['reservado']
    else:
        tipo_macro = ['despesa', 'reservado']  # Se não especificado, busca saídas em geral
        
    query = Q(usuario=request.user, data__gte=data_limite, categoria__macro_categoria__tipo__in=tipo_macro)
    if termo:
        query &= Q(descricao__icontains=termo)

    transacoes = Transacao.objects.filter(query).order_by('-data')[:50]

    dados = []
    for t in transacoes:
        desc_exibicao = t.descricao.split('-', 1)[1].strip() if '-' in t.descricao else t.descricao
        dados.append({
            'id': t.id,
            'descricao': desc_exibicao,
            'valor': float(t.valor),
            'data': t.data.strftime('%d/%m/%Y'),
        })

    return JsonResponse({'transacoes': dados})

@login_required
def detalhes_despesa_fixa_ajax(request: HttpRequest, pk: int) -> JsonResponse:
    """
    Busca dados da despesa fixa e todo o histórico de transações vinculadas
    """
    despesa = get_object_or_404(DespesaFixa, pk=pk, usuario=request.user)
    
    transacoes = Transacao.objects.filter(despesa_fixa=despesa).order_by('-data')
    
    historico = []
    for t in transacoes:
        desc_limpa = t.descricao.split('-', 1)[1].strip() if '-' in t.descricao else t.descricao
        
        historico.append({
            'id': t.id,
            'data': t.data.strftime('%d/%m/%Y'),
            'descricao': desc_limpa,
            'valor': f"{t.valor:.2f}",
            'pago': t.pago
        })
    
    return JsonResponse({
        'id': despesa.id,
        'nome': despesa.nome,
        'valor_previsto': f"{despesa.valor_previsto:.2f}",
        'dia_vencimento': despesa.dia_vencimento,
        'data_inicio': despesa.data_inicio.strftime('%Y-%m-%d') if despesa.data_inicio else '',
        'data_fim': despesa.data_fim.strftime('%Y-%m-%d') if despesa.data_fim else '',
        'historico': historico
    })

@login_required
def editar_despesa_fixa(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Edita a despesa fixa
    """
    despesa = get_object_or_404(DespesaFixa, pk=pk, usuario=request.user)
    
    if request.method == 'POST':
        despesa.nome = request.POST.get('nome')
        despesa.valor_previsto = request.POST.get('valor_previsto').replace(',', '.')
        despesa.dia_vencimento = request.POST.get('dia_vencimento')
        if request.POST.get('data_inicio'):
            despesa.data_inicio = request.POST.get('data_inicio')
        if request.POST.get('data_fim'):
            despesa.data_fim = request.POST.get('data_fim')
        else:
            despesa.data_fim = None
        despesa.save()

        transacao_padrao_id = request.POST.get('transacao_padrao_id_edicao')
        if transacao_padrao_id:
            t_padrao = Transacao.objects.filter(id=transacao_padrao_id, usuario=request.user).first()
            if t_padrao:
                desc_limpa = t_padrao.descricao.replace("Compra no débito - ", "").replace("Transferência enviada pelo Pix - ", "").replace("Transferência recebida pelo Pix - ", "").strip()
                regra, created = RegraClassificacao.objects.get_or_create(
                    usuario=request.user, palavra_chave=desc_limpa,
                    defaults={'categoria': despesa.categoria, 'despesa_vinculada': despesa}
                )
                if not created:
                    regra.despesa_vinculada = despesa
                    regra.save(update_fields=['despesa_vinculada'])
                    
                Transacao.objects.filter(
                    Q(id=t_padrao.id) | Q(descricao__icontains=desc_limpa),
                    usuario=request.user
                ).update(despesa_fixa=despesa)

        messages.success(request, "Conta fixa atualizada com sucesso!")
    return _redirect_pos_fixo(request)

@login_required
def excluir_despesa_fixa(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Exclui a despesa fixa
    """
    despesa = get_object_or_404(DespesaFixa, pk=pk, usuario=request.user)
    if request.method == 'POST':
        despesa.delete() 
        messages.success(request, "Conta fixa removida.")
    return _redirect_pos_fixo(request)

@login_required
def cadastrar_receita_planejada(request: HttpRequest) -> HttpResponse:
    if request.method == 'POST':
        form = ReceitaPlanejadaForm(request.POST, user=request.user)
        if form.is_valid():
            receita = form.save(commit=False)
            receita.usuario = request.user
            macro_id = request.POST.get('macro_id')
            if macro_id and not receita.macro_categoria_id:
                receita.macro_categoria_id = int(macro_id)
            receita.save()
            messages.success(request, f"Receita '{receita.nome}' cadastrada com sucesso!")
        else:
            messages.error(request, "Erro ao validar o cadastro da receita planejada.")
    return _redirect_pos_fixo(request)


@login_required
def editar_receita_planejada(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Edita uma fonte de receita planejada existente.
    Processa o vínculo de uma transação padrão para criar uma RegraClassificacao
    de entradas, automatizando a classificação futura.
    """
    receita = get_object_or_404(ReceitaPlanejada, pk=pk, usuario=request.user)
    if request.method == 'POST':
        receita.nome = request.POST.get('nome', receita.nome)
        valor_raw = request.POST.get('valor_previsto', '').replace(',', '.')
        if valor_raw:
            receita.valor_previsto = Decimal(valor_raw)
        dia_raw = request.POST.get('dia_recebimento')
        if dia_raw:
            receita.dia_recebimento = int(dia_raw)
        data_inicio_raw = request.POST.get('data_inicio')
        if data_inicio_raw:
            receita.data_inicio = data_inicio_raw
        data_fim_raw = request.POST.get('data_fim')
        receita.data_fim = data_fim_raw if data_fim_raw else None
        categoria_id = request.POST.get('categoria')
        if categoria_id:
            receita.categoria_id = int(categoria_id)
            receita.macro_categoria_id = receita.categoria.macro_categoria_id
        receita.save()

        # Vincula transacao padrao para criar regra de classificação automática
        transacao_padrao_id = request.POST.get('transacao_padrao_id')
        if transacao_padrao_id:
            t_padrao = Transacao.objects.filter(id=transacao_padrao_id, usuario=request.user).first()
            if t_padrao:
                desc_limpa = t_padrao.descricao.split('-', 1)[1].strip() if '-' in t_padrao.descricao else t_padrao.descricao
                regra, created = RegraClassificacao.objects.get_or_create(
                    usuario=request.user,
                    palavra_chave=desc_limpa,
                    defaults={'categoria': receita.categoria, 'receita_vinculada': receita},
                )
                if not created:
                    # Atualiza o vínculo mesmo que a regra já existisse para outro provisionamento
                    regra.receita_vinculada = receita
                    regra.save(update_fields=['receita_vinculada'])

                # Vincula retroativamente as transações já importadas que casam com o padrão
                Transacao.objects.filter(
                    Q(id=t_padrao.id) | Q(descricao__icontains=desc_limpa),
                    usuario=request.user,
                ).update(receita_planejada=receita)

        messages.success(request, f"Receita '{receita.nome}' atualizada com sucesso!")
    return _redirect_pos_fixo(request)


@login_required
def excluir_receita_planejada(request: HttpRequest, pk: int) -> HttpResponse:
    receita = get_object_or_404(ReceitaPlanejada, pk=pk, usuario=request.user)
    if request.method == 'POST':
        receita.delete()
        messages.success(request, "Fonte de receita removida.")
    return _redirect_pos_fixo(request)


@login_required
def detalhes_receita_planejada_ajax(request: HttpRequest, pk: int) -> JsonResponse:
    """
    Retorna os dados de uma ReceitaPlanejada e o histórico de transações vinculadas,
    consumido pelo modal "Gerenciar Receita" via fetch.
    """
    receita = get_object_or_404(ReceitaPlanejada, pk=pk, usuario=request.user)

    transacoes = Transacao.objects.filter(
        receita_planejada=receita
    ).order_by('-data')

    historico = []
    for t in transacoes:
        desc_limpa = t.descricao.split('-', 1)[1].strip() if '-' in t.descricao else t.descricao
        historico.append({
            'id': t.id,
            'data': t.data.strftime('%d/%m/%Y'),
            'descricao': desc_limpa,
            'valor': f'{t.valor:.2f}',
            'pago': t.pago,
        })

    return JsonResponse({
        'id': receita.id,
        'nome': receita.nome,
        'valor_previsto': f'{receita.valor_previsto:.2f}',
        'dia_recebimento': receita.dia_recebimento,
        'data_inicio': receita.data_inicio.strftime('%Y-%m-%d') if receita.data_inicio else '',
        'data_fim': receita.data_fim.strftime('%Y-%m-%d') if receita.data_fim else '',
        'categoria_id': receita.categoria_id,
        'macro_categoria_id': receita.macro_categoria_id,
        'historico': historico,
    })


@login_required
def desvincular_transacao_receita_ajax(request: HttpRequest, pk: int) -> JsonResponse:
    """
    Remove o vínculo de uma transação com uma ReceitaPlanejada (sem excluir a transação).
    """
    if request.method == 'POST':
        transacao = get_object_or_404(Transacao, pk=pk, usuario=request.user)
        transacao.receita_planejada = None
        transacao.save(update_fields=['receita_planejada'])
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)




@login_required
def desvincular_transacao_ajax(request: HttpRequest, pk: int) -> JsonResponse:
    """
    Desvincula uma transação da despesa fixa (sem excluir a transação)
    """
    if request.method == 'POST':
        transacao = get_object_or_404(Transacao, pk=pk, usuario=request.user)
        transacao.despesa_fixa = None
        transacao.save(update_fields=['despesa_fixa'])
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)

# ==============================================================================
# 5b. QUICK ADD — LANÇAMENTO AVULSO DE PROVISIONAMENTO (AJAX)
# ==============================================================================

@login_required
def quick_add_provisionamento_ajax(request: HttpRequest) -> JsonResponse:
    """
    Cria um provisionamento avulso (DespesaFixa ou ReceitaPlanejada) de forma
    simplificada via AJAX, sem exigir preenchimento do formulário completo.

    Payload JSON esperado:
        { "nome": "...", "valor": 500.00, "macro_id": 3 }

    Retorna:
        { "status": "ok", "item": { id, nome, valor, categoria_nome }, "nova_soma": 1234.56 }
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'mensagem': 'Método não permitido.'}, status=405)

    if request.content_type == 'application/json':
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'status': 'error', 'mensagem': 'JSON inválido.'}, status=400)
    else:
        data = request.POST

    nome   = (data.get('nome') or '').strip()
    valor  = data.get('valor')
    macro_id = data.get('macro_id')

    if not nome:
        return JsonResponse({'status': 'error', 'mensagem': 'O nome não pode estar vazio.'}, status=400)
    try:
        valor_decimal = Decimal(str(valor))
        if valor_decimal <= 0:
            raise ValueError
    except (TypeError, ValueError, Exception):
        return JsonResponse({'status': 'error', 'mensagem': 'Valor inválido. Informe um número positivo.'}, status=400)

    macro = MacroCategoria.objects.filter(pk=macro_id, usuario=request.user, ativo=True).first()
    if not macro:
        return JsonResponse({'status': 'error', 'mensagem': 'Macro categoria não encontrada.'}, status=404)

    # Garante que existe uma Categoria "Geral" para esta macro (cria se necessário)
    categoria_geral, _ = Categoria.objects.get_or_create(
        usuario=request.user,
        macro_categoria=macro,
        nome='Geral',
        defaults={'icone': 'bi-box', 'ativo': True},
    )

    hoje = date.today()

    if macro.tipo == 'receita':
        item = ReceitaPlanejada.objects.create(
            usuario=request.user,
            nome=nome,
            valor_previsto=valor_decimal,
            dia_recebimento=1,
            categoria=categoria_geral,
            macro_categoria=macro,
            ativo=True,
            data_inicio=hoje,
        )
        # Recalcula soma das receitas planejadas ativas para esta macro
        nova_soma = float(
            ReceitaPlanejada.objects.filter(
                usuario=request.user,
                macro_categoria=macro,
                ativo=True,
            ).aggregate(total=Sum('valor_previsto'))['total'] or Decimal('0.00')
        )
        tipo_item = 'receita'
    else:
        item = DespesaFixa.objects.create(
            usuario=request.user,
            nome=nome,
            valor_previsto=valor_decimal,
            dia_vencimento=1,
            categoria=categoria_geral,
            macro_categoria=macro,
            ativo=True,
            data_inicio=hoje,
        )
        # Recalcula soma das despesas fixas ativas para esta macro
        nova_soma = float(
            DespesaFixa.objects.filter(
                usuario=request.user,
                macro_categoria=macro,
                ativo=True,
            ).aggregate(total=Sum('valor_previsto'))['total'] or Decimal('0.00')
        )
        tipo_item = macro.tipo  # 'despesa' ou 'reservado'

    return JsonResponse({
        'status': 'ok',
        'tipo': tipo_item,
        'nova_soma': nova_soma,
        'item': {
            'id': item.pk,
            'nome': item.nome,
            'valor': float(item.valor_previsto),
            'categoria_nome': categoria_geral.nome,
        },
    })


# ==============================================================================
# 6. PLANEJAMENTO MENSAL E ORÇAMENTOS
# ==============================================================================

@login_required
def tela_planejamento(request):
    """
    Tela de planejamento mensal, onde o usuário pode definir a receita esperada e alocar valores para cada Macro Categoria, com validações para evitar excessos e garantir consistência.
    """
    hoje = date.today()
    mes_atual = int(request.GET.get('mes', hoje.month))
    ano_atual = int(request.GET.get('ano', hoje.year))
    
    planejamento, created = PlanejamentoMensal.objects.get_or_create(
        usuario=request.user,
        mes=mes_atual,
        ano=ano_atual
    )
    
    ultimo_dia = calendar.monthrange(ano_atual, mes_atual)[1]
    data_ref = date(ano_atual, mes_atual, ultimo_dia)

    if request.method == 'POST':
        # Calcula a receita_esperada como soma das ReceitasPlanejadas ativas — nunca usa o valor do POST
        receitas_ativas_post = (
            ReceitaPlanejada.objects.ativas_na_data(data_ref)
            .filter(usuario=request.user)
        )
        soma_receitas = receitas_ativas_post.aggregate(total=Sum('valor_previsto'))['total'] or Decimal('0.00')
        # Usa o valor manual do form apenas se não houver receitas cadastradas
        if soma_receitas == Decimal('0.00'):
            receita_esperada_raw = request.POST.get('receita_esperada', '0').replace(',', '.')
            planejamento.receita_esperada = float(receita_esperada_raw or 0)
        else:
            planejamento.receita_esperada = float(soma_receitas)
        planejamento.save()

        despesas_fixas_ativas = (
            DespesaFixa.objects.ativas_na_data(data_ref)
            .filter(usuario=request.user)
            .select_related('categoria')
        )
        fixos_por_macro = DespesaFixa.agrupar_por_macro(despesas_fixas_ativas)

        receitas_planejadas_ativas = (
            ReceitaPlanejada.objects.ativas_na_data(data_ref)
            .filter(usuario=request.user)
            .select_related('categoria')
        )
        receitas_por_macro = ReceitaPlanejada.agrupar_por_macro(receitas_planejadas_ativas)

        macros = MacroCategoria.objects.filter(usuario=request.user, ativo=True)
        for macro in macros:
            if macro.tipo == 'receita':
                grupo = receitas_por_macro.get(macro.id, {'soma': Decimal('0.00')})
            else:
                grupo = fixos_por_macro.get(macro.id, {'soma': Decimal('0.00')})

            if grupo['soma'] > 0:
                valor_limpo = float(grupo['soma'])
            else:
                valor_str = request.POST.get(f'valor_macro_{macro.id}', '0').replace(',', '.')
                valor_limpo = float(valor_str) if valor_str else 0.0

            OrcamentoCategoria.objects.update_or_create(
                planejamento=planejamento,
                macro_categoria=macro,
                defaults={'valor_planejado': valor_limpo}
            )

        messages.success(request, "Planejamento salvo com sucesso!")
        return redirect(f"{request.path}?mes={mes_atual}&ano={ano_atual}")
    
    macros = MacroCategoria.objects.filter(
        usuario=request.user, 
        ativo=True
    )

    # Cria dicionário indexado com os valores que já estão no banco de dados
    orcamentos_salvos = {
        orc.macro_categoria_id: float(orc.valor_planejado)
        for orc in planejamento.orcamentos.all()
    }

    despesas_fixas_ativas = (
        DespesaFixa.objects.ativas_na_data(data_ref)
        .filter(usuario=request.user)
        .select_related('categoria', 'macro_categoria')
    )
    fixos_por_macro = DespesaFixa.agrupar_por_macro(despesas_fixas_ativas)

    receitas_planejadas_ativas = (
        ReceitaPlanejada.objects.ativas_na_data(data_ref)
        .filter(usuario=request.user)
        .select_related('categoria', 'macro_categoria')
    )
    receitas_por_macro = ReceitaPlanejada.agrupar_por_macro(receitas_planejadas_ativas)

    categorias = Categoria.objects.filter(
        usuario=request.user,
        ativo=True,
        macro_categoria__tipo__in=['despesa', 'reservado'],
    ).select_related('macro_categoria').order_by('macro_categoria__nome', 'nome')

    categorias_receita = Categoria.objects.filter(
        usuario=request.user,
        ativo=True,
        macro_categoria__tipo='receita',
    ).select_related('macro_categoria').order_by('macro_categoria__nome', 'nome')

    categorias_por_macro: Dict[int, List[Dict[str, Any]]] = {}
    for cat in categorias:
        categorias_por_macro.setdefault(cat.macro_categoria_id, []).append({
            'id': cat.id,
            'nome': cat.nome,
        })

    categorias_receita_por_macro: Dict[int, List[Dict[str, Any]]] = {}
    for cat in categorias_receita:
        categorias_receita_por_macro.setdefault(cat.macro_categoria_id, []).append({
            'id': cat.id,
            'nome': cat.nome,
        })

    lista_macros_planejamento = []

    # Receita esperada base para cálculo de percentuais
    receita_esperada_base = float(planejamento.receita_esperada or 0)

    for macro in macros:
        icone_dinamico = ICONES_MACRO.get(
            macro.nome,
            'bi-wallet2'
        )

        if macro.tipo == 'receita':
            grupo = receitas_por_macro.get(macro.id, {'itens': [], 'soma': Decimal('0.00')})
        else:
            grupo = fixos_por_macro.get(macro.id, {'itens': [], 'soma': Decimal('0.00')})

        itens_provisionamento = [
            {
                'id': item['id'],
                'nome': item['nome'],
                'valor': float(item['valor']),
                'categoria_nome': item['categoria_nome'],
            }
            for item in grupo['itens']
        ]
        soma_provisionamento = float(grupo['soma'])
        count_provisionamento = len(itens_provisionamento)
        tem_provisionamento = count_provisionamento > 0
        valor_planejado = orcamentos_salvos.get(macro.id, 0.00)

        # Valor calculado: soma dos provisionamentos (ou valor_planejado manual se não houver)
        valor_planejado_calculado = soma_provisionamento if tem_provisionamento else valor_planejado

        # Percentual em relação à receita esperada do mês
        if receita_esperada_base > 0:
            percentual_calculado = round((valor_planejado_calculado / receita_esperada_base) * 100, 1)
        else:
            percentual_calculado = 0.0

        lista_macros_planejamento.append({
            'id': macro.id,
            'nome': macro.nome,
            'tipo': macro.tipo,
            'icone': icone_dinamico,
            'valor_planejado': valor_planejado,
            'valor_exibido': valor_planejado_calculado,
            'valor_bloqueado': tem_provisionamento,
            'valor_planejado_calculado': valor_planejado_calculado,
            'percentual_calculado': percentual_calculado,
            'provisionamentos': itens_provisionamento,
            'soma_provisionamento': soma_provisionamento,
            'count_provisionamento': count_provisionamento,
            'tem_provisionamento': tem_provisionamento,
            'pode_remover_escopo': count_provisionamento == 0,
            'despesas_fixas': itens_provisionamento,
            'soma_fixos': soma_provisionamento,
            'tem_fixos': tem_provisionamento,
            'count_fixos': count_provisionamento,
        })

    # Ordenação Customizada: 1º Receita, 2º Despesa, 3º Reservado
    ordem_tipos = {'receita': 1, 'despesa': 2, 'reservado': 3}
    lista_macros_planejamento.sort(key=lambda x: (ordem_tipos.get(x['tipo'], 4), x['nome']))

    # Cabeçalho formatado
    MESES_PT = {
        1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril', 5: 'Maio', 6: 'Junho',
        7: 'Julho', 8: 'Agosto', 9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
    }
    filtro_ativo = f"{MESES_PT[mes_atual]} / {ano_atual}"

    planejamento_next = f"{reverse('tela_planejamento')}?mes={mes_atual}&ano={ano_atual}"

    provisionamentos_por_macro_json = json.dumps({
        str(m['id']): {
            'tipo': m['tipo'],
            'nome': m['nome'],
            'icone': m['icone'],
            'itens': m['provisionamentos'],
            'soma': m['soma_provisionamento'],
        }
        for m in lista_macros_planejamento
    })

    # Soma total das receitas planejadas ativas para este mês (usado para bloquear o campo no template)
    soma_receitas_planejadas = float(
        receitas_planejadas_ativas.aggregate(total=Sum('valor_previsto'))['total'] or Decimal('0.00')
    )

    # Se há receitas vinculadas no mês, garante que o planejamento.receita_esperada 
    # enviado no contexto seja a soma dinâmica real
    if soma_receitas_planejadas > 0:
        planejamento.receita_esperada = soma_receitas_planejadas

    # Limites temporários ativos (dentro da janela temporal) — preparados para o Open Finance
    limites_temporarios = LimiteTemporario.objects.ativos_para_usuario(request.user)

    context = {
        'titulo': 'Planejamento de Orçamento',
        'planejamento': planejamento,
        'macros_planejamento': lista_macros_planejamento,
        'filtro_ativo': filtro_ativo,
        'mes_atual': mes_atual,
        'ano_atual': ano_atual,
        'categorias': categorias,
        'categorias_receita': categorias_receita,
        'categorias_por_macro_json': json.dumps(categorias_por_macro),
        'categorias_receita_por_macro_json': json.dumps(categorias_receita_por_macro),
        'provisionamentos_por_macro_json': provisionamentos_por_macro_json,
        'planejamento_next': planejamento_next,
        'soma_receitas_planejadas': soma_receitas_planejadas,
        # Limites temporários: renderizados na seção de "Guardas de Gasto"
        'limites_temporarios': limites_temporarios,
        # Todas as categorias de despesa/reserva para o select do modal de criação
        'categorias_limite': Categoria.objects.filter(
            usuario=request.user,
            ativo=True,
            macro_categoria__tipo__in=['despesa', 'reservado'],
        ).select_related('macro_categoria').order_by('macro_categoria__nome', 'nome'),
    }
    return render(request, 'financeiro/planejamento.html', context)


# ==============================================================================
# 5c. GERENCIAMENTO DINÂMICO DE CATEGORIAS (AJAX)
# ==============================================================================


# ==============================================================================
# 6b. LIMITES TEMPORÁRIOS DE GASTOS
# ==============================================================================

# TODO: views.py com 1500+ linhas. Numa próxima sprint, extrair as seções de
# Planejamento e Limites para um módulo views/ (package estruturado).


@login_required
def cadastrar_limite_temporario(request: HttpRequest) -> JsonResponse:
    """
    Cria um novo Limite Temporário de Gastos via POST/AJAX.

    A `data_fim` é calculada aqui no servidor, nunca recebida do cliente,
    garantindo consistência de fuso horário — pré-requisito para o worker
    do Open Finance validar se uma transação está dentro do período do limite.

    Args:
        request: HttpRequest com POST contendo 'valor_limite', 'categoria_alvo',
                 'duracao' ('24h'|'7d'|'30d'|'custom') e opcionalmente 'duracao_custom_horas'.

    Returns:
        JsonResponse com 'status': 'ok' e os dados do limite criado, ou 'error' com mensagem.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'mensagem': 'Método não permitido.'}, status=405)

    form = LimiteTemporarioForm(request.POST, user=request.user)
    if not form.is_valid():
        # Consolida todos os erros em uma mensagem única para o frontend exibir no toast
        erros = ' '.join(
            str(e)
            for field_errors in form.errors.values()
            for e in field_errors
        )
        return JsonResponse({'status': 'error', 'mensagem': erros}, status=400)

    duracao = form.cleaned_data['duracao']
    custom_horas = form.cleaned_data.get('duracao_custom_horas') or 0

    # Mapeamento duração → horas. Calculado no servidor para evitar drift de fuso.
    DURACAO_HORAS: Dict[str, int] = {
        '24h': 24,
        '7d': 7 * 24,
        '30d': 30 * 24,
        'custom': custom_horas,
    }
    horas = DURACAO_HORAS.get(duracao, 24)
    data_fim = timezone.now() + timedelta(hours=horas)

    limite = form.save(commit=False)
    limite.usuario = request.user
    limite.data_fim = data_fim
    limite.save()

    # Formata o rótulo de categoria para exibição imediata no card do frontend
    categoria_nome = limite.categoria_alvo.nome if limite.categoria_alvo else 'Geral'

    return JsonResponse({
        'status': 'ok',
        'limite': {
            'id': limite.pk,
            'valor_limite': float(limite.valor_limite),
            'valor_consumido': float(limite.valor_consumido),
            'percentual': limite.percentual_consumido,
            'categoria_nome': categoria_nome,
            'data_fim_iso': limite.data_fim.isoformat(),
            'tempo_restante_segundos': limite.tempo_restante_segundos,
            'cor_status': limite.cor_status_tailwind,
            'cor_barra': limite.cor_barra_tailwind,
        },
    })


@login_required
def desativar_limite_temporario(request: HttpRequest, pk: int) -> JsonResponse:
    """
    Soft-delete de um Limite Temporário (ativo=False).

    Optamos por soft-delete em vez de DELETE para manter rastreabilidade histórica
    — o Open Finance pode precisar auditar quais limites estavam vigentes quando
    uma transação foi registrada.

    Args:
        request: HttpRequest POST.
        pk: ID do LimiteTemporario a desativar.

    Returns:
        JsonResponse {'status': 'ok'} em caso de sucesso.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'mensagem': 'Método não permitido.'}, status=405)

    limite = get_object_or_404(LimiteTemporario, pk=pk, usuario=request.user)
    limite.ativo = False
    limite.save(update_fields=['ativo'])
    return JsonResponse({'status': 'ok'})

@login_required
def criar_categoria_ajax(request: HttpRequest) -> JsonResponse:
    """
    Lista ou cria categorias atreladas a uma MacroCategoria do usuário.
    GET: Retorna a lista de categorias ativas para a macro indicada por 'macro_categoria_id'.
    POST: Cria uma nova categoria ou reativa uma inativa existente.
    """
    if request.method == 'GET':
        macro_id = request.GET.get('macro_categoria_id')
        if not macro_id:
            return JsonResponse({'status': 'error', 'mensagem': 'ID da macro categoria é obrigatório.'}, status=400)
        try:
            macro = MacroCategoria.objects.get(pk=macro_id, usuario=request.user, ativo=True)
        except MacroCategoria.DoesNotExist:
            return JsonResponse({'status': 'error', 'mensagem': 'Macro categoria não encontrada.'}, status=404)

        cats = Categoria.objects.filter(usuario=request.user, macro_categoria=macro, ativo=True).order_by('nome')
        cats_data = [{'id': c.id, 'nome': c.nome, 'macro_id': c.macro_categoria_id} for c in cats]
        return JsonResponse({'status': 'ok', 'categorias': cats_data})

    elif request.method == 'POST':
        nome = None
        macro_id = None
        if request.body:
            try:
                data = json.loads(request.body)
                nome = data.get('nome')
                macro_id = data.get('macro_categoria_id')
            except (json.JSONDecodeError, ValueError):
                pass

        if not nome or not macro_id:
            nome = request.POST.get('nome')
            macro_id = request.POST.get('macro_categoria_id')

        nome = (nome or '').strip()
        if not nome:
            return JsonResponse({'status': 'error', 'mensagem': 'O nome da categoria não pode estar vazio.'}, status=400)

        try:
            macro = MacroCategoria.objects.get(pk=macro_id, usuario=request.user, ativo=True)
        except MacroCategoria.DoesNotExist:
            return JsonResponse({'status': 'error', 'mensagem': 'Macro categoria não encontrada.'}, status=404)

        try:
            # Tenta recuperar uma categoria existente (ativa ou inativa) para evitar crash de restrição unique
            cat = Categoria.objects.get(usuario=request.user, macro_categoria=macro, nome__iexact=nome)
            if not cat.ativo:
                cat.ativo = True
                cat.save()
            else:
                return JsonResponse({'status': 'error', 'mensagem': 'Já existe uma categoria com este nome nesta macro.'}, status=400)
        except Categoria.DoesNotExist:
            cat = Categoria.objects.create(usuario=request.user, macro_categoria=macro, nome=nome)

        cats = Categoria.objects.filter(usuario=request.user, macro_categoria=macro, ativo=True).order_by('nome')
        cats_data = [{'id': c.id, 'nome': c.nome, 'macro_id': c.macro_categoria_id} for c in cats]

        return JsonResponse({
            'status': 'ok',
            'categoria': {'id': cat.id, 'nome': cat.nome, 'macro_id': cat.macro_categoria_id},
            'categorias': cats_data
        })

    return JsonResponse({'status': 'error', 'mensagem': 'Método não permitido.'}, status=405)


@login_required
def editar_categoria_ajax(request: HttpRequest, pk: int) -> JsonResponse:
    """
    Edita (renomeia) uma categoria do usuário.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'mensagem': 'Método não permitido.'}, status=405)

    nome = None
    if request.body:
        try:
            data = json.loads(request.body)
            nome = data.get('nome')
        except (json.JSONDecodeError, ValueError):
            pass

    if not nome:
        nome = request.POST.get('nome')

    nome = (nome or '').strip()
    if not nome:
        return JsonResponse({'status': 'error', 'mensagem': 'O nome da categoria não pode estar vazio.'}, status=400)

    try:
        cat = Categoria.objects.get(pk=pk, usuario=request.user)
    except Categoria.DoesNotExist:
        return JsonResponse({'status': 'error', 'mensagem': 'Categoria não encontrada.'}, status=404)

    # Verifica se já existe outra categoria com esse nome na mesma macro
    if Categoria.objects.filter(usuario=request.user, macro_categoria=cat.macro_categoria, nome__iexact=nome).exclude(id=cat.id).exists():
        return JsonResponse({'status': 'error', 'mensagem': 'Já existe outra categoria com este nome nesta macro.'}, status=400)

    cat.nome = nome
    cat.ativo = True
    cat.save()

    cats = Categoria.objects.filter(usuario=request.user, macro_categoria=cat.macro_categoria, ativo=True).order_by('nome')
    cats_data = [{'id': c.id, 'nome': c.nome, 'macro_id': c.macro_categoria_id} for c in cats]

    return JsonResponse({
        'status': 'ok',
        'categoria': {'id': cat.id, 'nome': cat.nome, 'macro_id': cat.macro_categoria_id},
        'categorias': cats_data
    })


@login_required
def excluir_categoria_ajax(request: HttpRequest, pk: int) -> JsonResponse:
    """
    Exclui logicamente (desativa) uma categoria do usuário.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'mensagem': 'Método não permitido.'}, status=405)

    try:
        cat = Categoria.objects.get(pk=pk, usuario=request.user)
    except Categoria.DoesNotExist:
        return JsonResponse({'status': 'error', 'mensagem': 'Categoria não encontrada.'}, status=404)

    macro = cat.macro_categoria
    cat.ativo = False
    cat.save()

    cats = Categoria.objects.filter(usuario=request.user, macro_categoria=macro, ativo=True).order_by('nome')
    cats_data = [{'id': c.id, 'nome': c.nome, 'macro_id': c.macro_categoria_id} for c in cats]

    return JsonResponse({
        'status': 'ok',
        'categorias': cats_data
    })


# ==============================================================================
# 10. PERFIL E CONFIGURAÇÕES
# ==============================================================================

@login_required
def tela_configuracoes(request: HttpRequest) -> HttpResponse:
    """Tela unificada de configurações: Perfil, Segurança e Integrações."""
    perfil, _ = PerfilUsuario.objects.get_or_create(usuario=request.user)

    if request.method == 'POST':
        user_form = UsuarioForm(request.POST, instance=request.user)
        perfil_form = PerfilUsuarioForm(request.POST, request.FILES, instance=perfil)

        if user_form.is_valid() and perfil_form.is_valid():
            user_form.save()
            perfil_form.save()
            messages.success(request, 'Configurações salvas com sucesso!')
            return redirect('tela_configuracoes')
    else:
        user_form = UsuarioForm(instance=request.user)
        perfil_form = PerfilUsuarioForm(instance=perfil)

    context = {
        'titulo': 'Configurações',
        'user_form': user_form,
        'perfil_form': perfil_form,
    }
    return render(request, 'financeiro/configuracoes.html', context)


# ==============================================================================
# 10. OPEN FINANCE — PLUGGY
# ==============================================================================

@login_required
def gerar_token_pluggy(request: HttpRequest) -> JsonResponse:
    """
    Endpoint AJAX que gera um Connect Token efêmero (~30 min) para o widget Pluggy Connect.

    O token é gerado server-side (usando Client ID + Secret) para que o frontend
    nunca precise conhecer o Client Secret. O widget JS recebe apenas este token
    de vida curta e limitada.

    Suporta o parâmetro opcional `item_id` para reconexão de itens com erro de login.

    Returns:
        JsonResponse com `{"access_token": str}` ou erro 500.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'mensagem': 'Método não permitido.'}, status=405)

    try:
        body = json.loads(request.body) if request.body else {}
        item_id = body.get('item_id')  # Opcional: reconexão de item existente
        cliente = PluggyAPIClient()
        access_token = cliente.gerar_connect_token(item_id=item_id)
        return JsonResponse({'access_token': access_token})
    except Exception as exc:
        logger.error('Falha ao gerar connect token Pluggy: %s', exc)
        return JsonResponse({'status': 'error', 'mensagem': str(exc)}, status=500)


@login_required
def tela_conexoes_open_finance(request: HttpRequest) -> HttpResponse:
    """
    Renderiza a tela de gerenciamento de conexões bancárias Open Finance.

    Exibe as conexões ativas do usuário e injeta a chave pública do Pluggy
    Connect via contexto para o template inicializar o widget JS sem expor
    a Client Secret no frontend.

    Returns:
        HttpResponse com o template `open_finance.html` renderizado.
    """
    from django.conf import settings as django_settings

    conexoes = (
        ConexaoBancaria.objects
        .filter(usuario=request.user)
        .order_by('-criado_em')
    )

    context = {
        'titulo': 'Conexões Bancárias',
        'conexoes': conexoes,
        # Apenas o CLIENT_ID (chave pública) é seguro de expor no frontend.
        'pluggy_client_id': getattr(django_settings, 'PLUGGY_CLIENT_ID', ''),
    }
    return render(request, 'financeiro/open_finance.html', context)


@login_required
def salvar_conexao_bancaria_ajax(request: HttpRequest) -> JsonResponse:
    """
    Endpoint AJAX que recebe o `itemId` gerado pelo Pluggy Connect após o
    consentimento do usuário e persiste a ConexaoBancaria no banco.

    Chamado pelo frontend imediatamente após o evento `onSuccess` do widget.

    Payload JSON esperado:
        {
            "item_id": "<string: Pluggy Item ID>",
            "instituicao_nome": "<string: nome amigável do banco>"
        }

    Returns:
        JsonResponse com `{"status": "created"|"exists", "conexao_id": int}`
        ou `{"status": "error", "mensagem": str}` com status 400.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'invalid_method'}, status=405)

    try:
        body = json.loads(request.body)
        item_id = str(body.get('item_id', '')).strip()
        instituicao_nome = str(body.get('instituicao_nome', 'Banco Desconhecido')).strip()[:100]

        if not item_id:
            return JsonResponse({'status': 'error', 'mensagem': 'item_id é obrigatório.'}, status=400)

        conexao, created = ConexaoBancaria.objects.get_or_create(
            item_id_externo=item_id,
            defaults={
                'usuario': request.user,
                'instituicao_nome': instituicao_nome,
                'provider': 'pluggy',
                'status': ConexaoBancaria.StatusConexao.UPDATED,
            },
        )

        # Garante que uma conexão existente pertença ao mesmo usuário (proteção IDOR).
        if not created and conexao.usuario_id != request.user.id:
            return JsonResponse({'status': 'error', 'mensagem': 'Acesso negado.'}, status=403)

        # Dispara a primeira sincronização em background para não bloquear o response.
        # O usuário vê o feedback imediato enquanto as transações são importadas.
        if created:
            import threading
            t = threading.Thread(
                target=_sync_conexao_em_background,
                args=(conexao.pk,),
                daemon=True,
            )
            t.start()

        return JsonResponse({
            'status': 'created' if created else 'exists',
            'conexao_id': conexao.pk,
            'instituicao_nome': conexao.instituicao_nome,
            'sincronizando': created,  # Sinaliza para o frontend exibir feedback de loading
        })

    except Exception as exc:
        return JsonResponse({'status': 'error', 'mensagem': str(exc)}, status=400)


@login_required
def sincronizar_conexao_ajax(request: HttpRequest, pk: int) -> JsonResponse:
    """
    Dispara manualmente a sincronização de uma ConexaoBancaria específica via AJAX.

    Utilizado pelo botão 'Sincronizar Agora' na tela de conexões, permitindo que
    o usuário force uma atualização sem aguardar o próximo ciclo do Cron.

    Args:
        pk: PK da ConexaoBancaria a sincronizar (vem da URL).

    Returns:
        JsonResponse com `{"status": "success", "stats": {...}}` ou erro.
    """
    if request.method != 'POST':
        return JsonResponse({'status': 'invalid_method'}, status=405)

    # Filtro por usuário garante proteção contra IDOR.
    conexao = get_object_or_404(ConexaoBancaria, pk=pk, usuario=request.user)

    try:
        stats = sincronizar_transacoes_open_finance(conexao=conexao)
        return JsonResponse({
            'status': 'success',
            'stats': stats,
            'mensagem': (
                f'{stats["novos"]} nova(s) transação(ões) importada(s). '
                f'{stats["duplicados"]} já existia(m).'
            ),
        })
    except Exception as exc:
        return JsonResponse({'status': 'error', 'mensagem': str(exc)}, status=500)