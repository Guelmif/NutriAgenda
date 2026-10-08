import uuid
from datetime import timedelta, time
from types import SimpleNamespace

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .forms import PacienteAgendamentoForm
from .models import Agendamento, Cliente, Disponibilidade, FichaPaciente, FormularioAgendamento, ModeloFormulario, Profissional
from .questionarios import PADRAO, campos_base
from .services import reservar_consulta


class QuestionariosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user('dona', password='teste')
        cls.other = get_user_model().objects.create_user('outra', password='teste')
        cls.item = FormularioAgendamento.objects.create(responsavel=cls.owner, titulo='Primeira consulta')
        cls.prof = Profissional.objects.create(responsavel=cls.owner, nome='Profissional de teste')
        cls.day = timezone.localdate() + timedelta(days=2)
        cls.slot = Disponibilidade.objects.create(formulario=cls.item, profissional=cls.prof, data=cls.day, horario=time(9))

    def setUp(self):
        self.item.refresh_from_db()
        self.editor = reverse('agenda:editar_perguntas', args=[self.item.token])
        self.public = reverse('agenda:formulario_publico', args=[self.item.token])
        self.payload = {'versao': self.item.versao, 'profissional': self.prof.pk, 'data': self.day.isoformat(),
            'horario': '09:00', 'nome': 'Paciente fictício', 'idade': '30', 'contato': 'paciente@example.com',
            'tem_problemas_saude': 'nao', 'usa_medicacoes': 'nao', 'motivo_consulta': 'Rotina alimentar'}
        self.question = {'identificador': str(uuid.uuid4()), 'rotulo': 'Como conheceu o consultório?',
            'tipo': 'escolha', 'ajuda': 'Escolha uma opção.', 'opcoes': ['Indicação', 'Internet'], 'obrigatoria': True}

    def schema_payload(self, questions=None, changes=None):
        questions = [self.question] if questions is None else questions
        data = {'versao': self.item.versao, 'base-TOTAL_FORMS': len(PADRAO), 'base-INITIAL_FORMS': len(PADRAO),
            'perguntas-TOTAL_FORMS': len(questions), 'perguntas-INITIAL_FORMS': len(self.item.perguntas)}
        for index, base in enumerate(campos_base(self.item.campos_padrao)):
            base.update((changes or {}).get(base['chave'], {}))
            for key, value in base.items():
                if isinstance(value, bool):
                    if value:
                        data[f'base-{index}-{key}'] = 'on'
                else:
                    data[f'base-{index}-{key}'] = value
        for index, q in enumerate(questions):
            for key, value in {**q, 'ordem': index + 1}.items():
                if key == 'opcoes':
                    value = '\n'.join(value)
                if isinstance(value, bool):
                    if value:
                        data[f'perguntas-{index}-{key}'] = 'on'
                else:
                    data[f'perguntas-{index}-{key}'] = value
        return data

    def save_questions(self, **kwargs):
        self.client.force_login(self.owner)
        response = self.client.post(self.editor, self.schema_payload(**kwargs))
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.payload['versao'] = self.item.versao
        return response

    def test_editor_adds_question_and_changes_builtin_label(self):
        self.save_questions(changes={'idade': {'rotulo': 'Idade em anos', 'ajuda': 'Informe a idade atual.'}})
        self.assertEqual(self.item.versao, 2)
        self.assertEqual(self.item.perguntas, [self.question])
        response = self.client.get(self.public)
        self.assertContains(response, 'Idade em anos')
        self.assertContains(response, 'Como conheceu o consultório?')
        self.assertContains(response, 'Escolha uma opção.')

    def test_public_validation_and_snapshot_survive_edit_and_removal(self):
        self.save_questions()
        key = 'pergunta_' + self.question['identificador']
        for answer in ['', 'Opção forjada']:
            response = self.client.post(self.public, {**self.payload, key: answer})
            self.assertIn(key, response.context['form'].errors)
        self.assertEqual(Cliente.objects.count(), 0)
        self.assertEqual(self.client.post(self.public, {**self.payload, key: 'Indicação'}).status_code, 302)
        appointment = Agendamento.objects.get()
        readonly = admin.site._registry[FichaPaciente].get_readonly_fields(None, appointment.ficha)
        self.assertIn('respostas', readonly)
        self.assertIn('motivo_consulta', readonly)
        self.save_questions(questions=[], changes={'motivo_consulta': {'rotulo': 'Objetivo atual'}})
        response = self.client.get(reverse('agenda:detalhes_agendamento', args=[appointment.pk]))
        self.assertContains(response, 'Como conheceu o consultório?')
        self.assertContains(response, 'Indicação')
        self.assertContains(response, 'Motivo da consulta')
        self.assertNotContains(response, 'Objetivo atual')
        self.assertNotContains(self.client.get(self.public), 'Como conheceu o consultório?')

    def test_hidden_builtin_fields_are_optional_and_not_stored_from_forged_post(self):
        changes = {key: {'ativa': False} for key in PADRAO if key not in {'profissional','data','horario','nome','contato'}}
        self.save_questions(questions=[], changes=changes)
        response = self.client.post(self.public, self.payload)
        self.assertEqual(response.status_code, 302)
        ficha = Agendamento.objects.get().ficha
        self.assertIsNone(ficha.idade)
        self.assertIsNone(ficha.tem_problemas_saude)
        self.assertEqual(ficha.motivo_consulta, '')
        self.assertEqual(len(ficha.respostas), 2)  # Name and contact.

    def test_essential_fields_cannot_be_removed(self):
        self.save_questions(questions=[], changes={'nome': {'ativa': False, 'obrigatoria': False}})
        self.assertTrue(self.item.campos_padrao['nome']['ativa'])
        response = self.client.post(self.public, {**self.payload, 'nome': ''})
        self.assertIn('nome', response.context['form'].errors)

    def test_all_supported_question_types_are_validated(self):
        questions = [{**self.question, 'identificador': str(uuid.uuid4()), 'tipo': kind, 'rotulo': kind,
            'opcoes': ['A', 'B'] if kind == 'escolha' else []} for kind in ['texto','longo','numero','data','sim_nao','escolha']]
        self.save_questions(questions=questions)
        values = ['Resposta', 'Texto maior', '72.50', '2026-10-01', 'nao', 'A']
        payload = {**self.payload, **{'pergunta_'+q['identificador']: value for q, value in zip(questions, values)}}
        self.assertEqual(self.client.post(self.public, {**payload, 'pergunta_'+questions[2]['identificador']: 'abc'}).status_code, 200)
        self.assertEqual(self.client.post(self.public, payload).status_code, 302)
        responses = Agendamento.objects.get().ficha.respostas[-6:]
        self.assertEqual([r['resposta'] for r in responses], ['Resposta','Texto maior','72.50','01/10/2026','Não','A'])

    def test_optional_boolean_without_answer_is_not_false(self):
        self.save_questions(questions=[], changes={'tem_problemas_saude': {'obrigatoria': False}})
        self.payload.pop('tem_problemas_saude')
        self.assertEqual(self.client.post(self.public, self.payload).status_code, 302)
        ficha = Agendamento.objects.get().ficha
        self.assertIsNone(ficha.tem_problemas_saude)
        self.assertEqual(next(r['resposta'] for r in ficha.respostas if r['identificador']=='tem_problemas_saude'), 'Não informado')

    def test_conditional_required_details_only_for_yes(self):
        self.save_questions(questions=[], changes={'problemas_saude': {'obrigatoria': True}})
        response = self.client.post(self.public, {**self.payload, 'tem_problemas_saude': 'sim'})
        self.assertIn('problemas_saude', response.context['form'].errors)
        self.assertEqual(self.client.post(self.public, self.payload).status_code, 302)

    def test_invalid_editor_schemas_do_not_change_database(self):
        self.client.force_login(self.owner)
        cases = []
        data = self.schema_payload(); data['perguntas-0-opcoes'] = 'A\nA'; cases.append(data)
        data = self.schema_payload(); data['base-0-chave'] = 'nome'; cases.append(data)
        data = self.schema_payload(); data['perguntas-0-tipo'] = 'html'; cases.append(data)
        data = self.schema_payload(); data['perguntas-TOTAL_FORMS'] = 500; cases.append(data)
        data = self.schema_payload(questions=[self.question, self.question]); cases.append(data)
        data = self.schema_payload(changes={'tem_problemas_saude': {'ativa': False}}); cases.append(data)
        for data in cases:
            with self.subTest(data=data):
                self.assertEqual(self.client.post(self.editor, data).status_code, 200)
                self.item.refresh_from_db()
                self.assertEqual(self.item.perguntas, [])
                self.assertEqual(self.item.versao, 1)

    def test_saved_template_is_persistent_private_and_creates_independent_forms(self):
        self.save_questions()
        save = reverse('agenda:salvar_modelo', args=[self.item.token])
        self.assertEqual(self.client.post(save, {'nome': 'Primeira consulta completa'}).status_code, 302)
        model = ModeloFormulario.objects.get()
        self.assertEqual(model.perguntas, self.item.perguntas)
        self.assertContains(self.client.get(reverse('agenda:formularios')), model.nome)
        new = reverse('agenda:criar_formulario')
        for _ in range(2):
            self.assertEqual(self.client.post(new, {'modelo': model.pk, 'titulo': 'Ignorado', 'ativo': 'on'}).status_code, 302)
        forms = list(FormularioAgendamento.objects.exclude(pk=self.item.pk))
        self.assertEqual(forms[0].perguntas, model.perguntas)
        self.assertEqual(forms[0].titulo, self.item.titulo)
        self.assertNotEqual(forms[0].token, forms[1].token)
        self.assertFalse(forms[0].disponibilidades.exists())
        self.assertFalse(forms[1].disponibilidades.exists())
        self.save_questions(questions=[])
        forms[0].refresh_from_db(); model.refresh_from_db()
        self.assertEqual(forms[0].perguntas, [self.question])
        self.assertEqual(model.perguntas, [self.question])
        self.client.force_login(self.other)
        response = self.client.post(new, {'modelo': model.pk, 'titulo': 'Outro', 'ativo': 'on'})
        self.assertIn('modelo', response.context['form'].errors)
        self.assertNotContains(self.client.get(reverse('agenda:formularios')), model.nome)
        self.assertEqual(self.client.get(reverse('agenda:editar_modelo', args=[model.pk])).status_code, 404)

    def test_edit_saved_model_affects_only_future_forms(self):
        model = ModeloFormulario.objects.create(responsavel=self.owner, nome='Modelo inicial', titulo='Consulta')
        self.client.force_login(self.owner)
        data = self.schema_payload()
        data.update({'modelo-nome': 'Modelo atualizado', 'modelo-titulo': 'Novo título', 'modelo-descricao': 'Nova mensagem'})
        response = self.client.post(reverse('agenda:editar_modelo', args=[model.pk]), data)
        self.assertEqual(response.status_code, 302)
        model.refresh_from_db()
        self.assertEqual(model.nome, 'Modelo atualizado')
        self.assertEqual(model.perguntas, [self.question])
        self.item.refresh_from_db()
        self.assertEqual(self.item.perguntas, [])
        self.assertEqual(self.client.post(reverse('agenda:criar_formulario'), {'modelo': model.pk, 'titulo': 'Consulta', 'ativo': 'on'}).status_code, 302)
        self.assertEqual(FormularioAgendamento.objects.exclude(pk=self.item.pk).get().titulo, 'Novo título')
        old_version = model.versao
        model.nome = 'Nome no admin'
        admin.site._registry[ModeloFormulario].save_model(SimpleNamespace(user=self.owner), model, None, True)
        model.refresh_from_db()
        self.assertEqual(model.versao, old_version + 1)
        self.assertEqual(model.perguntas, [self.question])


    def test_owner_and_csrf_protection_on_edit_and_save(self):
        save = reverse('agenda:salvar_modelo', args=[self.item.token])
        self.assertEqual(self.client.get(self.editor).status_code, 302)
        self.client.force_login(self.other)
        for url in [self.editor, save]:
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(self.client.post(url, {}).status_code, 404)
        strict = Client(enforce_csrf_checks=True); strict.force_login(self.owner)
        self.assertEqual(strict.post(self.editor, self.schema_payload()).status_code, 403)
        self.assertEqual(strict.post(save, {'nome': 'Teste'}).status_code, 403)

    def test_outdated_editor_and_patient_cannot_overwrite_or_book(self):
        old = self.schema_payload()
        self.save_questions()
        self.assertEqual(self.client.post(self.editor, old).status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.versao, 2)
        key = 'pergunta_'+self.question['identificador']
        response = self.client.post(self.public, {**self.payload, 'versao': 1, key: 'Internet'})
        self.assertContains(response, 'As perguntas foram atualizadas')
        self.assertContains(response, 'name="versao" value="2"')
        self.assertEqual(Agendamento.objects.count(), 0)
        self.assertEqual(self.client.post(self.public, {**self.payload, key: 'Internet'}).status_code, 302)

    def test_service_rechecks_schema_after_validation(self):
        form = PacienteAgendamentoForm(self.payload, formulario=self.item)
        self.assertTrue(form.is_valid())
        self.save_questions()
        with self.assertRaises(ValidationError):
            reservar_consulta(form)
        self.assertEqual(Cliente.objects.count(), 0)

    def test_question_html_is_escaped_in_public_form_and_details(self):
        self.question['rotulo'] = '<script>alert(1)</script>'
        self.save_questions()
        self.assertNotContains(self.client.get(self.public), '<script>alert(1)</script>')
        self.assertEqual(self.client.post(self.public, {**self.payload, 'pergunta_'+self.question['identificador']: 'Internet'}).status_code, 302)
        detail = self.client.get(reverse('agenda:detalhes_agendamento', args=[Agendamento.objects.get().pk]))
        self.assertContains(detail, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(detail, '<script>alert(1)</script>')
