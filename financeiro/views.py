import json
import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, Q
from django.utils import timezone

# Imports locais
from .services import processar_extrato_nubank
from .models import Transacao, Categoria, RegraClassificacao, LoteImportacao, DespesaFixa
from .forms import TransacaoForm


# ==============================================================================
# 1. DASHBOARD E OPERAÇÃO PRINCIPAL
# ==============================================================================

@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """
    Renderiza o painel principal, processa adições rápidas e consolida totais do mês.
    """
    today = date.today()
    user = request.user
    
    if request.method == 'POST':
        form = TransacaoForm(request.POST, user=user)
        if form.is_valid():
            transacao = form.save()
            
            if form.cleaned_data.get('fixo'):
                nova_despesa = DespesaFixa.objects.create(
                    nome=transacao.descricao,
                    valor_previsto=transacao.valor,
                    dia_vencimento=transacao.data.day,
                    categoria=transacao.categoria,
                    data_inicio=form.cleaned_data.get('data_inicio_fixo') or transacao.data,
                    data_fim=form.cleaned_data.get('data_fim_fixo')
                )
                transacao.despesa_fixa = nova_despesa
                transacao.save(update_fields=['despesa_fixa'])
                
            messages.success(request, 'Lançamento adicionado com sucesso!')
            return redirect('dashboard')
    else:
        form = TransacaoForm(user=user, initial={'data': today})

    # Busca otimizada usando aggregate e Q objects do Django (Faz a conta no Banco)
    transacoes_mes = Transacao.objects.filter(data__month=today.month, data__year=today.year)
    totais = transacoes_mes.aggregate(
        receitas=Sum('valor', filter=Q(categoria__tipo='receita')),
        despesas=Sum('valor', filter=Q(categoria__tipo='despesa'))
    )

    receitas = totais['receitas'] or Decimal('0.00')
    despesas = totais['despesas'] or Decimal('0.00')
    saldo_atual = receitas - despesas

    context = {
        'titulo': 'Fluxo de Caixa',
        'saldo': saldo_atual,
        'receitas': receitas,
        'despesas': despesas,
        'ultimas_transacoes': transacoes_mes.select_related('categoria').order_by('-data', '-id')[:5],
        'form': form,
        'mes_atual': today.strftime('%B').capitalize(),
    }
    return render(request, 'financeiro/dashboard.html', context)


# ==============================================================================
# 2. HISTÓRICO E CRUD
# ==============================================================================

@login_required
def historico_transacoes(request: HttpRequest) -> HttpResponse:
    """
    Listagem consolidada com filtros dinâmicos de período e tipo.
    """
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    tipo_filtro = request.GET.get('tipo')

    today = date.today()

    if not start_date_str:
        start_date = today - timedelta(days=6)
        end_date = today
    else:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            start_date = today - timedelta(days=6)
            end_date = today

    queryset = Transacao.objects.select_related('categoria').filter(
        data__range=(start_date, end_date)
    ).order_by('-data', '-id')

    if tipo_filtro in ['receita', 'despesa']:
        queryset = queryset.filter(categoria__tipo=tipo_filtro)

    # Cálculo do saldo do período filtrado
    totais = queryset.aggregate(
        receitas=Sum('valor', filter=Q(categoria__tipo='receita')),
        despesas=Sum('valor', filter=Q(categoria__tipo='despesa'))
    )
    total_periodo = (totais['receitas'] or Decimal('0.00')) - (totais['despesas'] or Decimal('0.00'))

    context = {
        'titulo': 'Histórico de Lançamentos',
        'transacoes': queryset,
        'start_date': start_date.strftime('%Y-%m-%d'),
        'end_date': end_date.strftime('%Y-%m-%d'),
        'total_periodo': total_periodo,
        'tipo_filtro': tipo_filtro or ''
    }
    return render(request, 'financeiro/historico.html', context)


