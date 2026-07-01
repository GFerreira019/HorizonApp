import re
import logging
import requests
import pandas as pd
from decimal import Decimal
from datetime import date, timedelta
from typing import Tuple, Dict, Any, List, Optional

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from .models import (
    Transacao, Categoria, MacroCategoria, RegraClassificacao,
    LoteImportacao, ConexaoBancaria, LimiteTemporario,
    OrcamentoCategoria, PlanejamentoMensal,
    DespesaFixa, ReceitaPlanejada,
)
from . import telegram_bot

logger = logging.getLogger(__name__)


# =============================================================================
# Automação de Classificação — Regras e Reclassificação Retroativa
# =============================================================================

def _extrair_palavra_chave(descricao: str) -> str:
    """
    Extrai e normaliza a palavra-chave de uma descrição de transação bancária.

    Segue a "Regra de Ouro" do .cursorrules: remove prefixos ruidosos
    ("Compra no débito - ", "Pix enviado - ", etc.) usando split por " - ".
    Esta é a função canônica de limpeza do projeto — alinhada com
    `_normalizar_transacao_pluggy` e `buscar_transacoes_ajax`.

    Args:
        descricao: Descrição original da transação (ex: "Compra no débito - Netflix").

    Returns:
        Palavra-chave limpa e sem espaços extras (ex: "Netflix").
    """
    if ' - ' in descricao:
        return descricao.split(' - ', 1)[-1].strip()
    return descricao.strip()


def criar_regra_e_reclassificar(
    usuario: Any,
    transacao_padrao: 'Transacao',
    categoria: 'Categoria',
    despesa_fixa: Optional['DespesaFixa'] = None,
    receita_planejada: Optional['ReceitaPlanejada'] = None,
) -> int:
    """
    Cria ou atualiza uma RegraClassificacao e aplica reclassificação retroativa
    em batch em todas as transações históricas pendentes do utilizador.

    Deve ser chamada logo após o salvamento bem-sucedido de um provisionamento
    (DespesaFixa ou ReceitaPlanejada) quando o utilizador vinculou uma
    transação padrão.

    Regras de negócio:
        - A palavra-chave é extraída via `_extrair_palavra_chave`, eliminando
          prefixos ruidosos ("Pix enviado - ", "Compra no débito - ", etc.).
        - Se já existir uma RegraClassificacao com a mesma palavra-chave,
          os campos de vínculo (despesa_vinculada / receita_vinculada) são
          atualizados sem duplicar a regra (unique_together garante isso).
        - O batch update retroativo atualiza APENAS transações com
          `status_auditoria='pendente'` e `ignorado=False`, protegendo
          classificações manuais já consolidadas pelo utilizador.
        - A transação padrão é sempre incluída no batch, independente
          do seu status_auditoria.

    Args:
        usuario: Instância do utilizador autenticado (multi-tenant safety).
        transacao_padrao: Transação de referência selecionada pelo utilizador.
        categoria: Categoria do provisionamento recém-salvo.
        despesa_fixa: Instância de DespesaFixa, se aplicável.
        receita_planejada: Instância de ReceitaPlanejada, se aplicável.

    Returns:
        Número de transações reclassificadas pelo batch update.
    """
    from django.db.models import Q

    palavra_chave = _extrair_palavra_chave(transacao_padrao.descricao)

    # ── 1. Criação/atualização da RegraClassificacao ─────────────────────
    # unique_together = ['usuario', 'palavra_chave'] garante idempotência.
    defaults_regra: Dict[str, Any] = {'categoria': categoria}
    if despesa_fixa:
        defaults_regra['despesa_vinculada'] = despesa_fixa
    if receita_planejada:
        defaults_regra['receita_vinculada'] = receita_planejada

    regra, created = RegraClassificacao.objects.get_or_create(
        usuario=usuario,
        palavra_chave=palavra_chave,
        defaults=defaults_regra,
    )

    if not created:
        # Atualiza os vínculos mesmo que a regra existisse para outro provisionamento.
        # O campo 'categoria' é sempre sincronizado para refletir o provisionamento atual.
        update_fields = ['categoria']
        regra.categoria = categoria
        if despesa_fixa:
            regra.despesa_vinculada = despesa_fixa
            update_fields.append('despesa_vinculada')
        if receita_planejada:
            regra.receita_vinculada = receita_planejada
            update_fields.append('receita_vinculada')
        regra.save(update_fields=update_fields)

    logger.info(
        '%s RegraClassificacao "%s" -> categoria=%s (user=%s)',
        'Criada' if created else 'Atualizada',
        palavra_chave,
        categoria.nome,
        usuario.pk,
    )

    # ── 2. Batch update retroativo ────────────────────────────────────────
    # Inclui sempre a transação padrão (referência do utilizador) + todas
    # as transações pendentes cuja descrição case com a palavra-chave.
    # Transações já 'consolidado' pelo utilizador NÃO são sobrescritas.
    filtro_batch = Q(id=transacao_padrao.id) | Q(
        descricao__icontains=palavra_chave,
        status_auditoria=Transacao.StatusAuditoria.PENDENTE,
        ignorado=False,
    )

    campos_update: Dict[str, Any] = {
        'categoria': categoria,
        'status_auditoria': Transacao.StatusAuditoria.CONSOLIDADO,
    }
    if despesa_fixa:
        campos_update['despesa_fixa'] = despesa_fixa
    if receita_planejada:
        campos_update['receita_planejada'] = receita_planejada

    # Isolamento multi-tenant: filtra SEMPRE pelo utilizador atual.
    qtd_atualizadas = Transacao.objects.filter(
        filtro_batch,
        usuario=usuario,
    ).update(**campos_update)

    logger.info(
        'Reclassificacao retroativa: %d transacoes atualizadas para "%s" (user=%s)',
        qtd_atualizadas,
        palavra_chave,
        usuario.pk,
    )

    return qtd_atualizadas


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
            # Gatilho Telegram: verifica limites/orçamentos após nova transação
            verificar_limite_e_notificar(transacao)
        else:
            estatisticas['duplicados'] += 1

    return estatisticas


