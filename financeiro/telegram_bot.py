"""
Telegram Bot — Serviço de Notificações Push
============================================

Cliente leve que encapsula a comunicação com a Bot API do Telegram.
Responsabilidades:
    1. Enviar mensagens de texto formatadas (MarkdownV2) via `sendMessage`.
    2. Expor helpers de alto nível para os dois casos de uso de negócio:
       - Alerta de Limite de Gasto / Orçamento de Categoria excedido.
       - Aviso diário de Despesas Fixas próximas do vencimento.

Princípios de Design:
    - **Fail-safe**: erros de rede/API são logados mas NUNCA propagados,
      garantindo que uma falha no Telegram não derrube a transação financeira.
    - **Baixo acoplamento**: este módulo depende apenas de `django.conf.settings`
      e da stdlib `requests` (já no projeto).
    - **Idempotência**: o caller é responsável por verificar `notificacao_enviada`
      antes de chamar estas funções (ver `verificar_limite_e_notificar`).

Configuração necessária:
    settings.TELEGRAM_BOT_TOKEN  — Token do BotFather (HTTP API Token).
    PerfilUsuario.telegram_chat_id — ID do chat do utilizador no Telegram.
"""
import logging
from decimal import Decimal
from typing import Optional, List, Dict, Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Camada de Transporte — Comunicação HTTP com a Bot API
# ─────────────────────────────────────────────────────────────────────────────

def _get_bot_token() -> str:
    """Retorna o token configurado ou string vazia (desabilitado)."""
    return getattr(settings, 'TELEGRAM_BOT_TOKEN', '')


def _escape_markdown_v2(text: str) -> str:
    """
    Escapa caracteres especiais do MarkdownV2 do Telegram.
    Ref: https://core.telegram.org/bots/api#markdownv2-style
    """
    special_chars = r'_*[]()~`>#+-=|{}.!'
    escaped = ''
    for char in text:
        if char in special_chars:
            escaped += f'\\{char}'
        else:
            escaped += char
    return escaped


