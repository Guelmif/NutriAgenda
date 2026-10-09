from .models import MembroEquipe


def contas_acessiveis(usuario):
    compartilhadas = MembroEquipe.objects.filter(
        usuario=usuario,
        ativo=True,
        responsavel__is_active=True,
    ).values_list("responsavel_id", flat=True)
    return {usuario.pk, *compartilhadas}
