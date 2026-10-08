from django import forms

from .models import Agendamento, Cliente, RegistroSessao
from django.contrib.auth import get_user_model


class SituacaoForm(forms.Form):
    status_anterior = forms.ChoiceField(choices=Agendamento.Status.choices, widget=forms.HiddenInput)
    motivo = forms.CharField(label='Motivo do cancelamento (opcional)', required=False, max_length=2000,
        widget=forms.Textarea(attrs={'rows': 3}))


class SessaoForm(forms.ModelForm):
    versao_atual = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    class Meta:
        model = RegistroSessao
        fields = ['observacoes', 'plano_alimentar', 'orientacoes']
        widgets = {key: forms.Textarea(attrs={'rows': 5}) for key in fields}


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ['nome', 'email', 'telefone']

    def clean_telefone(self):
        value = self.cleaned_data.get('telefone', '').strip()
        if value:
            digits = ''.join(c for c in value if c.isdigit())
            if not 10 <= len(digits) <= 15 or any(c not in '0123456789 ()+.-' for c in value):
                raise forms.ValidationError('Informe um telefone com DDD, de 10 a 15 dígitos.')
            return digits
        return value


class VincularClienteForm(forms.Form):
    cliente_anterior = forms.IntegerField(widget=forms.HiddenInput)
    cliente = forms.ModelChoiceField(queryset=Cliente.objects.none(), label='Paciente do catálogo',
        help_text='Selecione o cadastro correto. As respostas originais e o registro da sessão serão preservados.')

    def __init__(self, *args, responsavel, atual, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cliente'].queryset = Cliente.objects.filter(nutricionista=responsavel).exclude(pk=atual)


class MembroEquipeForm(forms.Form):
    usuario = forms.CharField(label='Usuário de acesso do nutricionista', max_length=150,
        help_text='Informe o login de um usuário já cadastrado. Ele terá acesso aos pacientes e atendimentos desta conta.')

    def __init__(self, *args, responsavel, **kwargs):
        super().__init__(*args, **kwargs)
        self.responsavel = responsavel

    def clean_usuario(self):
        value = self.cleaned_data['usuario']
        user = get_user_model().objects.filter(username=value, is_active=True).first()
        if not user:
            raise forms.ValidationError('Não foi encontrado um usuário ativo com esse login.')
        if user.pk == self.responsavel.pk:
            raise forms.ValidationError('Você já tem acesso à sua conta.')
        return user
