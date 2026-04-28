from .models import Transacao

def alertas_pendencias(request):
    if request.user.is_authenticated:
        return {'qtd_pendente': Transacao.objects.filter(status_auditoria='pendente').count()}
    return {'qtd_pendente': 0}