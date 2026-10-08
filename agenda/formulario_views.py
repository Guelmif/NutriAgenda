from collections import OrderedDict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Count, F, Q
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .forms import DisponibilidadeForm, FormularioConfigForm, HorariosForm, PacienteAgendamentoForm, ProfissionalForm
from .models import Agendamento, Disponibilidade, FormularioAgendamento, Profissional
from .services import reservar_consulta


@login_required
@never_cache
@require_GET
def formularios(request):
    items = FormularioAgendamento.objects.filter(responsavel=request.user).annotate(total_horarios=Count('disponibilidades'))
    return render(request, 'agenda/formularios.html', {'formularios': items})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def criar_formulario(request):
    form = FormularioConfigForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        item = form.save(commit=False)
        item.responsavel = request.user
        item.save()
        messages.success(request, 'Formulário criado. Agora adicione os nutricionistas e horários disponíveis.')
        return redirect('agenda:editar_formulario', token=item.token)
    return render(request, 'agenda/criar_formulario.html', {'form': form})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def editar_formulario(request, token):
    item = get_object_or_404(FormularioAgendamento, token=token, responsavel=request.user)
    action = request.POST.get('acao') if request.method == 'POST' else None
    config = FormularioConfigForm(request.POST if action == 'config' else None, instance=item, prefix='config')
    profissional = ProfissionalForm(request.POST if action == 'profissional' else None, prefix='profissional')
    horarios = HorariosForm(request.POST if action == 'horarios' else None, responsavel=request.user, prefix='horarios')
    saved = False
    if action == 'config' and config.is_valid():
        config.save()
        messages.success(request, 'Configurações atualizadas.')
        saved = True
    elif action == 'profissional' and profissional.is_valid():
        obj = profissional.save(commit=False)
        obj.responsavel = request.user
        obj.save()
        messages.success(request, 'Nutricionista cadastrado. Você já pode oferecer seus horários.')
        saved = True
    elif action == 'horarios' and horarios.is_valid():
        try:
            with transaction.atomic():
                for hora in horarios.cleaned_data['horarios']:
                    slot, created = Disponibilidade.objects.get_or_create(
                        profissional=horarios.cleaned_data['profissional'],
                        data=horarios.cleaned_data['data'], horario=hora,
                        defaults={'formulario': item},
                    )
                    if slot.formulario_id != item.pk:
                        raise ValidationError('Um dos horários já pertence a outro formulário. Escolha outros horários.')
                    if not created and not slot.ativo:
                        slot.ativo = True
                        slot.save(update_fields=['ativo'])
        except (ValidationError, IntegrityError):
            horarios.add_error('horarios', 'Um dos horários já está cadastrado em outro formulário. Nenhum horário novo foi salvo.')
        else:
            messages.success(request, 'Horários adicionados. Horários repetidos neste formulário não foram duplicados.')
            saved = True
    elif request.method == 'POST' and action not in ('config', 'profissional', 'horarios'):
        return HttpResponseBadRequest('Ação inválida.')
    if saved:
        return redirect('agenda:editar_formulario', token=item.token)
    slots = item.disponibilidades.select_related('profissional').annotate(
        total_reservas=Count('agendamentos'),
        reservas_ativas=Count('agendamentos', filter=~Q(agendamentos__status='cancelado')),
    )
    return render(request, 'agenda/editar_formulario.html', {
        'formulario': item, 'config_form': config, 'profissional_form': profissional,
        'horarios_form': horarios, 'profissionais': Profissional.objects.filter(responsavel=request.user),
        'slots': slots,
        'link_publico': request.build_absolute_uri(reverse('agenda:formulario_publico', args=[item.token])),
    })


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def editar_profissional(request, pk):
    item = get_object_or_404(Profissional, pk=pk, responsavel=request.user)
    form = ProfissionalForm(request.POST or None, instance=item)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Nutricionista atualizado. A mudança vale para todos os seus formulários.')
        return redirect('agenda:formularios')
    return render(request, 'agenda/editar_item.html', {'form': form, 'titulo': 'Editar nutricionista', 'descricao': 'Nome, CRN e situação são atualizados em todos os formulários desta conta.'})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
