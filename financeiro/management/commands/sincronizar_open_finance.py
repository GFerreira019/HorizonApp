"""
Management Command: sincronizar_open_finance
============================================

Orquestra a sincronização automática de transações para todas as conexões
Open Finance ativas. Projetado para ser executado periodicamente via:

  - Windows Task Scheduler (MVP):
      Tarefa agendada → python manage.py sincronizar_open_finance

  - Linux/Mac Cron:
      0 * * * * /path/to/venv/bin/python manage.py sincronizar_open_finance

  - Celery Beat (futura migração):
      Ver `financeiro/tasks.py` para o equivalente assíncrono.

Uso:
    # Sincroniza todas as conexões ativas (padrão: últimos 30 dias)
    python manage.py sincronizar_open_finance

    # Sincroniza apenas uma conexão específica
    python manage.py sincronizar_open_finance --conexao-id 42

    # Sincroniza com janela temporal customizada
    python manage.py sincronizar_open_finance --data-inicio 2024-01-01 --data-fim 2024-01-31
"""
import logging
from datetime import date
from typing import Optional

from django.core.management.base import BaseCommand, CommandError

from financeiro.models import ConexaoBancaria
from financeiro.services import sincronizar_transacoes_open_finance

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Sincroniza transações Open Finance para todas as conexões ativas."""

    help = (
        'Itera sobre todas as ConexaoBancaria com status=UPDATED e executa '
        'a sincronização via Pluggy API. Seguro para rodar repetidamente (idempotente).'
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            '--conexao-id',
            type=int,
            default=None,
            help='Limita a execução a uma ConexaoBancaria específica (por PK).',
        )
        parser.add_argument(
            '--data-inicio',
            type=date.fromisoformat,
            default=None,
            metavar='YYYY-MM-DD',
            help='Data de início da janela de busca de transações.',
        )
        parser.add_argument(
            '--data-fim',
            type=date.fromisoformat,
            default=None,
            metavar='YYYY-MM-DD',
            help='Data de fim da janela de busca de transações.',
        )

    def handle(self, *args, **options) -> None:
        """
        Ponto de entrada do command. Orquestra a sincronização e reporta resultados.

        Args:
            *args: Argumentos posicionais (não utilizados).
            **options: Opções parseadas pelo argparse (conexao_id, data_inicio, data_fim).

        Raises:
            CommandError: Se `--conexao-id` for passado mas a conexão não existir.
        """
        conexao_id: Optional[int] = options['conexao_id']
        data_inicio: Optional[date] = options['data_inicio']
        data_fim: Optional[date] = options['data_fim']

        # --- Seleção das conexões a processar ---
        if conexao_id:
            try:
                # select_related evita N+1 ao acessar conexao.usuario.
                conexoes = [
                    ConexaoBancaria.objects.select_related('usuario').get(pk=conexao_id)
                ]
            except ConexaoBancaria.DoesNotExist:
                raise CommandError(f'ConexaoBancaria com id={conexao_id} não encontrada.')
        else:
            # Processa apenas conexões saudáveis para evitar loops de retry em erros de login.
            conexoes = list(
                ConexaoBancaria.objects
                .filter(status=ConexaoBancaria.StatusConexao.UPDATED)
                .select_related('usuario')
            )

        total = len(conexoes)
        if total == 0:
            self.stdout.write(self.style.WARNING('Nenhuma conexão ativa encontrada. Nada a sincronizar.'))
            return

        self.stdout.write(
            self.style.HTTP_INFO(f'\n🔄 Iniciando sincronização de {total} conexão(ões) Open Finance...\n')
        )

        # --- Totalizadores para o resumo final ---
        total_novos = 0
        total_duplicados = 0
        total_erros_tx = 0
        conexoes_com_falha = 0

        for idx, conexao in enumerate(conexoes, start=1):
            self.stdout.write(
                f'[{idx}/{total}] {conexao.instituicao_nome} '
                f'(usuário: {conexao.usuario.username}) ...',
                ending=' ',
            )
            self.stdout.flush()

            try:
                stats = sincronizar_transacoes_open_finance(
                    conexao=conexao,
                    data_inicio=data_inicio,
                    data_fim=data_fim,
                )
                total_novos += stats['novos']
                total_duplicados += stats['duplicados']
                total_erros_tx += stats['erros']

                self.stdout.write(
                    self.style.SUCCESS(
                        f'✅ novos={stats["novos"]} | duplicados={stats["duplicados"]} | erros={stats["erros"]}'
                    )
                )

            except Exception as exc:  # noqa: BLE001
                # Isola a falha de uma conexão para não bloquear as demais.
                conexoes_com_falha += 1
                self.stdout.write(self.style.ERROR(f'❌ Falha: {exc}'))
                logger.exception('Erro ao sincronizar conexão %s: %s', conexao.pk, exc)

        # --- Relatório final ---
        self.stdout.write('\n' + '─' * 55)
        self.stdout.write(
            self.style.SUCCESS(
                f'✅ Sincronização concluída:\n'
                f'   Conexões processadas : {total - conexoes_com_falha}/{total}\n'
                f'   Transações novas     : {total_novos}\n'
                f'   Duplicadas (skip)    : {total_duplicados}\n'
                f'   Erros por transação  : {total_erros_tx}\n'
                f'   Conexões com falha   : {conexoes_com_falha}\n'
            )
        )
