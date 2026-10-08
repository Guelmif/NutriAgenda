from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .acesso import contas_acessiveis

from .models import Agendamento, AlteracaoStatus, Cliente, Disponibilidade, FormularioAgendamento, RegistroSessao, RevisaoSessao


TRANSICOES = {
    Agendamento.Status.PENDENTE: {Agendamento.Status.CONFIRMADO, Agendamento.Status.CONCLUIDO, Agendamento.Status.CANCELADO},
    Agendamento.Status.CONFIRMADO: {Agendamento.Status.CONCLUIDO, Agendamento.Status.CANCELADO},
    Agendamento.Status.CONCLUIDO: set(),
    Agendamento.Status.CANCELADO: set(),
}


def bloquear_consulta(pk, responsavel):
    # Match the reservation lock order: questionnaire -> slot -> appointment.
    item = get_object_or_404(Agendamento.objects.select_related('disponibilidade'), pk=pk, cliente__nutricionista_id__in=contas_acessiveis(responsavel))
    if item.disponibilidade_id:
        FormularioAgendamento.objects.filter(pk=item.disponibilidade.formulario_id).update(versao=models.F('versao'))
        Disponibilidade.objects.filter(pk=item.disponibilidade_id).update(ativo=models.F('ativo'))
    Agendamento.objects.filter(pk=pk, cliente__nutricionista_id__in=contas_acessiveis(responsavel)).update(status=models.F('status'))
    return get_object_or_404(Agendamento.objects.select_for_update(), pk=pk, cliente__nutricionista_id__in=contas_acessiveis(responsavel))


@transaction.atomic
def alterar_situacao(pk, responsavel, status_anterior, novo, motivo=''):
    item = bloquear_consulta(pk, responsavel)
    if item.status != status_anterior:
        raise ValidationError('A situação desta consulta já mudou. Atualize a página antes de continuar.')
    if novo not in TRANSICOES.get(item.status, set()):
        raise ValidationError('Esta alteração não está disponível para a situação atual da consulta.')
    agora = timezone.now()
    if novo == Agendamento.Status.CONCLUIDO:
        inicio = timezone.make_aware(datetime.combine(item.data, item.horario), timezone.get_current_timezone())
        if inicio > agora:
            raise ValidationError('Só é possível concluir um atendimento a partir do horário agendado.')
        item.concluido_em = agora
    if novo == Agendamento.Status.CANCELADO:
        item.cancelado_em = agora
        item.motivo_cancelamento = motivo
    antigo = item.status
    item.status = novo
    item.save(update_fields=['status', 'concluido_em', 'cancelado_em', 'motivo_cancelamento'])
    AlteracaoStatus.objects.create(agendamento=item, anterior=antigo, novo=novo,
        motivo=motivo if novo == Agendamento.Status.CANCELADO else '', realizado_por=responsavel)
    return item


@transaction.atomic
def salvar_sessao(pk, responsavel, versao, dados):
    item = bloquear_consulta(pk, responsavel)
    if item.status == Agendamento.Status.CANCELADO:
        raise ValidationError('A consulta está cancelada. O registro existente foi preservado e não pode ser editado.')
    sessao = RegistroSessao.objects.filter(agendamento=item).first()
    if (sessao.versao if sessao else 0) != versao:
        raise ValidationError('Outro registro da sessão foi salvo. Atualize a página para revisar antes de editar.')
    if not sessao:
        sessao = RegistroSessao(agendamento=item)
    else:
        sessao.versao += 1
    for key in ('observacoes', 'plano_alimentar', 'orientacoes'):
        setattr(sessao, key, dados[key])
    sessao.atualizado_por = responsavel
    sessao.save()
    RevisaoSessao.objects.create(sessao=sessao, versao=sessao.versao, autor=responsavel,
        observacoes=sessao.observacoes, plano_alimentar=sessao.plano_alimentar, orientacoes=sessao.orientacoes)
    return sessao


@transaction.atomic
def vincular_cliente(pk, responsavel, cliente_anterior, destino):
    item = bloquear_consulta(pk, responsavel)
    target = get_object_or_404(Cliente, pk=destino, nutricionista_id=item.cliente.nutricionista_id)
    if item.cliente_id != cliente_anterior:
        raise ValidationError('O paciente desta consulta já mudou. Atualize a página antes de continuar.')
    item.cliente = target
    item.save(update_fields=['cliente'])
    return item
