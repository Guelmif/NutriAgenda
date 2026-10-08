from datetime import datetime

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import OperationalError
from django.db.models import Count, Max, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .acesso import contas_acessiveis
from .atendimento_forms import ClienteForm, MembroEquipeForm, SessaoForm, SituacaoForm, VincularClienteForm
from .atendimento_services import TRANSICOES, alterar_situacao, salvar_sessao, vincular_cliente
from .models import Agendamento, Cliente, MembroEquipe, Profissional, RegistroSessao


def consultas(usuario):
    return Agendamento.objects.filter(cliente__nutricionista_id__in=contas_acessiveis(usuario)).select_related('cliente', 'cliente__nutricionista', 'profissional', 'ficha', 'sessao', 'sessao__atualizado_por')


@login_required
@never_cache
@require_GET
def atendimentos(request):
    items = consultas(request.user).order_by('-data', '-horario', '-pk')
    search = request.GET.get('q', '').strip()[:150]
    status = request.GET.get('status', '')
    profissional = request.GET.get('profissional', '')
    if search:
        items = items.filter(Q(cliente__nome__icontains=search) | Q(cliente__email__icontains=search) | Q(cliente__telefone__icontains=search))
    if status in Agendamento.Status.values:
        items = items.filter(status=status)
    else:
        status = ''
    try:
        professional_id = int(profissional)
        if not 0 < professional_id <= 9223372036854775807:
            raise ValueError
    except (ValueError, OverflowError):
        profissional = ''
    else:
        profissional = str(professional_id)
        items = items.filter(profissional_id=professional_id)
    return render(request, 'agenda/atendimentos.html', {
        'page': Paginator(items, 20).get_page(request.GET.get('page')), 'q': search, 'status': status,
        'status_choices': Agendamento.Status.choices, 'profissional': profissional,
        'profissionais': Profissional.objects.filter(responsavel_id__in=contas_acessiveis(request.user)),
    })


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def detalhes_agendamento(request, pk):
    item = get_object_or_404(consultas(request.user), pk=pk)
    sessao = RegistroSessao.objects.filter(agendamento=item).first()
    form = SessaoForm(request.POST if request.method == 'POST' else None, instance=sessao,
        initial={'versao_atual': sessao.versao if sessao else 0})
    if request.method == 'POST' and form.is_valid():
        try:
            salvar_sessao(item.pk, request.user, form.cleaned_data['versao_atual'], form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        except OperationalError:
            form.add_error(None, 'Não foi possível salvar agora. Tente novamente; o registro anterior foi preservado.')
        else:
            messages.success(request, 'Registro da sessão salvo.')
            return redirect('agenda:detalhes_agendamento', pk=item.pk)
    inicio = timezone.make_aware(datetime.combine(item.data, item.horario), timezone.get_current_timezone())
    return render(request, 'agenda/detalhes_agendamento.html', {
        'agendamento': item, 'sessao': sessao, 'sessao_form': form,
        'pode_confirmar': item.status == Agendamento.Status.PENDENTE,
        'pode_alterar': bool(TRANSICOES[item.status]),
        'pode_concluir': bool(TRANSICOES[item.status]) and inicio <= timezone.now(),
        'historico_status': item.alteracoes_status.select_related('realizado_por'),
        'revisoes': sessao.revisoes.select_related('autor') if sessao else [],
    })


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def situacao_agendamento(request, pk, acao):
    actions = {'confirmar': ('confirmado', 'Confirmar consulta'), 'concluir': ('concluido', 'Concluir atendimento'), 'cancelar': ('cancelado', 'Cancelar consulta')}
    if acao not in actions:
        return HttpResponseBadRequest('Ação inválida.')
    item = get_object_or_404(consultas(request.user), pk=pk)
    status, label = actions[acao]
    form = SituacaoForm(request.POST if request.method == 'POST' else None, initial={'status_anterior': item.status})
    if acao != 'cancelar':
        form.fields.pop('motivo')
    if request.method == 'POST' and form.is_valid():
        try:
            alterar_situacao(item.pk, request.user, form.cleaned_data['status_anterior'], status, form.cleaned_data.get('motivo', ''))
        except ValidationError as error:
            form.add_error(None, error)
        except OperationalError:
            form.add_error(None, 'Não foi possível concluir agora. Atualize a página e tente novamente.')
        else:
            messages.success(request, 'Situação da consulta atualizada.')
            return redirect('agenda:detalhes_agendamento', pk=item.pk)
    return render(request, 'agenda/situacao_agendamento.html', {'agendamento': item, 'form': form, 'acao': acao, 'titulo': label})


@login_required
@never_cache
@require_GET
def clientes(request):
    search = request.GET.get('q', '').strip()[:150]
    items = Cliente.objects.filter(nutricionista_id__in=contas_acessiveis(request.user)).select_related('nutricionista').annotate(
        total_consultas=Count('agendamentos'),
        total_concluidas=Count('agendamentos', filter=Q(agendamentos__status='concluido')),
        ultima_consulta=Max('agendamentos__data'),
    )
    items = items.order_by('nome', 'pk')
    if search:
        items = items.filter(Q(nome__icontains=search) | Q(email__icontains=search) | Q(telefone__icontains=search))
    return render(request, 'agenda/clientes.html', {'page': Paginator(items, 20).get_page(request.GET.get('page')), 'q': search})


@login_required
@never_cache
@require_GET
def detalhes_cliente(request, pk):
    item = get_object_or_404(Cliente.objects.select_related('nutricionista'), pk=pk, nutricionista_id__in=contas_acessiveis(request.user))
    history = consultas(request.user).filter(cliente=item).order_by('-data', '-horario', '-pk')
    return render(request, 'agenda/detalhes_cliente.html', {'cliente': item, 'page': Paginator(history, 10).get_page(request.GET.get('page'))})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def editar_cliente(request, pk=None):
    item = get_object_or_404(Cliente, pk=pk, nutricionista_id__in=contas_acessiveis(request.user)) if pk else Cliente(nutricionista=request.user)
    form = ClienteForm(request.POST if request.method == 'POST' else None, instance=item)
    if not pk:
        from django import forms
        form.fields['conta'] = forms.ModelChoiceField(label='Conta / consultório', queryset=get_user_model().objects.filter(pk__in=contas_acessiveis(request.user)), initial=request.user.pk)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        if not pk:
            obj.nutricionista = form.cleaned_data['conta']
        obj.save()
        messages.success(request, 'Cadastro do paciente salvo. As fichas recebidas foram preservadas.')
        return redirect('agenda:detalhes_cliente', pk=obj.pk)
    return render(request, 'agenda/editar_cliente.html', {'form': form, 'cliente': item, 'novo': pk is None})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def vincular_agendamento(request, pk):
    item = get_object_or_404(consultas(request.user), pk=pk)
    form = VincularClienteForm(request.POST if request.method == 'POST' else None, responsavel=item.cliente.nutricionista,
        atual=item.cliente_id, initial={'cliente_anterior': item.cliente_id})
    if request.method == 'POST' and form.is_valid():
        try:
            vincular_cliente(item.pk, request.user, form.cleaned_data['cliente_anterior'], form.cleaned_data['cliente'].pk)
        except ValidationError as error:
            form.add_error(None, error)
        except OperationalError:
            form.add_error(None, 'Não foi possível vincular agora. Tente novamente.')
        else:
            messages.success(request, 'Consulta vinculada ao paciente escolhido. As informações da sessão foram preservadas.')
            return redirect('agenda:detalhes_agendamento', pk=item.pk)
    return render(request, 'agenda/vincular_agendamento.html', {'form': form, 'agendamento': item})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def equipe(request):
    form = MembroEquipeForm(request.POST if request.method == 'POST' else None, responsavel=request.user)
    if request.method == 'POST' and form.is_valid():
        MembroEquipe.objects.update_or_create(responsavel=request.user, usuario=form.cleaned_data['usuario'], defaults={'ativo': True})
        messages.success(request, 'Nutricionista adicionado à equipe. O histórico desta conta está compartilhado com ele.')
        return redirect('agenda:equipe')
    return render(request, 'agenda/equipe.html', {
        'form': form, 'membros': MembroEquipe.objects.filter(responsavel=request.user).select_related('usuario'),
        'compartilhadas': MembroEquipe.objects.filter(usuario=request.user, ativo=True, responsavel__is_active=True).select_related('responsavel'),
    })


@login_required
@require_POST
def alterar_membro(request, pk):
    item = get_object_or_404(MembroEquipe, pk=pk, responsavel=request.user)
    acao = request.POST.get('acao')
    if acao not in ('ativar', 'desativar'):
        return HttpResponseBadRequest('Ação inválida.')
    item.ativo = acao == 'ativar'
    item.save(update_fields=['ativo'])
    messages.success(request, 'Acesso à equipe atualizado.')
    return redirect('agenda:equipe')
