import re
import pandas as pd
from decimal import Decimal
from typing import Tuple, Dict, Any, List

from django.db import transaction
from .models import Transacao, Categoria, RegraClassificacao, LoteImportacao


def classificar_nubank_inteligente(
    descricao_original: str, 
    valor_original: float, 
    regras_compiladas: List[Tuple[re.Pattern, RegraClassificacao]],
    cat_entrada_padrao: Categoria,
    cat_saida_padrao: Categoria
) -> Tuple[Categoria, str, str]:
    """
    Motor de inteligência financeira (Função Pura).
    Usa o valor como fonte da verdade absoluta para definir o fluxo do caixa.
    
    Args:
        descricao_original: Descrição que vem no CSV do banco.
        valor_original: Valor exato, onde > 0 é Receita e < 0 é Despesa.
        regras_compiladas: Lista de tuplas contendo o Regex compilado e a instância da Regra.
        cat_entrada_padrao: Categoria de fallback para receitas desconhecidas.
        cat_saida_padrao: Categoria de fallback para despesas desconhecidas.
        
    Returns:
        Uma tupla contendo: (Categoria, Status da Auditoria, Motivo da Auditoria)
    """
    descricao = str(descricao_original).upper()
    valor = float(valor_original)

    # 1. BUSCA POR REGRA EXATA/VARIAÇÕES (Regex pré-compilado na memória)
    for padrao_regex, regra in regras_compiladas:
        if padrao_regex.search(descricao):
            # Encontrou a regra! Garante que o tipo da regra bate com o sinal do dinheiro
            is_receita_valida = (valor > 0 and regra.categoria.tipo == 'receita')
            is_despesa_valida = (valor < 0 and regra.categoria.tipo == 'despesa')
            
            if is_receita_valida or is_despesa_valida:
                return regra.categoria, Transacao.StatusAuditoria.CONSOLIDADO, 'Classificação Automática via RegEx'

    # 2. REGRAS DE OURO DO PIX E FALLBACKS (Nada foi encontrado no Regex)
    if valor > 0 or "RECEBID" in descricao:
        if "PIX" in descricao or "TRANSFER" in descricao:
            return cat_entrada_padrao, Transacao.StatusAuditoria.PENDENTE, 'Entrada via Pix exige revisão'
        return cat_entrada_padrao, Transacao.StatusAuditoria.PENDENTE, 'Entrada não identificada'

    else:
        if "PIX" in descricao and "ENVIAD" in descricao:
            return cat_saida_padrao, Transacao.StatusAuditoria.PENDENTE, 'Pix enviado exige revisão'
        return cat_saida_padrao, Transacao.StatusAuditoria.PENDENTE, 'Saída não identificada'


@transaction.atomic
def processar_extrato_nubank(arquivo_csv: Any) -> Dict[str, int]:
    """
    Processa o CSV do Nubank, garantindo a idempotência e integridade dos dados via Atomic Transaction.
    Faz cache de categorias e regras em memória para evitar o problema de queries N+1.
    """
    df = pd.read_csv(arquivo_csv, encoding='utf-8')
    df.columns = ['data', 'valor', 'identificador', 'descricao']
    
    estatisticas = {'novos': 0, 'duplicados': 0, 'categorias_automaticas': 0}

    # 1. Cria o Lote de Importação
    lote_atual = LoteImportacao.objects.create(arquivo_nome=arquivo_csv.name)

    # =========================================================================
    # FASE DE CACHE (Evita milhares de consultas ao Banco de Dados)
    # =========================================================================
    cat_entrada_padrao, _ = Categoria.objects.get_or_create(
        nome="A Classificar (Entrada)", 
        defaults={'tipo': 'receita', 'icone': 'bi-plus-circle'}
    )
    
    cat_saida_padrao, _ = Categoria.objects.get_or_create(
        nome="A Classificar (Saída)", 
        defaults={'tipo': 'despesa', 'icone': 'bi-dash-circle'}
    )

    # Traz todas as regras e compila o Regex de uma vez só
    regras_db = RegraClassificacao.objects.select_related('categoria').all()
    regras_compiladas = [
        (re.compile(r'\b' + re.escape(regra.palavra_chave.upper()) + r'\b.*'), regra)
        for regra in regras_db
    ]

    # =========================================================================
    # FASE DE PROCESSAMENTO (ETL)
    # =========================================================================
    for _, row in df.iterrows():
        # Tratamento de valores para garantir formato Decimal correto
        valor_str = str(row['valor']).replace(',', '.')
        valor_original = float(valor_str)
        valor_limpo = abs(Decimal(str(valor_original)))
        
        # Inteligência de categorização (Passando dados em memória, sem queries extras)
        categoria, status, motivo = classificar_nubank_inteligente(
            descricao_original=row['descricao'], 
            valor_original=valor_original,
            regras_compiladas=regras_compiladas,
            cat_entrada_padrao=cat_entrada_padrao,
            cat_saida_padrao=cat_saida_padrao
        )
        
        # A MAGIA DA IDEMPOTÊNCIA: get_or_create
        transacao, created = Transacao.objects.get_or_create(
            identificador_extrato=row['identificador'],
            defaults={
                'descricao': row['descricao'],
                'valor': valor_limpo,
                'data': pd.to_datetime(row['data']).date(),
                'categoria': categoria,
                'pago': True,
                'status_auditoria': status,
                'motivo_auditoria': motivo,
                'lote': lote_atual,
                'importada_automatica': True
            }
        )

        # Atualiza métricas
        if created:
            estatisticas['novos'] += 1
            if status == Transacao.StatusAuditoria.CONSOLIDADO:
                estatisticas['categorias_automaticas'] += 1
        else:
            estatisticas['duplicados'] += 1

    return estatisticas