def enviar_mensagem_telegram(
    chat_id: str,
    mensagem: str,
    parse_mode: str = 'HTML',
) -> bool:
    """
    Envia uma mensagem de texto para um chat do Telegram.

    Args:
        chat_id: ID do chat destino (obtido de PerfilUsuario.telegram_chat_id).
        mensagem: Corpo da mensagem (já formatado no parse_mode escolhido).
        parse_mode: Formato do texto ('MarkdownV2', 'HTML' ou '').

    Returns:
        True se a mensagem foi entregue com sucesso, False caso contrário.

    Notes:
        - Erros são logados mas NUNCA propagados (fail-safe by design).
        - Se o token estiver vazio, retorna False silenciosamente (feature desabilitada).
    """
    token = _get_bot_token()
    if not token:
        logger.debug('Telegram desabilitado: TELEGRAM_BOT_TOKEN não configurado.')
        return False

    if not chat_id:
        logger.debug('Telegram: chat_id vazio, notificação ignorada.')
        return False

    url = f'https://api.telegram.org/bot{token}/sendMessage'
    payload: Dict[str, Any] = {
        'chat_id': chat_id,
        'text': mensagem,
    }
    if parse_mode:
        payload['parse_mode'] = parse_mode

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        logger.info('Telegram: mensagem enviada para chat_id=%s', chat_id)
        return True

    except requests.exceptions.Timeout:
        logger.warning('Telegram: timeout ao enviar mensagem para chat_id=%s', chat_id)
    except requests.exceptions.ConnectionError:
        logger.warning('Telegram: erro de conexão ao enviar para chat_id=%s', chat_id)
    except requests.exceptions.HTTPError as exc:
        logger.error(
            'Telegram: erro HTTP %s ao enviar para chat_id=%s — %s',
            exc.response.status_code if exc.response else '?',
            chat_id,
            exc.response.text[:200] if exc.response else str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error('Telegram: erro inesperado ao enviar para chat_id=%s — %s', chat_id, exc)

    return False


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de Alto Nível — Mensagens de Negócio
# ─────────────────────────────────────────────────────────────────────────────

def _obter_chat_id_usuario(usuario) -> Optional[str]:
    """
    Obtém o telegram_chat_id do PerfilUsuario, retornando None se inexistente.
    Fail-safe: se o perfil não existir, loga e retorna None.
    """
    try:
        perfil = getattr(usuario, 'perfil', None)
        if perfil and perfil.telegram_chat_id:
            return perfil.telegram_chat_id
    except Exception:  # noqa: BLE001
        pass
    return None


def notificar_limite_excedido(
    usuario,
    limite,
    transacao_descricao: str,
    transacao_valor: Decimal,
) -> bool:
    chat_id = _obter_chat_id_usuario(usuario)
    if not chat_id:
        return False

    pct = limite.percentual_consumido
    alvo = limite.categoria_alvo.nome if limite.categoria_alvo else 'Geral'

    if pct >= 100:
        emoji = '🚨'
        status = '<b>EXCEDIDO</b>'
    else:
        emoji = '⚠️'
        status = f'<b>{pct}%</b> consumido'

    # Usando formatação HTML básica
    mensagem = (
        f'{emoji} <b>ALERTA DE LIMITE — HorizonAPP</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'📌 Limite: {alvo}\n'
        f'💰 Teto: R$ {limite.valor_limite:.2f}\n'
        f'📊 Consumido: R$ {limite.valor_consumido:.2f} ({status})\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'🧾 Transação: <i>{transacao_descricao}</i>\n'
        f'💸 Valor: R$ {transacao_valor:.2f}\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'Acesse o app para mais detalhes.'
    )

    return enviar_mensagem_telegram(chat_id, mensagem)


def notificar_orcamento_excedido(
    usuario,
    macro_nome: str,
    valor_planejado: Decimal,
    valor_realizado: Decimal,
    transacao_descricao: str,
    transacao_valor: Decimal,
) -> bool:
    """
    Envia alerta quando o gasto real de uma MacroCategoria ultrapassa o orçamento.

    Args:
        usuario: Instância do User Django.
        macro_nome: Nome da MacroCategoria orçamentada.
        valor_planejado: Valor definido no OrcamentoCategoria.
        valor_realizado: Soma real de gastos no mês (inclui a transação atual).
        transacao_descricao: Descrição da transação que disparou o alerta.
        transacao_valor: Valor da transação.

    Returns:
        True se a notificação foi enviada com sucesso.
    """
    chat_id = _obter_chat_id_usuario(usuario)
    if not chat_id:
        return False

    pct = round(float(valor_realizado / valor_planejado * 100), 1) if valor_planejado else 0

    mensagem = (
        f'🚨 ORÇAMENTO EXCEDIDO — HorizonAPP\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'📁 Categoria: {macro_nome}\n'
        f'📊 Planejado: R$ {valor_planejado:.2f}\n'
        f'💸 Realizado: R$ {valor_realizado:.2f} ({pct}%)\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'🧾 Última transação: {transacao_descricao}\n'
        f'💰 Valor: R$ {transacao_valor:.2f}\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'Revise seu planejamento no app.'
    )

    return enviar_mensagem_telegram(chat_id, mensagem, parse_mode='')


def notificar_despesas_proximas_vencimento(
    usuario,
    despesas: List[Dict[str, Any]],
) -> bool:
    """
    Envia aviso diário com as despesas fixas que vencem nos próximos 3 dias.

    Args:
        usuario: Instância do User Django.
        despesas: Lista de dicts com chaves: 'nome', 'valor', 'dia_vencimento', 'data_vencimento'.

    Returns:
        True se a notificação foi enviada com sucesso.
    """
    chat_id = _obter_chat_id_usuario(usuario)
    if not chat_id:
        return False

    if not despesas:
        return False

    linhas = [
        f'📅 DESPESAS PRÓXIMAS DO VENCIMENTO — HorizonAPP',
        f'━━━━━━━━━━━━━━━━━━━━━━━━━━',
    ]

    total = Decimal('0.00')
    for d in despesas:
        linhas.append(
            f"• {d['nome']} — R$ {d['valor']:.2f} (vence dia {d['dia_vencimento']})"
        )
        total += d['valor']

    linhas.extend([
        f'━━━━━━━━━━━━━━━━━━━━━━━━━━',
        f'💰 Total previsto: R$ {total:.2f}',
        f'Acesse o app para registrar os pagamentos.',
    ])

    mensagem = '\n'.join(linhas)
    return enviar_mensagem_telegram(chat_id, mensagem, parse_mode='')
