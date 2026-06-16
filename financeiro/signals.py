from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from django.db.models import Sum
from datetime import date
import threading
from .models import MacroCategoria, Categoria, PerfilUsuario, Transacao, OrcamentoCategoria
from .telegram_bot import enviar_mensagem_telegram

# Dicionário de Ícones para cada MacroCategoria
ICONES_MACRO = {
    'Renda Principal': 'bi-cash-stack',
    'Renda Extra': 'bi-graph-up-arrow',

    'Moradia': 'bi-house',
    'Contas Residenciais': 'bi-lightning',
    'Alimentação': 'bi-cart3',
    'Transporte': 'bi-car-front',
    'Saúde e Bem-estar': 'bi-heart-pulse',
    'Educação': 'bi-book',
    'Lazer e Estilo de Vida': 'bi-controller',
    'Cuidados Pessoais e Compras': 'bi-scissors',
    'Serviços Financeiros': 'bi-bank',

    'Investimentos e Futuro': 'bi-safe',
}

# Plano de Contas Padrão mapeado em um Dicionário
PLANILHA_PADRAO = {
    'receita': {
        'Renda Principal': [('Salário', 'bi-cash-stack'), ('Adiantamento', 'bi-wallet2')],
        'Renda Extra': [('Freelance', 'bi-laptop'), ('Vendas', 'bi-shop'), ('Rendimentos/Dividendos', 'bi-graph-up-arrow')],
    },
    'despesa': {
        'Moradia': [('Aluguel/Financiamento', 'bi-house'), ('Condomínio', 'bi-building'), ('IPTU', 'bi-file-text'), ('Reformas', 'bi-tools')],
        'Contas Residenciais': [('Energia Elétrica', 'bi-lightning'), ('Água', 'bi-droplet'), ('Gás', 'bi-fire'), ('Internet', 'bi-router'), ('Celular', 'bi-phone'), ('Streaming', 'bi-play-btn')],
        'Alimentação': [('Supermercado', 'bi-cart3'), ('Restaurantes', 'bi-cup-hot'), ('Delivery', 'bi-bicycle'), ('Padaria/Cafés', 'bi-cup')],
        'Transporte': [('Combustível', 'bi-fuel-pump'), ('Manutenção Carro', 'bi-wrench'), ('Uber/Táxi', 'bi-car-front'), ('Transporte Público', 'bi-bus-front')],
        'Saúde e Bem-estar': [('Plano de Saúde', 'bi-heart-pulse'), ('Farmácia', 'bi-capsule'), ('Terapia/Psicólogo', 'bi-person-hearts'), ('Academia', 'bi-bicycle')],
        'Educação': [('Mensalidade Escolar/Faculdade', 'bi-book'), ('Cursos/Certificações', 'bi-award'), ('Livros/Materiais', 'bi-journal-text')],
        'Lazer e Estilo de Vida': [('Viagens', 'bi-airplane'), ('Cinema/Teatro', 'bi-ticket-perforated'), ('Hobbies', 'bi-controller'), ('Eventos/Festas', 'bi-balloon')],
        'Cuidados Pessoais e Compras': [('Roupas/Calçados', 'bi-bag'), ('Cabelo/Beleza', 'bi-scissors'), ('Eletrônicos', 'bi-phone'), ('Presentes', 'bi-gift')],
        'Serviços Financeiros': [('Tarifas Bancárias', 'bi-bank'), ('Juros/Multas', 'bi-exclamation-triangle'), ('Impostos (IRPF)', 'bi-file-earmark-text'), ('Seguros', 'bi-shield-check')],
    },
    'reservado': {
        'Investimentos e Futuro': [('Reserva de Emergência', 'bi-safe'), ('Ações/Fundos', 'bi-graph-up'), ('Previdência', 'bi-piggy-bank')],
    }
}

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def criar_categorias_padrao(sender, instance, created, **kwargs):
    """
    Gatilho que dispara automaticamente sempre que um User é salvo.
    Se for um User NOVO (created=True), ele injeta o plano de contas padrão.
    """
    if created:
        for tipo_categoria, macros in PLANILHA_PADRAO.items():
            ordem = 1
            for nome_macro, subcategorias in macros.items():
                
                macro_obj = MacroCategoria.objects.create(
                    usuario=instance,
                    nome=nome_macro,
                    tipo=tipo_categoria,
                    ordem=ordem
                )
                
                for nome_sub, icone in subcategorias:
                    Categoria.objects.create(
                        usuario=instance,
                        macro_categoria=macro_obj,
                        nome=nome_sub,
                        icone=icone
                    )
                ordem += 1


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def criar_perfil_usuario(sender, instance, created, **kwargs):
    """Garante que todo User tenha um PerfilUsuario associado (retrocompatível)."""
    if created:
        PerfilUsuario.objects.create(usuario=instance)
    else:
        PerfilUsuario.objects.get_or_create(usuario=instance)


def verificar_orcamento_em_background(transacao_id):
    """
    Verifica se a soma dos gastos de uma MacroCategoria ultrapassa o orçamento
    planejado para o mês e, se for o caso, envia notificação no Telegram.
    """
    try:
        transacao = Transacao.objects.select_related('categoria__macro_categoria', 'usuario').get(id=transacao_id)
    except Transacao.DoesNotExist:
        return
        
    macro = transacao.categoria.macro_categoria
    if macro.tipo != 'despesa':
        return
        
    hoje = date.today()
    # Verifica se existe orçamento para esta macrocategoria no mês atual
    orcamento = OrcamentoCategoria.objects.filter(
        planejamento__usuario=transacao.usuario,
        planejamento__mes=hoje.month,
        planejamento__ano=hoje.year,
        macro_categoria=macro
    ).first()
    
    if not orcamento or orcamento.valor_planejado <= 0:
        return
        
    # Calcula soma dos gastos da macrocategoria no mês
    total_gasto = Transacao.objects.filter(
        usuario=transacao.usuario,
        categoria__macro_categoria=macro,
        data__year=hoje.year,
        data__month=hoje.month
    ).aggregate(total=Sum('valor'))['total'] or 0
    
    percentual = (total_gasto / orcamento.valor_planejado) * 100
    
    usuario = transacao.usuario
    perfil = getattr(usuario, 'perfil', None)
    telegram_chat_id = perfil.telegram_chat_id if perfil else None
    
    if not telegram_chat_id:
        return
        
    if percentual > 100:
        msg = f"🚨 <b>Orçamento Estourado!</b>\n\nA sua categoria <b>{macro.nome}</b> ultrapassou o limite orçado.\nOrçado: R$ {orcamento.valor_planejado:.2f}\nGasto: R$ {total_gasto:.2f} ({percentual:.1f}%)"
        enviar_mensagem_telegram(telegram_chat_id, msg, parse_mode='HTML')
    elif percentual >= 90:
        msg = f"⚠️ <b>Orçamento em Risco!</b>\n\nA sua categoria <b>{macro.nome}</b> atingiu {percentual:.1f}% do orçado.\nOrçado: R$ {orcamento.valor_planejado:.2f}\nGasto: R$ {total_gasto:.2f} ({percentual:.1f}%)"
        enviar_mensagem_telegram(telegram_chat_id, msg, parse_mode='HTML')


@receiver(post_save, sender=Transacao)
def transacao_post_save(sender, instance, created, **kwargs):
    """
    Quando uma Transação é salva, dispara a verificação do orçamento de forma assíncrona.
    """
    threading.Thread(target=verificar_orcamento_em_background, args=(instance.id,), daemon=True).start()