"""Schema shared by saved templates, the editor and public forms."""
import uuid

from django import forms
from django.core.exceptions import ValidationError

# Essential scheduling/identity fields cannot be hidden or made optional.
ESSENCIAIS = {'profissional', 'data', 'horario', 'nome', 'contato'}
PADRAO = {
    'profissional': ('Nutricionista', True),
    'data': ('Data do agendamento', True),
    'horario': ('Horário', True),
    'nome': ('Nome do paciente', True),
    'idade': ('Idade', True),
    'contato': ('Contato (telefone ou e-mail)', True),
    'tem_problemas_saude': ('Tem problemas de saúde?', True),
    'problemas_saude': ('Quais problemas de saúde?', False),
    'usa_medicacoes': ('Usa medicações?', True),
    'medicacoes': ('Quais medicações?', False),
    'ultimos_exames': ('Última vez que fez exames', False),
    'motivo_consulta': ('Motivo da consulta', True),
    'observacoes': ('Observações', False),
}
TIPOS = [('texto', 'Resposta curta'), ('longo', 'Resposta longa'),
         ('numero', 'Número'), ('data', 'Data'), ('sim_nao', 'Sim ou não'),
         ('escolha', 'Escolha única')]


def campos_base(config):
    return [{'chave': key, 'rotulo': label, 'ajuda': '', 'obrigatoria': required,
             'ativa': True, **config.get(key, {})} for key, (label, required) in PADRAO.items()]


class CampoBaseForm(forms.Form):
    chave = forms.ChoiceField(choices=[(k, k) for k in PADRAO], widget=forms.HiddenInput)
    rotulo = forms.CharField(label='Pergunta', max_length=150)
    ajuda = forms.CharField(label='Texto de ajuda', max_length=300, required=False)
    obrigatoria = forms.BooleanField(label='Obrigatória', required=False)
    ativa = forms.BooleanField(label='Mostrar no formulário', required=False)

    def clean(self):
        data = super().clean()
        if data.get('chave') in ESSENCIAIS:
            data['ativa'] = data['obrigatoria'] = True
        return data


class BasesFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        keys = [form.cleaned_data.get('chave') for form in self.forms]
        if len(keys) != len(PADRAO) or set(keys) != set(PADRAO):
            raise ValidationError('Os campos básicos estão incompletos. Atualize a página.')
        config = {f.cleaned_data['chave']: f.cleaned_data for f in self.forms}
        for parent, child in [('tem_problemas_saude', 'problemas_saude'), ('usa_medicacoes', 'medicacoes')]:
            if not config[parent]['ativa'] and config[child]['ativa']:
                raise ValidationError('Para mostrar a pergunta de detalhes, mantenha também a pergunta de sim ou não correspondente.')


class PerguntaForm(forms.Form):
    identificador = forms.UUIDField(required=False, widget=forms.HiddenInput)
    rotulo = forms.CharField(label='Pergunta', max_length=150)
    tipo = forms.ChoiceField(label='Tipo de resposta', choices=TIPOS)
    ajuda = forms.CharField(label='Texto de ajuda', max_length=300, required=False)
    opcoes = forms.CharField(label='Opções de resposta', required=False, max_length=3000,
                             help_text='Para escolha única: uma opção por linha (até 30).',
                             widget=forms.Textarea(attrs={'rows': 3}))
    obrigatoria = forms.BooleanField(label='Obrigatória', required=False)
    ordem = forms.IntegerField(label='Ordem', min_value=1, max_value=1000, initial=1)

    def clean(self):
        data = super().clean()
        if data.get('tipo') == 'escolha':
            options = [x.strip() for x in data.get('opcoes', '').splitlines() if x.strip()]
            if not 2 <= len(options) <= 30 or len(set(options)) != len(options) or any(len(x) > 100 for x in options):
                self.add_error('opcoes', 'Informe de 2 a 30 opções diferentes, com até 100 caracteres cada.')
        else:
            options = []
        data['lista_opcoes'] = options
        return data


class PerguntasFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        ids = [f.cleaned_data.get('identificador') for f in self.forms if f.cleaned_data and not f.cleaned_data.get('DELETE')]
        ids = [x for x in ids if x]
        if len(ids) != len(set(ids)):
            raise ValidationError('Existem perguntas com identificadores repetidos. Atualize a página.')


BaseFormSet = forms.formset_factory(CampoBaseForm, formset=BasesFormSet, extra=0,
    min_num=len(PADRAO), max_num=len(PADRAO), validate_min=True, validate_max=True, absolute_max=len(PADRAO))
PerguntaFormSet = forms.formset_factory(PerguntaForm, formset=PerguntasFormSet, extra=0,
    can_delete=True, max_num=50, validate_max=True, absolute_max=50)


def editores(item, data=None):
    base = BaseFormSet(data, initial=campos_base(item.campos_padrao), prefix='base')
    initial = [{**q, 'opcoes': '\n'.join(q.get('opcoes', [])), 'ordem': i + 1} for i, q in enumerate(item.perguntas)]
    custom = PerguntaFormSet(data, initial=initial, prefix='perguntas')
    return base, custom


def salvar_schema(item, base, custom):
    item.campos_padrao = {f.cleaned_data['chave']: {k: f.cleaned_data[k] for k in ('rotulo', 'ajuda', 'obrigatoria', 'ativa')} for f in base}
    questions = [f.cleaned_data for f in custom if f.cleaned_data and not f.cleaned_data.get('DELETE')]
    item.perguntas = [{
        'identificador': str(q.get('identificador') or uuid.uuid4()),
        'rotulo': q['rotulo'], 'tipo': q['tipo'], 'ajuda': q['ajuda'],
        'obrigatoria': q['obrigatoria'], 'opcoes': q['lista_opcoes'],
    } for q in sorted(questions, key=lambda q: q['ordem'])]


def campo_personalizado(q):
    options = {'label': q['rotulo'], 'help_text': q.get('ajuda', ''), 'required': q['obrigatoria']}
    tipo = q['tipo']
    if tipo == 'numero':
        return forms.DecimalField(max_digits=12, decimal_places=2, **options)
    if tipo == 'data':
        return forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'), **options)
    if tipo in ('escolha', 'sim_nao'):
        choices = [(x, x) for x in q['opcoes']] if tipo == 'escolha' else [('sim', 'Sim'), ('nao', 'Não')]
        return forms.ChoiceField(choices=[('', 'Selecione')] + choices, **options)
    return forms.CharField(max_length=2000 if tipo == 'longo' else 300,
        widget=forms.Textarea(attrs={'rows': 3}) if tipo == 'longo' else forms.TextInput(), **options)
