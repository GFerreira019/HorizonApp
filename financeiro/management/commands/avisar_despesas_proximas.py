"""
Management Command: avisar_despesas_proximas
=============================================

Envia notificações via Telegram para utilizadores com despesas fixas
que vencem nos próximos 3 dias.

Uso:
    python manage.py avisar_despesas_proximas

Agendamento:
    - Cron (Linux): 0 8 * * * cd /path/to/project && python manage.py avisar_despesas_proximas
    - Celery Beat: Adicionar à CELERY_BEAT_SCHEDULE quando Celery for ativado.
    - Windows Task Scheduler: Criar tarefa agendada diária às 08:00.

Este comando é idempotente — pode ser executado várias vezes no mesmo dia
sem efeitos colaterais (o Telegram entregará mensagens repetidas, mas o
impacto é aceitável pois serve como lembrete útil).
"""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand

from financeiro.models import DespesaFixa, PerfilUsuario
from financeiro import telegram_bot


class Command(BaseCommand):
    help = 'Envia notificações Telegram para despesas fixas que vencem nos próximos 3 dias.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dias',
            type=int,
            default=3,
            help='Número de dias à frente para verificar vencimentos (padrão: 3).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Simula o envio sem disparar mensagens reais.',
        )

    def handle(self, *args, **options):
        dias = options['dias']
        dry_run = options['dry_run']
        hoje = date.today()

        self.stdout.write(
            self.style.NOTICE(f'Verificando despesas fixas com vencimento nos próximos {dias} dias...')
        )

        # Busca todos os perfis com telegram_chat_id configurado
        perfis_com_telegram = PerfilUsuario.objects.filter(
            telegram_chat_id__isnull=False,
        ).exclude(
            telegram_chat_id='',
        ).select_related('usuario')

        total_notificacoes = 0
        total_usuarios = 0

        for perfil in perfis_com_telegram:
            usuario = perfil.usuario

            # Busca despesas fixas ativas para este utilizador
            despesas_ativas = DespesaFixa.objects.ativas_na_data(hoje).filter(
                usuario=usuario,
            )

            if not despesas_ativas.exists():
                continue

            # Filtra despesas com vencimento nos próximos N dias
            despesas_proximas = []
            for despesa in despesas_ativas:
                # Calcula a data de vencimento real neste mês
                ultimo_dia_mes = calendar.monthrange(hoje.year, hoje.month)[1]
                dia_venc = min(despesa.dia_vencimento, ultimo_dia_mes)
                data_vencimento = date(hoje.year, hoje.month, dia_venc)

                # Se o vencimento já passou neste mês, verifica no mês seguinte
                if data_vencimento < hoje:
                    if hoje.month == 12:
                        prox_mes = 1
                        prox_ano = hoje.year + 1
                    else:
                        prox_mes = hoje.month + 1
                        prox_ano = hoje.year
                    ultimo_dia_prox = calendar.monthrange(prox_ano, prox_mes)[1]
                    dia_venc = min(despesa.dia_vencimento, ultimo_dia_prox)
                    data_vencimento = date(prox_ano, prox_mes, dia_venc)

                # Verifica se está dentro da janela de N dias
                dias_ate_vencimento = (data_vencimento - hoje).days
                if 0 <= dias_ate_vencimento <= dias:
                    despesas_proximas.append({
                        'nome': despesa.nome,
                        'valor': despesa.valor_previsto,
                        'dia_vencimento': despesa.dia_vencimento,
                        'data_vencimento': data_vencimento.strftime('%d/%m/%Y'),
                        'dias_restantes': dias_ate_vencimento,
                    })

            if not despesas_proximas:
                continue

            # Ordena por proximidade do vencimento
            despesas_proximas.sort(key=lambda d: d['dias_restantes'])

            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f'[DRY-RUN] {usuario.username}: {len(despesas_proximas)} despesas próximas do vencimento'
                    )
                )
                for d in despesas_proximas:
                    self.stdout.write(f"  • {d['nome']} — R$ {d['valor']:.2f} (dia {d['dia_vencimento']})")
            else:
                sucesso = telegram_bot.notificar_despesas_proximas_vencimento(
                    usuario=usuario,
                    despesas=despesas_proximas,
                )
                if sucesso:
                    total_notificacoes += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'✅ {usuario.username}: notificação enviada ({len(despesas_proximas)} despesas)'
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f'❌ {usuario.username}: falha no envio')
                    )

            total_usuarios += 1

        self.stdout.write(self.style.SUCCESS(
            f'\nResumo: {total_notificacoes} notificações enviadas para {total_usuarios} utilizador(es).'
        ))
