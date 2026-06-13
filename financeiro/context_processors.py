from .models import Transacao

def alertas_pendencias(request):
    if request.user.is_authenticated:
        return {
            'qtd_pendente': Transacao.objects.filter(
                usuario=request.user,
                status_auditoria=Transacao.StatusAuditoria.PENDENTE,
            ).count()
        }
    return {'qtd_pendente': 0}