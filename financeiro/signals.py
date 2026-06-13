from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .models import MacroCategoria, Categoria, PerfilUsuario

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