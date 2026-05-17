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
from .forms import DespesaFixaForm, TransacaoForm


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

    context = {
        'titulo': 'Histórico de Lançamentos',
        'transacoes': queryset,
        'start_date': start_date.strftime('%Y-%m-%d') if start_date else '',
        'end_date': end_date.strftime('%Y-%m-%d') if end_date else '',
        'total_periodo': total_periodo,
        'tipo_filtro': tipo_filtro or '',
        'filtro_ativo': filtro_ativo,
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
def importar_extrato(request: HttpRequest) -> HttpResponse:
    """
    Importa um extrato financeiro (arquivo CSV) e processa as transações.
    """
    if request.method == 'POST' and request.FILES.get('extrato'):
        arquivo = request.FILES['extrato']
        if not arquivo.name.endswith('.csv'):
            messages.error(request, "Por favor, envie um arquivo CSV.")
            return redirect('importar_extrato')

        try:
            resultado = processar_extrato_nubank(arquivo, usuario=request.user)
            messages.success(request, f"Importação concluída! {resultado['novos']} novos lançamentos.")
        except Exception as e:
            messages.error(request, f"Falha ao processar o arquivo: {e}")
            
        return redirect('importar_extrato')
    
    context = {
        'lotes': LoteImportacao.objects.filter(usuario=request.user).order_by('-data_importacao'),
        'qtd_pendente': Transacao.objects.filter(usuario=request.user, status_auditoria='pendente').count(),
    }
    return render(request, 'financeiro/importar.html', context)


@login_required
def excluir_lote(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Exclui um lote de importação e todas as transações associadas.
    """
    lote = get_object_or_404(LoteImportacao, pk=pk, usuario=request.user)
    lote.delete()
    messages.success(request, "Arquivo e lançamentos removidos com sucesso.")
    return redirect('importar_extrato')


@login_required
def tela_auditoria(request: HttpRequest) -> HttpResponse:
    """
    Tela de auditoria, onde o usuário pode revisar e categorizar manualmente as transações pendentes.
    """
    pendencias = Transacao.objects.select_related('categoria__macro_categoria').filter(
        usuario=request.user, 
        status_auditoria='pendente'
    ).order_by('data')
    
    categorias = Categoria.objects.select_related('macro_categoria').filter(
        usuario=request.user, 
        ativo=True
    ).order_by('macro_categoria__ordem', 'nome')
    
    context = {
        'titulo': 'Auditoria de Lançamentos',
        'pendencias': pendencias,
        'categorias': categorias,
        'qtd_pendente': pendencias.count()
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
    
    despesas_ativas = DespesaFixa.objects.filter(usuario=user, ativo=True)

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

    categorias = Categoria.objects.filter(usuario=user, ativo=True).order_by('nome')

    context = {
        'titulo': 'Custos Fixos',
        'painel': painel,
        'total_previsto': total_previsto,
        'total_pago': total_pago_mes,
        'restante': total_falta,
        'categorias': categorias,
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
    return redirect('controle_gastos_fixos')

@login_required
def buscar_transacoes_ajax(request: HttpRequest) -> JsonResponse:
    """
    Busca as transações dos últimos 60 dias para o Modal de Vínculo Fixo.
    Permite filtrar por termo de descrição para facilitar a localização.
    """
    termo = request.GET.get('q', '').strip()
    data_limite = date.today() - timedelta(days=60)
    
    query = Q(usuario=request.user, data__gte=data_limite, categoria__macro_categoria__tipo='despesa')
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
            'data': t.data.strftime('%d/%m/%Y')
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
    return redirect('controle_gastos_fixos')

@login_required
def excluir_despesa_fixa(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Exclui a despesa fixa
    """
    despesa = get_object_or_404(DespesaFixa, pk=pk, usuario=request.user)
    if request.method == 'POST':
        despesa.delete() 
        messages.success(request, "Conta fixa removida.")
    return redirect('controle_gastos_fixos')

@login_required
def desvincular_transacao_ajax(request: HttpRequest, pk: int) -> JsonResponse:
    """
    Desvincula uma transação da despesa fixa (sem excluir a transação)
    """
    if request.method == 'POST':
        transacao = get_object_or_404(Transacao, pk=pk, usuario=request.user)
        transacao.despesa_fixa = None # Rompe o vínculo
        transacao.save(update_fields=['despesa_fixa'])
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'error'}, status=400)