@transaction.atomic
def editar_disponibilidade(request, pk):
    if request.method == 'POST':
        Disponibilidade.objects.filter(pk=pk, formulario__responsavel=request.user).update(ativo=F('ativo'))
    slot = get_object_or_404(Disponibilidade.objects.select_for_update().select_related('formulario'), pk=pk, formulario__responsavel=request.user)
    form = DisponibilidadeForm(request.POST or None, instance=slot, responsavel=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Disponibilidade atualizada.')
        return redirect('agenda:editar_formulario', token=slot.formulario.token)
    return render(request, 'agenda/editar_item.html', {'form': form, 'titulo': 'Editar disponibilidade', 'descricao': 'Altere o dia, o horário ou o nutricionista. Se houver histórico de reservas, desative o horário e adicione outro.'})


@login_required
@require_POST
def alterar_disponibilidade(request, pk):
    slot = get_object_or_404(Disponibilidade, pk=pk, formulario__responsavel=request.user)
    action = request.POST.get('acao')
    if action not in ('ativar', 'desativar'):
        return HttpResponseBadRequest('Ação inválida.')
    slot.ativo = action == 'ativar'
    slot.save(update_fields=['ativo'])
    messages.success(request, 'Disponibilidade atualizada. As consultas existentes foram preservadas.')
    return redirect('agenda:editar_formulario', token=slot.formulario.token)


@never_cache
@require_http_methods(['GET', 'POST'])
def formulario_publico(request, token):
    item = get_object_or_404(FormularioAgendamento, token=token, ativo=True)
    form = PacienteAgendamentoForm(request.POST if request.method == 'POST' else None, formulario=item)
    if request.method == 'POST' and form.is_valid():
        try:
            reservar_consulta(form)
        except (ValidationError, IntegrityError, Disponibilidade.DoesNotExist):
            form.add_error('horario', 'Este horário não está mais disponível. Selecione outro e envie novamente.')
        except OperationalError:
            # SQLite may reject simultaneous writes rather than wait for a row lock.
            form.add_error(None, 'Não foi possível concluir agora. Tente novamente; sua solicitação não foi registrada.')
        else:
            return redirect('agenda:formulario_sucesso', token=item.token)
    return render(request, 'agenda/formulario_publico.html', {
        'formulario': item, 'form': form, 'tem_horarios': form.slots.exists(),
    })


@never_cache
@require_GET
def disponibilidades_publicas(request, token):
    item = get_object_or_404(FormularioAgendamento, token=token, ativo=True)
    try:
        profissional = int(request.GET.get('profissional', ''))
    except ValueError:
        return JsonResponse({'erro': 'Selecione um nutricionista válido.'}, status=400)
    slots = Disponibilidade.objects.livres().filter(formulario=item, profissional_id=profissional)
    dates = OrderedDict()
    for slot in slots:
        key = slot.data.isoformat()
        if key not in dates:
            dates[key] = {'valor': key, 'rotulo': slot.data.strftime('%d/%m/%Y'), 'horarios': []}
        dates[key]['horarios'].append(slot.horario.strftime('%H:%M'))
    return JsonResponse({'datas': list(dates.values())})


@never_cache
@require_GET
def formulario_sucesso(request, token):
    item = get_object_or_404(FormularioAgendamento, token=token)
    return render(request, 'agenda/formulario_sucesso.html', {'formulario': item})


@login_required
@never_cache
@require_GET
def detalhes_agendamento(request, pk):
    item = get_object_or_404(Agendamento.objects.select_related('cliente', 'profissional', 'ficha'), pk=pk, cliente__nutricionista=request.user)
    return render(request, 'agenda/detalhes_agendamento.html', {'agendamento': item})
