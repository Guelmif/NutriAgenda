import calendar
from collections import defaultdict
from datetime import date

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .models import Agendamento

MESES = (
    '', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
    'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
)
ANO_MINIMO, ANO_MAXIMO = 1900, 2100


@login_required
@never_cache
@require_GET
def calendario(request):
    hoje = timezone.localdate()
    try:
        ano = int(request.GET.get('ano', hoje.year))
        mes = int(request.GET.get('mes', hoje.month))
        if not ANO_MINIMO <= ano <= ANO_MAXIMO:
            raise ValueError
        inicio = date(ano, mes, 1)
    except (ValueError, OverflowError):
        return HttpResponseBadRequest('Mês inválido. Use mes=1 a 12 e ano=1900 a 2100.')

    fim = date(ano, mes, calendar.monthrange(ano, mes)[1])
    agendamentos = list(Agendamento.objects.filter(
        cliente__nutricionista=request.user, data__range=(inicio, fim),
    ).select_related('cliente'))
    por_dia = defaultdict(list)
    for agendamento in agendamentos:
        por_dia[agendamento.data.day].append(agendamento)

    semanas = []
    for semana in calendar.Calendar(firstweekday=6).monthdayscalendar(ano, mes):
        semanas.append([
            {
                'numero': dia,
                'data': date(ano, mes, dia).isoformat(),
                'hoje': date(ano, mes, dia) == hoje,
                'agendamentos': por_dia[dia][:2],
                'total': len(por_dia[dia]),
                'extras': max(0, len(por_dia[dia]) - 2),
            } if dia else None
            for dia in semana
        ])

    anterior = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
    proximo = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return render(request, 'agenda/calendario.html', {
        'semanas': semanas, 'mes': mes, 'ano': ano, 'mes_nome': MESES[mes],
        'anterior': anterior if anterior[0] >= ANO_MINIMO else None,
        'proximo': proximo if proximo[0] <= ANO_MAXIMO else None,
        'total': len(agendamentos),
        'confirmados': sum(a.status == Agendamento.Status.CONFIRMADO for a in agendamentos),
        'pendentes': sum(a.status == Agendamento.Status.PENDENTE for a in agendamentos),
    })


@login_required
@never_cache
@require_GET
def agendamentos_do_dia(request):
    valor = request.GET.get('data', '')
    try:
        dia = date.fromisoformat(valor)
        if valor != dia.isoformat() or not ANO_MINIMO <= dia.year <= ANO_MAXIMO:
            raise ValueError
    except ValueError:
        return JsonResponse({'erro': 'Informe uma data válida no formato AAAA-MM-DD.'}, status=400)

    agendamentos = Agendamento.objects.filter(
        cliente__nutricionista=request.user, data=dia,
    ).select_related('cliente', 'profissional', 'ficha')
    return JsonResponse({
        'data': dia.isoformat(),
        'agendamentos': [
            {
                'id': a.pk, 'cliente': a.cliente.nome,
                'horario': a.horario.strftime('%H:%M'),
                'status': a.status, 'status_label': a.get_status_display(),
                **({'nutricionista': a.profissional.nome} if a.profissional_id else {}),
                **({'detalhes_url': reverse('agenda:detalhes_agendamento', args=[a.pk])} if hasattr(a, 'ficha') else {}),
            } for a in agendamentos
        ],
    })
