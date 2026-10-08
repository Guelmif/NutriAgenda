import re
from datetime import date, datetime, timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone

from .models import Disponibilidade, FichaPaciente, FormularioAgendamento, Profissional


class FormularioConfigForm(forms.ModelForm):
    class Meta:
        model = FormularioAgendamento
        fields = ['titulo', 'descricao', 'ativo']
        widgets = {'descricao': forms.Textarea(attrs={'rows': 3})}


class ProfissionalForm(forms.ModelForm):
    class Meta:
        model = Profissional
        fields = ['nome', 'crn', 'ativo']


class HorariosForm(forms.Form):
    profissional = forms.ModelChoiceField(queryset=Profissional.objects.none(), label='Nutricionista')
    data = forms.DateField(label='Dia disponível', input_formats=['%Y-%m-%d'], widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    horarios = forms.CharField(label='Horários disponíveis', max_length=500, help_text='Separe por vírgula. Exemplo: 08:00, 09:00, 10:30, 14:00')

    def __init__(self, *args, responsavel, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['profissional'].queryset = Profissional.objects.filter(responsavel=responsavel, ativo=True)
        self.fields['data'].widget.attrs['min'] = timezone.localdate().isoformat()
        self.fields['data'].widget.attrs['max'] = min(timezone.localdate() + timedelta(days=730), date(2100, 12, 31)).isoformat()

    def clean_data(self):
        value = self.cleaned_data['data']
        if not timezone.localdate() <= value <= timezone.localdate() + timedelta(days=730):
            raise ValidationError('Escolha um dia de hoje até os próximos dois anos.')
        if value.year > 2100:
            raise ValidationError('Escolha uma data até 2100.')
        return value

    def clean_horarios(self):
        result = []
        for value in self.cleaned_data['horarios'].split(','):
            value = value.strip()
            if not re.fullmatch(r'\d{2}:\d{2}', value):
                raise ValidationError('Use horários no formato HH:MM, separados por vírgula.')
            try:
                horario = datetime.strptime(value, '%H:%M').time()
            except ValueError as error:
                raise ValidationError('Informe horários entre 00:00 e 23:59.') from error
            if horario not in result:
                result.append(horario)
        return result

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('data') == timezone.localdate() and cleaned.get('horarios'):
            if any(h <= timezone.localtime().time().replace(tzinfo=None) for h in cleaned['horarios']):
                self.add_error('horarios', 'Para hoje, informe apenas horários que ainda não passaram.')
        return cleaned


class DisponibilidadeForm(forms.ModelForm):
    class Meta:
        model = Disponibilidade
        fields = ['profissional', 'data', 'horario', 'ativo']
        widgets = {
            'data': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'horario': forms.TimeInput(attrs={'type': 'time'}, format='%H:%M'),
        }

    def __init__(self, *args, responsavel, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['profissional'].queryset = Profissional.objects.filter(responsavel=responsavel)
        self.original_data = self.instance.data
        self.original_horario = self.instance.horario

    def clean(self):
        cleaned = super().clean()
        dia, horario = cleaned.get('data'), cleaned.get('horario')
        if dia and horario and (dia, horario) != (self.original_data, self.original_horario):
            agora = timezone.localtime()
            if dia < agora.date() or dia > agora.date() + timedelta(days=730) or dia.year > 2100:
                self.add_error('data', 'Escolha uma data futura nos próximos dois anos, até 2100.')
            elif dia == agora.date() and horario <= agora.time().replace(tzinfo=None):
                self.add_error('horario', 'Este horário já passou.')
        return cleaned


class PacienteAgendamentoForm(forms.Form):
    profissional = forms.ModelChoiceField(queryset=Profissional.objects.none(), label='Nutricionista', empty_label='Selecione um nutricionista')
    data = forms.ChoiceField(label='Data do agendamento', choices=[])
    horario = forms.ChoiceField(label='Horário', choices=[])
    nome = forms.CharField(label='Nome do paciente', max_length=150, widget=forms.TextInput(attrs={'autocomplete': 'name'}))
    idade = forms.IntegerField(label='Idade', min_value=0, max_value=120, widget=forms.NumberInput(attrs={'inputmode': 'numeric'}))
    contato = forms.CharField(label='Contato (telefone ou e-mail)', max_length=120, widget=forms.TextInput(attrs={'placeholder': '(16) 99999-9999 ou voce@exemplo.com'}))
    tem_problemas_saude = forms.TypedChoiceField(label='Tem problemas de saúde?', choices=[('', 'Selecione'), ('nao', 'Não'), ('sim', 'Sim')], coerce=lambda value: value == 'sim')
    problemas_saude = forms.CharField(label='Quais problemas de saúde? (opcional)', max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 2}))
    usa_medicacoes = forms.TypedChoiceField(label='Usa medicações?', choices=[('', 'Selecione'), ('nao', 'Não'), ('sim', 'Sim')], coerce=lambda value: value == 'sim')
    medicacoes = forms.CharField(label='Quais medicações? (opcional)', max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 2}))
    ultimos_exames = forms.CharField(label='Última vez que fez exames (opcional)', max_length=200, required=False, widget=forms.TextInput(attrs={'placeholder': 'Ex.: há 6 meses, em março de 2026 ou não lembro'}))
    motivo_consulta = forms.CharField(label='Motivo da consulta', max_length=2000, widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'O que você busca com o acompanhamento nutricional?'}))
    observacoes = forms.CharField(label='Observações (opcional)', max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, formulario, **kwargs):
        super().__init__(*args, **kwargs)
        self.formulario = formulario
        self.slots = Disponibilidade.objects.livres().filter(formulario=formulario)
        self.fields['profissional'].queryset = Profissional.objects.filter(pk__in=self.slots.values('profissional_id'))
        # Rebuild dependent choices from current database values on every GET/POST.
        profissional = self.data.get('profissional') if self.is_bound else self.initial.get('profissional')
        try:
            profissional_id = int(profissional)
        except (ValueError, TypeError):
            profissional_id = None
        slots = self.slots.filter(profissional_id=profissional_id)
        dates = sorted(set(slots.values_list('data', flat=True)))
        self.fields['data'].choices = [('', 'Selecione uma data')] + [(d.isoformat(), d.strftime('%d/%m/%Y')) for d in dates]
        selected = self.data.get('data') if self.is_bound else self.initial.get('data')
        if selected in {d.isoformat() for d in dates}:
            times = slots.filter(data=selected).values_list('horario', flat=True)
            self.fields['horario'].choices = [('', 'Selecione um horário')] + [(h.strftime('%H:%M'), h.strftime('%H:%M')) for h in times]
        else:
            self.fields['horario'].choices = [('', 'Selecione primeiro a data')]

    def clean_contato(self):
        value = self.cleaned_data['contato'].strip()
        if '@' in value:
            validate_email(value)
        elif not re.fullmatch(r'[\d\s()+.-]+', value) or not 10 <= len(re.sub(r'\D', '', value)) <= 15:
            raise ValidationError('Informe um telefone com DDD ou um e-mail válido.')
        return value

    def clean(self):
        cleaned = super().clean()
        profissional, dia, horario = (cleaned.get(key) for key in ('profissional', 'data', 'horario'))
        if profissional and dia and horario:
            slot = self.slots.filter(profissional=profissional, data=dia, horario=horario).first()
            if slot is None:
                self.add_error('horario', 'Este horário não está mais disponível. Escolha outro.')
            else:
                cleaned['slot'] = slot
        if cleaned.get('tem_problemas_saude') is False:
            cleaned['problemas_saude'] = ''
        if cleaned.get('usa_medicacoes') is False:
            cleaned['medicacoes'] = ''
        return cleaned

    def dados_ficha(self):
        return {field.name: self.cleaned_data[field.name] for field in FichaPaciente._meta.fields if field.name not in ('id', 'agendamento')}
