import re
import pandas as pd
from decimal import Decimal
from typing import Tuple, Dict, Any, List

from django.db import transaction
from .models import Transacao, Categoria, MacroCategoria, RegraClassificacao, LoteImportacao


def classificar_nubank_inteligente(
    descricao_original: str, 
    valor_original: float, 
    regras_compiladas: List[Tuple[re.Pattern, RegraClassificacao]],
    cat_entrada_padrao: Categoria,
    cat_saida_padrao: Categoria
) -> Tuple[Categoria, str, str]:
    """
    Motor de inteligência financeira.
    Usa o valor como fonte da verdade absoluta para definir o fluxo do caixa.
    """
    descricao = str(descricao_original).upper()
    valor = float(valor_original)

    for padrao_regex, regra in regras_compiladas:
        if padrao_regex.search(descricao):
            is_receita_valida = (valor > 0 and regra.categoria.macro_categoria.tipo == 'receita')
            is_despesa_valida = (valor < 0 and regra.categoria.macro_categoria.tipo == 'despesa')
            
            if is_receita_valida or is_despesa_valida:
                return regra.categoria, Transacao.StatusAuditoria.CONSOLIDADO, 'Classificação Automática via RegEx'

    if valor > 0 or "RECEBID" in descricao:
        if "PIX" in descricao or "TRANSFER" in descricao:
            return cat_entrada_padrao, Transacao.StatusAuditoria.PENDENTE, 'Entrada via Pix exige revisão'
        return cat_entrada_padrao, Transacao.StatusAuditoria.PENDENTE, 'Entrada não identificada'

    else:
        if "PIX" in descricao and "ENVIAD" in descricao:
            return cat_saida_padrao, Transacao.StatusAuditoria.PENDENTE, 'Pix enviado exige revisão'
        return cat_saida_padrao, Transacao.StatusAuditoria.PENDENTE, 'Saída não identificada'


@transaction.atomic
def processar_extrato_nubank(arquivo_csv: Any, usuario: Any) -> Dict[str, int]:
    """
    Processa o CSV do Nubank, garantindo a consistência e integridade dos dados via Atomic Transaction.
    Faz cache de categorias e regras do usuário em memória para evitar N+1 queries.
    """
    df = pd.read_csv(arquivo_csv, encoding='utf-8')
    df.columns = ['data', 'valor', 'identificador', 'descricao']
    
    estatisticas = {'novos': 0, 'duplicados': 0, 'categorias_automaticas': 0}

    lote_atual = LoteImportacao.objects.create(
        arquivo_nome=arquivo_csv.name,
        usuario=usuario
    )
    macro_entrada, _ = MacroCategoria.objects.get_or_create(
        usuario=usuario,
        nome="A Classificar (Entradas)",
        tipo=MacroCategoria.Tipo.RECEITA,
        defaults={'ordem': 99, 'ativo': False}
    )
    cat_entrada_padrao, _ = Categoria.objects.get_or_create(
        usuario=usuario,
        macro_categoria=macro_entrada,
        nome="Entrada Genérica", 
        defaults={'icone': 'bi-plus-circle', 'ativo': False}
    )
    macro_saida, _ = MacroCategoria.objects.get_or_create(
        usuario=usuario,
        nome="A Classificar (Saídas)",
        tipo=MacroCategoria.Tipo.DESPESA,
        defaults={'ordem': 99, 'ativo': False}
    )
    cat_saida_padrao, _ = Categoria.objects.get_or_create(
        usuario=usuario,
        macro_categoria=macro_saida,
        nome="Saída Genérica", 
        defaults={'icone': 'bi-dash-circle', 'ativo': False}
    )

    regras_db = RegraClassificacao.objects.select_related('categoria__macro_categoria').filter(usuario=usuario)
    
    regras_compiladas = [
        (re.compile(r'\b' + re.escape(regra.palavra_chave.upper()) + r'\b.*'), regra)
        for regra in regras_db
    ]

    for _, row in df.iterrows():
        valor_str = str(row['valor']).replace(',', '.')
        valor_original = float(valor_str)
        valor_limpo = abs(Decimal(str(valor_original)))
        
        categoria, status, motivo = classificar_nubank_inteligente(
            descricao_original=row['descricao'], 
            valor_original=valor_original,
            regras_compiladas=regras_compiladas,
            cat_entrada_padrao=cat_entrada_padrao,
            cat_saida_padrao=cat_saida_padrao
        )
        
        transacao, created = Transacao.objects.get_or_create(
            usuario=usuario,
            identificador_extrato=row['identificador'],
            defaults={
                'descricao': row['descricao'],
                'valor': valor_limpo,
                'data': pd.to_datetime(row['data'], format='%d/%m/%Y').date(),
                'categoria': categoria,
                'pago': True,
                'status_auditoria': status,
                'motivo_auditoria': motivo,
                'lote': lote_atual,
                'importada_automatica': True
            }
        )

        if created:
            estatisticas['novos'] += 1
            if status == Transacao.StatusAuditoria.CONSOLIDADO:
                estatisticas['categorias_automaticas'] += 1
        else:
            estatisticas['duplicados'] += 1

    return estatisticas