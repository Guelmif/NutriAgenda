from django.core.exceptions import ValidationError
from django.db import models, transaction

from .models import Agendamento, Cliente, Disponibilidade, FichaPaciente, FormularioAgendamento


@transaction.atomic
def reservar_consulta(form):
    # The constraint on active appointments is the final guard against duplicate
    # submissions; select_for_update also serializes reservations on PostgreSQL.
    # Lock the questionnaire before the slot so edits cannot race with booking.
    locked_form = FormularioAgendamento.objects.filter(
        pk=form.formulario.pk, ativo=True, versao=form.versao_schema,
        campos_padrao=form.schema_recebido[0], perguntas=form.schema_recebido[1],
    ).update(versao=models.F('versao'))
    if not locked_form:
        raise ValidationError('As perguntas ou a disponibilidade mudaram. Confira o formulário novamente.')
    selected = form.cleaned_data['slot']
    # Acquire the write lock before reading occupancy. SQLite ignores row locks,
    # so this atomic no-op update also serializes its concurrent writers.
    locked = Disponibilidade.objects.filter(
        pk=selected.pk, formulario_id=form.formulario.pk, ativo=True,
        profissional_id=selected.profissional_id, data=selected.data, horario=selected.horario,
    ).update(ativo=models.F('ativo'))
    if not locked:
        raise ValidationError('Este horário não está mais disponível. Escolha outro.')
    slot = Disponibilidade.objects.select_for_update().select_related('formulario', 'profissional').get(pk=selected.pk)
    if (slot.profissional_id, slot.data, slot.horario, slot.formulario_id) != (
        selected.profissional_id, selected.data, selected.horario, form.formulario.pk,
    ) or not Disponibilidade.objects.livres().filter(pk=slot.pk).exists():
        raise ValidationError('Este horário não está mais disponível. Escolha outro.')
    if slot.profissional.responsavel_id != slot.formulario.responsavel_id:
        raise ValidationError('Este horário não está disponível neste formulário.')
    contato = form.cleaned_data['contato']
    # Do not merge patients merely because they share a name or contact number.
    cliente = Cliente.objects.create(
        nutricionista=slot.formulario.responsavel, nome=form.cleaned_data['nome'],
        email=contato if '@' in contato else '',
        telefone=''.join(char for char in contato if char.isdigit()) if '@' not in contato else '',
    )
    consulta = Agendamento.objects.create(
        cliente=cliente, profissional=slot.profissional, disponibilidade=slot,
        data=slot.data, horario=slot.horario, status=Agendamento.Status.PENDENTE,
    )
    FichaPaciente.objects.create(agendamento=consulta, respostas=form.respostas_recebidas(), **form.dados_ficha())
    return consulta