# =============================================================================
# Gatilho de Notificações — Verificação de Limites e Orçamentos
# =============================================================================

def verificar_limite_e_notificar(transacao: 'Transacao') -> None:
    """
    Verifica se uma nova transação compromete Limites Temporários ou Orçamentos
    de Categoria do utilizador, e dispara notificações via Telegram se necessário.

    Essa função deve ser chamada APÓS cada transação ser salva com sucesso no BD.
    É fail-safe: erros de notificação são logados mas nunca propagados.

    Regras de negócio:
        1. Limites Temporários:
           - Calcula o valor_consumido real (soma das transações no período/categoria).
           - Dispara alerta quando ≥ 80% ou ≥ 100% do limite.
           - Marca `notificacao_enviada=True` para evitar alertas duplicados.

        2. Orçamento por Categoria (PlanejamentoMensal):
           - Compara o gasto real do mês na MacroCategoria com o valor planejado.
           - Dispara alerta quando o gasto real ultrapassa o orçamento.

    Args:
        transacao: Instância de Transacao já salva no banco de dados.
    """
    usuario = transacao.usuario

    # Apenas despesas disparam alertas (receitas não comprometem limites)
    try:
        macro_tipo = transacao.categoria.macro_categoria.tipo
    except Exception:  # noqa: BLE001
        return

    if macro_tipo != 'despesa':
        return

    # ── 1. Verificar Limites Temporários ──────────────────────────────────
    try:
        limites_ativos = LimiteTemporario.objects.ativos_para_usuario(usuario)

        for limite in limites_ativos:
            # Limites já notificados são ignorados
            if limite.notificacao_enviada:
                continue

            # Verifica escopo: global (categoria_alvo=None) ou por categoria
            if limite.categoria_alvo_id and limite.categoria_alvo_id != transacao.categoria_id:
                continue

            # Recalcula valor_consumido real a partir das transações no período
            filtro_consumo = Transacao.objects.filter(
                usuario=usuario,
                data__gte=limite.data_inicio,
                data__lte=limite.data_fim,
                categoria__macro_categoria__tipo='despesa',
                ignorado=False
            )
            if limite.categoria_alvo_id:
                filtro_consumo = filtro_consumo.filter(categoria=limite.categoria_alvo)

            soma = filtro_consumo.aggregate(
                total=Sum('valor')
            )['total'] or Decimal('0.00')

            # Atualiza o valor_consumido no modelo para consistência do dashboard
            LimiteTemporario.objects.filter(pk=limite.pk).update(valor_consumido=soma)

            # Recarrega para propriedades calculadas
            limite.refresh_from_db()

            # Threshold: notifica a partir de 80% de consumo
            if limite.percentual_consumido >= 80:
                sucesso = telegram_bot.notificar_limite_excedido(
                    usuario=usuario,
                    limite=limite,
                    transacao_descricao=transacao.descricao,
                    transacao_valor=transacao.valor,
                )
                if sucesso:
                    LimiteTemporario.objects.filter(pk=limite.pk).update(
                        notificacao_enviada=True,
                    )
                    logger.info(
                        'Alerta de limite enviado para user=%s, limite=%s (%.1f%%)',
                        usuario.pk, limite.pk, limite.percentual_consumido,
                    )

    except Exception as exc:  # noqa: BLE001
        logger.error('Erro ao verificar limites temporários para user=%s: %s', usuario.pk, exc)

    # ── 2. Verificar Orçamento de Categoria ───────────────────────────────
    try:
        hoje = transacao.data
        planejamento = PlanejamentoMensal.objects.filter(
            usuario=usuario,
            mes=hoje.month,
            ano=hoje.year,
        ).first()

        if planejamento:
            macro_cat = transacao.categoria.macro_categoria
            orcamento = OrcamentoCategoria.objects.filter(
                planejamento=planejamento,
                macro_categoria=macro_cat,
            ).first()

            if orcamento and orcamento.valor_planejado > 0:
                # Soma real de gastos na MacroCategoria neste mês
                gasto_real = Transacao.objects.filter(
                    usuario=usuario,
                    data__month=hoje.month,
                    data__year=hoje.year,
                    categoria__macro_categoria=macro_cat,
                    ignorado=False
                ).aggregate(
                    total=Sum('valor')
                )['total'] or Decimal('0.00')

                if gasto_real > orcamento.valor_planejado:
                    telegram_bot.notificar_orcamento_excedido(
                        usuario=usuario,
                        macro_nome=macro_cat.nome,
                        valor_planejado=orcamento.valor_planejado,
                        valor_realizado=gasto_real,
                        transacao_descricao=transacao.descricao,
                        transacao_valor=transacao.valor,
                    )
                    logger.info(
                        'Alerta de orçamento enviado para user=%s, macro=%s (R$ %.2f / R$ %.2f)',
                        usuario.pk, macro_cat.nome, gasto_real, orcamento.valor_planejado,
                    )

    except Exception as exc:  # noqa: BLE001
        logger.error('Erro ao verificar orçamento para user=%s: %s', usuario.pk, exc)


