"""
Celery Tasks — Open Finance (Migração Futura)
============================================

Este arquivo contém o equivalente assíncrono do management command
`sincronizar_open_finance`. Está pronto para ser ativado quando Celery
for adicionado ao projeto.

PASSOS PARA ATIVAR CELERY:
1. Instalar dependências:
       pip install celery redis django-celery-beat

2. Criar `horizonapp/celery.py` (app Celery principal):
       import os
       from celery import Celery
       os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
       app = Celery('horizonapp')
       app.config_from_object('django.conf:settings', namespace='CELERY')
       app.autodiscover_tasks()

3. Adicionar ao `core/settings.py`:
       CELERY_BROKER_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
       CELERY_RESULT_BACKEND = CELERY_BROKER_URL
       CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

4. Registrar a task no Django Admin (django-celery-beat) ou em CELERY_BEAT_SCHEDULE:
       CELERY_BEAT_SCHEDULE = {
           'sync-open-finance-hourly': {
               'task': 'financeiro.tasks.sincronizar_todas_conexoes',
               'schedule': crontab(minute=0),  # A cada hora
           },
       }

5. Iniciar workers:
       celery -A core worker --loglevel=info
       celery -A core beat --loglevel=info
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# TODO: Descomentar quando Celery for instalado no projeto.
# from celery import shared_task
# from financeiro.models import ConexaoBancaria
# from financeiro.services import sincronizar_transacoes_open_finance


# @shared_task(
#     bind=True,
#     autoretry_for=(Exception,),
#     retry_kwargs={'max_retries': 3, 'countdown': 60},
#     name='financeiro.tasks.sincronizar_conexao',
# )
# def sincronizar_conexao(self, conexao_id: int) -> dict:
#     """
#     Task Celery para sincronizar uma única ConexaoBancaria de forma assíncrona.
#
#     O parâmetro `bind=True` permite acesso ao contexto da task (self) para retry.
#     `autoretry_for` reativa a task até 3x em caso de falha de rede, com 60s de espera.
#
#     Args:
#         conexao_id: PK da ConexaoBancaria a sincronizar.
#
#     Returns:
#         Dicionário de estatísticas: {'novos': int, 'duplicados': int, 'erros': int}.
#     """
#     try:
#         conexao = ConexaoBancaria.objects.select_related('usuario').get(pk=conexao_id)
#     except ConexaoBancaria.DoesNotExist:
#         logger.error('Task cancelada: ConexaoBancaria id=%s não encontrada.', conexao_id)
#         return {}
#
#     return sincronizar_transacoes_open_finance(conexao=conexao)


# @shared_task(name='financeiro.tasks.sincronizar_todas_conexoes')
# def sincronizar_todas_conexoes() -> dict:
#     """
#     Task orquestradora: dispara `sincronizar_conexao` para cada conexão ativa.
#     Usa `delay()` para enfileirar cada conexão como uma task independente,
#     permitindo processamento paralelo e retry individual por conexão.
#
#     Returns:
#         Dict com o total de tasks enfileiradas: {'enfileiradas': int}.
#     """
#     conexoes_ativas = ConexaoBancaria.objects.filter(
#         status=ConexaoBancaria.StatusConexao.UPDATED
#     ).values_list('id', flat=True)
#
#     count = 0
#     for conexao_id in conexoes_ativas:
#         sincronizar_conexao.delay(conexao_id)
#         count += 1
#
#     logger.info('Enfileiradas %d tasks de sincronização Open Finance.', count)
#     return {'enfileiradas': count}