@login_required
def editar_transacao(request: HttpRequest, pk: int) -> HttpResponse:
    transacao = get_object_or_404(Transacao, pk=pk)
    
    if request.method == 'POST':
        form = TransacaoForm(request.POST, instance=transacao, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Registro atualizado com sucesso.")
            return redirect('historico_transacoes')
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
    transacao = get_object_or_404(Transacao, pk=pk)
    transacao.delete()
    messages.success(request, "Lançamento removido.")
    return redirect('historico_transacoes')


# ==============================================================================
# 3. APIS AJAX & INTEGRAÇÕES
# ==============================================================================

@login_required
def toggle_pago(request: HttpRequest, pk: int) -> HttpResponse:
    transacao = get_object_or_404(Transacao, pk=pk)
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
    Fornece dados estruturados para o Chart.js.
    Utiliza o ORM para agrupar e somar gastos sem usar loops Python.
    """
    today = date.today()
    
    dados = Transacao.objects.filter(
        data__month=today.month, 
        data__year=today.year,
        categoria__tipo='despesa'
    ).values('categoria__nome').annotate(total=Sum('valor')).order_by('-total')

    labels = [item['categoria__nome'] for item in dados]
    values = [float(item['total']) for item in dados]

    return JsonResponse({'labels': labels, 'values': values})


@login_required
def consolidar_transacao_ajax(request: HttpRequest, pk: int) -> JsonResponse:
    if request.method != 'POST':
        return JsonResponse({'status': 'invalid_method'}, status=405)

    try:
        data = json.loads(request.body)
        categoria_id = data.get('categoria_id')
        criar_regra = data.get('criar_regra', False)
        
        transacao = get_object_or_404(Transacao, pk=pk)
        categoria = get_object_or_404(Categoria, pk=categoria_id)
        
        transacao.categoria = categoria
        transacao.status_auditoria = 'consolidado'
        transacao.save(update_fields=['categoria', 'status_auditoria'])
        
        if criar_regra:
            desc_limpa = transacao.descricao.replace("Compra no débito - ", "") \
                                            .replace("Transferência enviada pelo Pix - ", "") \
                                            .replace("Transferência recebida pelo Pix - ", "") \
                                            .strip()
            RegraClassificacao.objects.get_or_create(
                palavra_chave=desc_limpa,
                defaults={'categoria': categoria}
            )
        return JsonResponse({'status': 'success'})
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'mensagem': str(e)}, status=400)


# ==============================================================================
# 4. EXPORTAÇÃO EXCEL & IMPORTAÇÃO
# ==============================================================================

@login_required
def exportar_financas_excel(request: HttpRequest) -> HttpResponse:
    """
    Gera relatório estruturado em formato .xlsx.
    """
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    queryset = Transacao.objects.select_related('categoria').all().order_by('data')

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

    headers = ["Data", "Descrição", "Categoria", "Tipo", "Valor (R$)", "Status", "Fixo?"]
    ws.append(headers)

    header_fill = PatternFill(start_color="4F46E5", end_color="4F46E5", fill_type="solid")
    white_font = Font(bold=True, color="FFFFFF")
    
    for cell in ws[1]:
        cell.font = white_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center')

    for item in queryset:
        tipo_str = "ENTRADA" if item.categoria.tipo == 'receita' else "SAÍDA"
        status_str = "PAGO" if item.pago else "PENDENTE"
        fixo_str = "SIM" if item.fixo else "-"

        row = [
            item.data.strftime('%d/%m/%Y'), 
            item.descricao, 
            item.categoria.nome, 
            tipo_str, 
            item.valor, 
            status_str, 
            fixo_str
        ]
        ws.append(row)

        current_row = ws.max_row
        valor_cell = ws.cell(row=current_row, column=5)
        valor_cell.number_format = '#,##0.00'

        if item.categoria.tipo == 'receita':
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
def importar_extrato(request: HttpRequest) -> HttpResponse:
    if request.method == 'POST' and request.FILES.get('extrato'):
        arquivo = request.FILES['extrato']
        if not arquivo.name.endswith('.csv'):
            messages.error(request, "Por favor, envie um arquivo CSV.")
            return redirect('importar_extrato')

        try:
            resultado = processar_extrato_nubank(arquivo)
            messages.success(request, f"Importação concluída! {resultado['novos']} novos lançamentos.")
        except Exception as e:
            messages.error(request, "Falha ao processar o arquivo de extrato.")
            
        return redirect('importar_extrato')
    
    context = {
        'lotes': LoteImportacao.objects.all().order_by('-data_importacao'),
        'qtd_pendente': Transacao.objects.filter(status_auditoria='pendente').count(),
    }
    return render(request, 'financeiro/importar.html', context)


@login_required
def excluir_lote(request: HttpRequest, pk: int) -> HttpResponse:
    lote = get_object_or_404(LoteImportacao, pk=pk)
    lote.delete()
    messages.success(request, "Arquivo e lançamentos removidos com sucesso.")
    return redirect('importar_extrato')


@login_required
def tela_auditoria(request: HttpRequest) -> HttpResponse:
    pendencias = Transacao.objects.filter(status_auditoria='pendente').order_by('data')
    context = {
        'titulo': 'Auditoria de Lançamentos',
        'pendencias': pendencias,
        'categorias': Categoria.objects.all().order_by('nome'),
        'qtd_pendente': pendencias.count()
    }
    return render(request, 'financeiro/auditoria.html', context)


# ==============================================================================
# 5. CONTROLADORIA (CARRY-OVER E PREVISIBILIDADE)
# ==============================================================================

def _calcular_status_despesa_fixa(despesa: DespesaFixa, today: date) -> List[Dict[str, Any]]:
    """
    Função Helper Privada para limpar a View `controle_gastos_fixos`.
    Gera a timeline da despesa aplicando lógica de Carry-over.
    """
    eventos = []
    
    # 1. TRATAMENTO PARA CONTAS FUTURAS
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
            'valido_mes_atual': False # Flag para ignorar na soma do dashboard
        })
        return eventos

    # 2. CÁLCULO DE DÍVIDA ACUMULADA (CARRY-OVER)
    meses_passados = (today.year - despesa.data_inicio.year) * 12 + (today.month - despesa.data_inicio.month) + 1
    if despesa.data_fim:
        meses_totais = (despesa.data_fim.year - despesa.data_inicio.year) * 12 + (despesa.data_fim.month - despesa.data_inicio.month) + 1
        meses_passados = min(meses_passados, meses_totais)

    esperado_historico = Decimal(meses_passados) * despesa.valor_previsto
    pago_historico = Transacao.objects.filter(despesa_fixa=despesa, pago=True).aggregate(Sum('valor'))['valor__sum'] or Decimal('0.00')
    falta_pagar = max(Decimal('0.00'), esperado_historico - Decimal(str(pago_historico)))

    # 3. LINHA DO TEMPO DOS CARDS MÊS ATUAL
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

    # 4. PREVISÃO DO MÊS SEGUINTE (Se já pagou o atual)
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
    today = date.today()
    despesas_ativas = DespesaFixa.objects.filter(ativo=True)

    painel = []
    total_previsto = Decimal('0.00')
    total_pago_mes = Decimal('0.00')
    total_falta = Decimal('0.00')

    for despesa in despesas_ativas:
        eventos_despesa = _calcular_status_despesa_fixa(despesa, today)
        painel.extend(eventos_despesa)
        
        # Consolida valores do mês atual baseado nos eventos retornados
        for evento in eventos_despesa:
            if evento.get('valido_mes_atual'):
                pago_este_mes = Transacao.objects.filter(
                    despesa_fixa=despesa, data__month=today.month, data__year=today.year, pago=True
                ).aggregate(Sum('valor'))['valor__sum'] or Decimal('0.00')
                
                total_falta += evento['falta_pagar']
                total_pago_mes += Decimal(str(pago_este_mes))
                total_previsto += evento['falta_pagar'] + Decimal(str(pago_este_mes))

    painel.sort(key=lambda x: x['data_vencimento'])

    context = {
        'titulo': 'Custos Fixos',
        'painel': painel,
        'total_previsto': total_previsto,
        'total_pago': total_pago_mes,
        'restante': total_falta,
    }
    return render(request, 'financeiro/gastos_fixos.html', context)