# =============================================================================
# Open Finance — Pluggy Integration
# =============================================================================

class PluggyAPIClient:
    """
    Cliente HTTP leve para a API REST do Pluggy.

    Gerencia o ciclo de vida do access token (validade de 2h) internamente,
    evitando que o worker precise lidar com autenticação manualmente.

    Referência: https://docs.pluggy.ai/
    """
    BASE_URL = 'https://api.pluggy.ai'

    def __init__(self) -> None:
        self._client_id: str = settings.PLUGGY_CLIENT_ID
        self._client_secret: str = settings.PLUGGY_CLIENT_SECRET
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[float] = None

    def _autenticar(self) -> None:
        """
        Obtém um access token da Pluggy via client credentials.
        O token expira em 2h; renovado automaticamente quando necessário.
        """
        import time
        if self._access_token and self._token_expires_at and time.time() < self._token_expires_at:
            return  # Token ainda válido, não renova desnecessariamente.


        resp = requests.post(
            f'{self.BASE_URL}/auth',
            json={'clientId': self._client_id, 'clientSecret': self._client_secret},
            timeout=15,
        )
        resp.raise_for_status()
        import time as _time
        self._access_token = resp.json()['apiKey']
        # Pluggy tokens duram 2h; renovamos com 5 min de margem de segurança.
        self._token_expires_at = _time.time() + (2 * 3600) - 300

    def _headers(self) -> Dict[str, str]:
        self._autenticar()
        return {'X-API-KEY': self._access_token, 'Content-Type': 'application/json'}

    def buscar_transacoes(
        self,
        account_id: str,
        data_inicio: Optional[date] = None,
        data_fim: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """
        Busca todas as transações de uma conta específica com paginação automática.

        Args:
            account_id: ID da conta retornado pelo Pluggy.
            data_inicio: Data inicial do período (padrão: 30 dias atrás).
            data_fim: Data final do período (padrão: hoje).

        Returns:
            Lista de dicionários com os dados brutos da transação conforme schema Pluggy.

        Raises:
            requests.HTTPError: Se a API retornar erro 4xx/5xx.
        """
        hoje = date.today()
        params: Dict[str, Any] = {
            'accountId': account_id,
            'from': (data_inicio or (hoje - timedelta(days=30))).isoformat(),
            'to': (data_fim or hoje).isoformat(),
            'pageSize': 500,
            'page': 1,
        }
        todas: List[Dict[str, Any]] = []
        while True:
            resp = requests.get(f'{self.BASE_URL}/transactions', headers=self._headers(), params=params, timeout=20)
            resp.raise_for_status()
            payload = resp.json()
            todas.extend(payload.get('results', []))
            # Pluggy retorna `total` e `totalPages` para controle de paginação.
            if params['page'] >= payload.get('totalPages', 1):
                break
            params['page'] += 1
        return todas

    def buscar_saldos_contas(self, item_id: str) -> float:
        """
        Retorna a soma do saldo real de todas as contas (corrente, poupança, cartão) vinculadas a um item.
        """
        contas = self.buscar_contas_do_item(item_id)
        saldo_total = 0.0
        for conta in contas:
            # O Pluggy retorna o saldo em 'balance'.
            saldo = float(conta.get('balance', 0.0))
            saldo_total += saldo
        return saldo_total

    def buscar_contas_do_item(self, item_id: str) -> List[Dict[str, Any]]:
        """
        Retorna todas as contas (corrente, poupança, cartão) vinculadas a um item Pluggy.

        Args:
            item_id: Item ID armazenado em `ConexaoBancaria.item_id_externo`.

        Returns:
            Lista de dicionários de conta conforme schema Pluggy.
        """
        resp = requests.get(
            f'{self.BASE_URL}/accounts',
            headers=self._headers(),
            params={'itemId': item_id},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get('results', [])

    def buscar_status_item(self, item_id: str) -> Dict[str, Any]:
        """
        Consulta o status atual de um item no Pluggy.

        Returns:
            Dict com os campos `status` e `connector` do item.
        """
        resp = requests.get(f'{self.BASE_URL}/items/{item_id}', headers=self._headers(), timeout=10)
        resp.raise_for_status()
        return resp.json()

    def gerar_connect_token(self, item_id: Optional[str] = None) -> str:
        """
        Gera um Connect Token efêmero (~30 min) para inicializar o widget Pluggy Connect.

        O Connect Token é uma credencial de curta duração que o frontend usa para
        autenticar o fluxo de consentimento OAuth sem expor o Client Secret.

        Args:
            item_id: Se fornecido, o widget abre no modo de reconexão/atualização
                     de uma instituição já conectada (ex: token de login expirado).

        Returns:
            String com o connect token gerado pelo Pluggy.

        Raises:
            requests.HTTPError: Se a API retornar erro 4xx/5xx.
        """
        payload: Dict[str, Any] = {}
        if item_id:
            payload['itemId'] = item_id

        resp = requests.post(
            f'{self.BASE_URL}/connect_token',
            headers=self._headers(),
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()['accessToken']


def _normalizar_transacao_pluggy(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza o payload bruto de uma transação Pluggy para o formato interno.

    A Pluggy pode retornar valores positivos ou negativos dependendo do banco,
    e usa o campo `type` (DEBIT/CREDIT) para indicar o sentido. Garantimos 
    que o valor passado ao motor de classificação tenha o sinal correto.

    Args:
        raw: Dicionário bruto retornado pela API da Pluggy.

    Returns:
        Dicionário normalizado com chaves: id, descricao, valor_com_sinal, valor_absoluto, data.
    """
    valor_original = float(raw.get('amount', 0))
    is_debito = raw.get('type') == 'DEBIT' or valor_original < 0

    # Motor de classificação exige: Despesas = negativo, Receitas = positivo.
    valor_com_sinal = -abs(valor_original) if is_debito else abs(valor_original)

    # Segue estritamente a modelagem do `processar_extrato_nubank`:
    # O banco de dados guarda o valor sempre em módulo (positivo), pois a 
    # natureza (receita/despesa) é definida estruturalmente pela Categoria.
    valor_limpo = abs(Decimal(str(valor_original)))

    # Limpeza de descrição seguindo a regra de ouro do .cursorrules:
    # remove prefixos ruidosos como "Compra no débito -" e similares.
    descricao_raw = str(raw.get('description', '') or raw.get('name', 'Sem descrição'))
    descricao_limpa = descricao_raw.split(' - ', 1)[-1].strip() if ' - ' in descricao_raw else descricao_raw

    return {
        'id': raw['id'],
        'descricao': descricao_limpa[:200],  # Respeita o max_length do campo.
        'valor_com_sinal': valor_com_sinal,
        'valor_absoluto': valor_limpo,
        'data': date.fromisoformat(raw['date'][:10]),
    }


@transaction.atomic
def sincronizar_transacoes_open_finance(
    conexao: 'ConexaoBancaria',
    data_inicio: Optional[date] = None,
    data_fim: Optional[date] = None,
) -> Dict[str, int]:
    """
    Sincroniza as transações de uma conexão Open Finance com o banco de dados.

    Reutiliza o motor de classificação Regex (`classificar_nubank_inteligente`) para
    manter consistência com a experiência de importação manual. Todas as novas
    transações nascem com `status_auditoria='pendente'` para revisão humana.

    A idempotência é garantida pelo `id_transacao_externa` (ID opaco do Pluggy),
    nunca pelo conteúdo da transação, pois descrições e valores podem variar.

    Args:
        conexao: Instância de `ConexaoBancaria` a ser sincronizada.
        data_inicio: Data inicial do período. Padrão: 30 dias atrás.
        data_fim: Data final do período. Padrão: hoje.

    Returns:
        Dicionário com contadores: {'novos': int, 'duplicados': int, 'erros': int}.

    Raises:
        requests.HTTPError: Propagado se a API Pluggy retornar erro crítico.
    """
    usuario = conexao.usuario
    estatisticas: Dict[str, int] = {'novos': 0, 'duplicados': 0, 'erros': 0}

    # Carrega o cache de regras e categorias padrão uma única vez,
    # espelhando o padrão anti-N+1 de `processar_extrato_nubank`.
    macro_entrada, _ = MacroCategoria.objects.get_or_create(
        usuario=usuario, nome='A Classificar (Entradas)',
        tipo=MacroCategoria.Tipo.RECEITA, defaults={'ordem': 99, 'ativo': False},
    )
    cat_entrada_padrao, _ = Categoria.objects.get_or_create(
        usuario=usuario, macro_categoria=macro_entrada, nome='Entrada Genérica',
        defaults={'icone': 'bi-plus-circle', 'ativo': False},
    )
    macro_saida, _ = MacroCategoria.objects.get_or_create(
        usuario=usuario, nome='A Classificar (Saídas)',
        tipo=MacroCategoria.Tipo.DESPESA, defaults={'ordem': 99, 'ativo': False},
    )
    cat_saida_padrao, _ = Categoria.objects.get_or_create(
        usuario=usuario, macro_categoria=macro_saida, nome='Saída Genérica',
        defaults={'icone': 'bi-dash-circle', 'ativo': False},
    )
    regras_db = RegraClassificacao.objects.select_related('categoria__macro_categoria').filter(usuario=usuario)
    regras_compiladas = [
        (re.compile(r'\b' + re.escape(regra.palavra_chave.upper()) + r'\b.*'), regra)
        for regra in regras_db
    ]

    cliente = PluggyAPIClient()

    # Atualiza o status da conexão para refletir a sincronização em andamento.
    ConexaoBancaria.objects.filter(pk=conexao.pk).update(
        status=ConexaoBancaria.StatusConexao.UPDATING
    )

    try:
        # Busca todas as contas (corrente, poupança, cartão) deste item.
        contas = cliente.buscar_contas_do_item(conexao.item_id_externo)

        for conta in contas:
            transacoes_brutas = cliente.buscar_transacoes(
                account_id=conta['id'],
                data_inicio=data_inicio,
                data_fim=data_fim,
            )

            for raw_tx in transacoes_brutas:
                try:
                    dados = _normalizar_transacao_pluggy(raw_tx)

                    # Motor de classificação Regex reutilizado para consistência.
                    categoria, _status_sugerido, motivo = classificar_nubank_inteligente(
                        descricao_original=dados['descricao'],
                        valor_original=dados['valor_com_sinal'],
                        regras_compiladas=regras_compiladas,
                        cat_entrada_padrao=cat_entrada_padrao,
                        cat_saida_padrao=cat_saida_padrao,
                    )

                    # Regra de negócio crítica: independente da classificação,
                    # transações do Open Finance nascem SEMPRE pendentes para
                    # revisão humana, pois o banco tem origem externa.
                    transacao, created = Transacao.objects.get_or_create(
                        id_transacao_externa=dados['id'],
                        defaults={
                            'usuario': usuario,
                            'descricao': dados['descricao'],
                            'valor': dados['valor_absoluto'],
                            'data': dados['data'],
                            'categoria': categoria,
                            'pago': True,
                            'importada_automatica': True,
                            'conexao_origem': conexao,
                            'status_auditoria': Transacao.StatusAuditoria.PENDENTE,
                            'motivo_auditoria': f'[Open Finance] {motivo}',
                        },
                    )

                    if created:
                        estatisticas['novos'] += 1
                        logger.info(
                            'Nova transação Open Finance: %s | %s | R$ %s',
                            dados['id'], dados['descricao'], dados['valor_absoluto'],
                        )
                        # Gatilho Telegram: verifica limites/orçamentos após nova transação
                        verificar_limite_e_notificar(transacao)
                    else:
                        estatisticas['duplicados'] += 1

                except Exception as exc:  # noqa: BLE001
                    # Isola erros por transação para não cancelar o lote inteiro.
                    estatisticas['erros'] += 1
                    logger.error('Erro ao processar transação %s: %s', raw_tx.get('id', '?'), exc)

        # Consulta o status real do item após a sync para refletir no modelo.
        status_item = cliente.buscar_status_item(conexao.item_id_externo)
        status_pluggy = status_item.get('status', ConexaoBancaria.StatusConexao.UPDATED)

        ConexaoBancaria.objects.filter(pk=conexao.pk).update(
            status=status_pluggy,
            atualizado_em=timezone.now(),
        )

    except requests.HTTPError as exc:
        # Marca a conexão como desatualizada para alertar o usuário no dashboard.
        ConexaoBancaria.objects.filter(pk=conexao.pk).update(
            status=ConexaoBancaria.StatusConexao.LOGIN_ERROR
        )
        logger.exception('Falha crítica na sync da conexão %s: %s', conexao.pk, exc)
        raise

    logger.info(
        'Sync concluída para conexão %s (%s): %s',
        conexao.pk, conexao.instituicao_nome, estatisticas,
    )
    return estatisticas

# =============================================================================
# Módulo de Calendário e Envelopes
# =============================================================================

def get_despesas_calendario(usuario: Any, mes: int, ano: int) -> List[Dict[str, Any]]:
    """
    Retorna todas as despesas fixas ativas do usuário para um dado mês/ano,
    enriquecidas com o status de pagamento real daquele período.
    """
    from datetime import date
    from .models import DespesaFixa, Transacao
    
    data_ref = date(ano, mes, 1)
    despesas = DespesaFixa.objects.ativas_na_data(data_ref).filter(
        usuario=usuario,
        tem_vencimento=True
    ).only('id', 'nome', 'valor_previsto', 'dia_vencimento')

    ids_pagos: set[int] = set(
        Transacao.objects.filter(
            usuario=usuario,
            despesa_fixa__isnull=False,
            data__month=mes,
            data__year=ano,
            ignorado=False,
        ).values_list('despesa_fixa_id', flat=True)
    )

    resultado: List[Dict[str, Any]] = []
    for despesa in despesas:
        resultado.append({
            'id': despesa.id,
            'nome': despesa.nome,
            'valor': float(despesa.valor_previsto),
            'dia_vencimento': despesa.dia_vencimento,
            'pago': despesa.id in ids_pagos,
        })

    return resultado


def get_proximos_vencimentos(usuario: Any) -> List[Dict[str, Any]]:
    """
    Retorna as próximas 3 contas a vencer no mês corrente que ainda não foram pagas.
    """
    from datetime import date
    
    hoje = date.today()
    todas = get_despesas_calendario(usuario, hoje.month, hoje.year)

    proximas = [
        d for d in todas
        if not d['pago'] and d.get('dia_vencimento') is not None and d['dia_vencimento'] >= hoje.day
    ]
    proximas.sort(key=lambda d: d['dia_vencimento'])
    return proximas[:3]


def get_envelopes_progresso(usuario: Any, mes: int, ano: int) -> List[Dict[str, Any]]:
    """
    Retorna o progresso dos envelopes de orçamento (DespesaFixa com tem_vencimento=False)
    ativos para o usuário, cruzando com os gastos reais do mês/ano informado.

    Envelopes não possuem restrição de data por definição — o filtro é direto
    em tem_vencimento=False e ativo=True, sem usar ativas_na_data(), que pode
    excluir envelopes criados no meio do mês (data_inicio > 1º do mês).

    Lógica de Estorno:
        Gasto Efetivo = Soma(despesas normais) - Soma(estornos marcados como is_estorno=True)
    """
    from django.db.models import Sum, Q
    from decimal import Decimal
    from .models import DespesaFixa, Transacao

    # Filtro simples e direto — sem filtros de data que excluem envelopes válidos
    envelopes = DespesaFixa.objects.filter(
        usuario=usuario,
        tem_vencimento=False,
        ativo=True,
    ).select_related('categoria', 'macro_categoria')

    # Gastos normais por categoria (excluindo estornos)
    gastos_normais = (
        Transacao.objects.filter(
            usuario=usuario,
            data__month=mes,
            data__year=ano,
            ignorado=False,
            is_estorno=False,
        )
        .values('categoria_id')
        .annotate(total=Sum('valor'))
    )
    # Dicionário {categoria_id: Decimal(total_gasto_normal)}
    gastos_dict: dict = {
        item['categoria_id']: item['total'] or Decimal('0.00')
        for item in gastos_normais
    }

    # Estornos: abatidos do gasto normal da categoria correspondente
    estornos = (
        Transacao.objects.filter(
            usuario=usuario,
            data__month=mes,
            data__year=ano,
            ignorado=False,
            is_estorno=True,
        )
        .values('categoria_id')
        .annotate(total=Sum('valor'))
    )
    for item in estornos:
        cat_id = item['categoria_id']
        valor_estorno = item['total'] or Decimal('0.00')
        # Subtrai o estorno — garante que o saldo não fique negativo (mín. 0)
        gastos_dict[cat_id] = max(
            Decimal('0.00'),
            gastos_dict.get(cat_id, Decimal('0.00')) - valor_estorno
        )

    resultado = []
    for envelope in envelopes:
        valor_planejado = envelope.valor_previsto  # Decimal do banco
        valor_gasto = gastos_dict.get(envelope.categoria_id, Decimal('0.00'))

        
        porcentagem_real = 0
        porcentagem_barra = 0
        if valor_planejado > 0:
            porcentagem_real = (float(valor_gasto) / float(valor_planejado)) * 100
            porcentagem_barra = min(porcentagem_real, 100)

        valor_restante = float(valor_planejado) - float(valor_gasto)
        
        # Cores pré-calculadas para evitar comparadores >= no template Django
        if porcentagem_real > 100:
            cor_barra  = 'bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]'
            cor_texto  = 'text-red-400'
            estourado  = True
            limite_atingido = False
        elif porcentagem_real == 100:
            cor_barra  = 'bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.4)]'
            cor_texto  = 'text-amber-400'
            estourado  = False
            limite_atingido = True
        elif porcentagem_real >= 80:
            cor_barra  = 'bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.4)]'
            cor_texto  = 'text-amber-400'
            estourado  = False
            limite_atingido = False
        else:
            cor_barra  = 'bg-cyan-500 shadow-[0_0_8px_rgba(34,211,238,0.4)]'
            cor_texto  = 'text-cyan-400'
            estourado  = False
            limite_atingido = False

        resultado.append({
            'nome_envelope': envelope.nome,
            'categoria_nome': envelope.categoria.nome if envelope.categoria else 'Sem Categoria',
            'valor_planejado': float(valor_planejado),
            'valor_gasto': float(valor_gasto),
            'porcentagem_real': round(porcentagem_real, 1),
            'porcentagem_barra': round(porcentagem_barra, 2),
            'valor_restante': valor_restante,
            'cor_barra': cor_barra,
            'cor_texto': cor_texto,
            'estourado': estourado,
            'limite_atingido': limite_atingido,
        })
        
    return sorted(resultado, key=lambda x: x['nome_envelope'])
