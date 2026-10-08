from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, time
from threading import Barrier
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, close_old_connections, transaction
from django.test import Client, RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .forms import PacienteAgendamentoForm
from .models import Agendamento, Cliente, Disponibilidade, FichaPaciente, FormularioAgendamento, Profissional
from .services import reservar_consulta


class FormulariosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user(username='clinica', password='senha-teste')
        cls.other = get_user_model().objects.create_user(username='outra-clinica', password='senha-teste')
        cls.prof = Profissional.objects.create(responsavel=cls.owner, nome='Ana Nutricionista', crn='12345')
        cls.other_prof = Profissional.objects.create(responsavel=cls.other, nome='Outro profissional')
        cls.formulario = FormularioAgendamento.objects.create(responsavel=cls.owner)
        cls.other_form = FormularioAgendamento.objects.create(responsavel=cls.other)
        cls.dia = timezone.localdate() + timedelta(days=2)
        cls.slot = Disponibilidade.objects.create(formulario=cls.formulario, profissional=cls.prof, data=cls.dia, horario=time(9))
        cls.other_slot = Disponibilidade.objects.create(formulario=cls.other_form, profissional=cls.other_prof, data=cls.dia, horario=time(10))

    def setUp(self):
        self.url = reverse('agenda:formulario_publico', args=[self.formulario.token])
        self.config_url = reverse('agenda:editar_formulario', args=[self.formulario.token])
        self.payload = {
            'profissional': self.prof.pk, 'data': self.dia.isoformat(), 'horario': '09:00',
            'nome': 'Paciente de teste', 'idade': 28, 'contato': '(16) 99999-9999',
            'tem_problemas_saude': 'sim', 'problemas_saude': 'Informação de saúde de teste',
            'usa_medicacoes': 'sim', 'medicacoes': 'Medicação de teste',
            'ultimos_exames': 'Há seis meses', 'motivo_consulta': 'Acompanhamento alimentar',
            'observacoes': 'Observação de teste',
        }

    def book(self):
        response = self.client.post(self.url, self.payload)
        self.assertEqual(response.status_code, 302)
        return Agendamento.objects.get(disponibilidade=self.slot)

    def test_public_form_has_requested_fields_without_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for label in ['Nutricionista', 'Data do agendamento', 'Horário', 'Nome do paciente', 'Idade', 'Contato', 'Tem problemas de saúde?', 'Usa medicações?', 'Última vez que fez exames', 'Motivo da consulta', 'Observações']:
            self.assertContains(response, label)
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_submission_persists_all_fields_and_integrates_calendar(self):
        consulta = self.book()
        self.assertEqual(consulta.cliente.nutricionista, self.owner)
        self.assertEqual(consulta.profissional, self.prof)
        self.assertEqual(consulta.status, 'pendente')
        self.assertEqual(consulta.ficha.idade, 28)
        self.assertEqual(consulta.ficha.contato, self.payload['contato'])
        for key in ['problemas_saude', 'medicacoes', 'ultimos_exames', 'motivo_consulta', 'observacoes']:
            self.assertEqual(getattr(consulta.ficha, key), self.payload[key])
        self.assertEqual(consulta.cliente.telefone, '16999999999')
        self.client.force_login(self.owner)
        result = self.client.get(reverse('agenda:agendamentos_do_dia'), {'data': self.dia.isoformat()}).json()
        self.assertEqual(len(result['agendamentos']), 1)
        self.assertEqual(result['agendamentos'][0]['nutricionista'], self.prof.nome)
        self.assertIn('detalhes_url', result['agendamentos'][0])
        self.assertNotIn('medicacoes', str(result))

    def test_public_availability_exposes_only_open_future_slots(self):
        Disponibilidade.objects.create(formulario=self.formulario, profissional=self.prof, data=timezone.localdate()-timedelta(days=1), horario=time(8))
        Disponibilidade.objects.create(formulario=self.formulario, profissional=self.prof, data=self.dia, horario=time(11), ativo=False)
        url = reverse('agenda:disponibilidades_publicas', args=[self.formulario.token])
        response = self.client.get(url, {'profissional': self.prof.pk})
        self.assertEqual(response.json(), {'datas': [{'valor': self.dia.isoformat(), 'rotulo': self.dia.strftime('%d/%m/%Y'), 'horarios': ['09:00']}]})
        self.book()
        self.assertEqual(self.client.get(url, {'profissional': self.prof.pk}).json(), {'datas': []})
        self.assertEqual(self.client.get(url, {'profissional': self.other_prof.pk}).json(), {'datas': []})
        self.assertEqual(self.client.get(url, {'profissional': 'invalid'}).status_code, 400)

    def test_second_submission_does_not_double_book_or_create_patient(self):
        self.book()
        response = self.client.post(self.url, self.payload)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['form'].errors)
        self.assertEqual(Agendamento.objects.count(), 1)
        self.assertEqual(Cliente.objects.count(), 1)

    def test_service_rechecks_an_already_validated_stale_form(self):
        first = PacienteAgendamentoForm(self.payload, formulario=self.formulario)
        stale = PacienteAgendamentoForm(self.payload, formulario=self.formulario)
        self.assertTrue(first.is_valid())
        self.assertTrue(stale.is_valid())
        reservar_consulta(first)
        with self.assertRaises(ValidationError):
            reservar_consulta(stale)
        self.assertEqual(Cliente.objects.count(), 1)

    def test_changed_or_paused_slot_rejects_stale_submission(self):
        form = PacienteAgendamentoForm(self.payload, formulario=self.formulario)
        self.assertTrue(form.is_valid())
        self.slot.horario = time(12)
        self.slot.save()
        with self.assertRaises(ValidationError):
            reservar_consulta(form)
        self.assertEqual(Agendamento.objects.count(), 0)

    def test_forged_foreign_professional_date_and_time_rejected(self):
        for replacements in [
            {'profissional': self.other_prof.pk}, {'data': (self.dia+timedelta(days=1)).isoformat()},
            {'horario': '19:00'}, {'idade': -1}, {'idade': 121},
            {'contato': 'invalido'}, {'tem_problemas_saude': ''}, {'usa_medicacoes': ''},
        ]:
            with self.subTest(replacements=replacements):
                response = self.client.post(self.url, {**self.payload, **replacements})
                self.assertTrue(response.context['form'].errors)
        self.assertEqual(Agendamento.objects.count(), 0)

    def test_optional_fields_and_no_answers(self):
        self.payload.update(tem_problemas_saude='nao', usa_medicacoes='nao', contato='paciente@example.com', ultimos_exames='', observacoes='')
        consulta = self.book()
        self.assertEqual(consulta.ficha.problemas_saude, '')
        self.assertEqual(consulta.ficha.medicacoes, '')
        self.assertFalse(consulta.ficha.tem_problemas_saude)
        self.assertEqual(consulta.cliente.email, 'paciente@example.com')

    def test_cancelled_appointment_releases_the_slot(self):
        consulta = self.book()
        consulta.status = 'cancelado'
        consulta.save()
        self.assertTrue(Disponibilidade.objects.livres().filter(pk=self.slot.pk).exists())
        self.assertEqual(self.client.post(self.url, self.payload).status_code, 302)
        self.assertEqual(Agendamento.objects.count(), 2)

    def test_database_constraint_blocks_manual_duplicate_booking(self):
        consulta = self.book()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Agendamento.objects.create(cliente=consulta.cliente, profissional=self.prof, data=self.dia, horario=time(9))

    def test_inactive_form_or_professional_cannot_be_booked(self):
        self.prof.ativo = False
        self.prof.save()
        self.assertFalse(Disponibilidade.objects.livres().filter(formulario=self.formulario).exists())
        response = self.client.post(self.url, self.payload)
        self.assertTrue(response.context['form'].errors)
        self.formulario.ativo = False
        self.formulario.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, self.payload).status_code, 404)

    def test_public_post_is_protected_by_csrf(self):
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url, self.payload).status_code, 403)

    def test_configuration_requires_login_and_owner(self):
        self.assertEqual(self.client.get(self.config_url).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.config_url).status_code, 404)
        self.assertEqual(self.client.post(self.config_url, {'acao': 'config', 'config-titulo': 'Ataque'}).status_code, 404)
        self.assertEqual(self.client.get(reverse('agenda:editar_profissional', args=[self.prof.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('agenda:editar_disponibilidade', args=[self.slot.pk])).status_code, 404)

    def test_owner_creates_and_edits_form_without_admin(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse('agenda:criar_formulario'), {'titulo': 'Meu atendimento', 'descricao': 'Texto editável', 'ativo': 'on'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(FormularioAgendamento.objects.filter(responsavel=self.owner).count(), 2)
        self.client.post(self.config_url, {'acao': 'config', 'config-titulo': 'Novo título', 'config-descricao': 'Mensagem nova', 'config-ativo': 'on'})
        self.formulario.refresh_from_db()
        self.assertEqual(self.formulario.titulo, 'Novo título')
        self.assertContains(self.client.get(self.url), 'Mensagem nova')

    def test_owner_can_add_professional_and_multiple_slots(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.config_url, {'acao': 'profissional', 'profissional-nome': 'Novo nutricionista', 'profissional-crn': '54321', 'profissional-ativo': 'on'})
        self.assertEqual(response.status_code, 302)
        novo = Profissional.objects.get(nome='Novo nutricionista')
        response = self.client.post(self.config_url, {'acao': 'horarios', 'horarios-profissional': novo.pk, 'horarios-data': self.dia.isoformat(), 'horarios-horarios': '08:00, 09:00, 10:30, 09:00'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Disponibilidade.objects.filter(profissional=novo).count(), 3)
        edited = self.client.post(reverse('agenda:editar_profissional', args=[novo.pk]), {'nome': 'Nome atualizado', 'crn': '54321', 'ativo': 'on'})
        self.assertEqual(edited.status_code, 302)
        novo.refresh_from_db()
        self.assertEqual(novo.nome, 'Nome atualizado')

    def test_other_form_slot_conflict_rolls_back_whole_batch(self):
        same_owner_form = FormularioAgendamento.objects.create(responsavel=self.owner)
        Disponibilidade.objects.create(formulario=same_owner_form, profissional=self.prof, data=self.dia, horario=time(12))
        self.client.force_login(self.owner)
        response = self.client.post(self.config_url, {'acao': 'horarios', 'horarios-profissional': self.prof.pk, 'horarios-data': self.dia.isoformat(), 'horarios-horarios': '11:00, 12:00'})
        self.assertTrue(response.context['horarios_form'].errors)
        self.assertFalse(Disponibilidade.objects.filter(profissional=self.prof, horario=time(11)).exists())

    def test_owner_can_edit_unbooked_slot_and_pause_booked_one(self):
        self.client.force_login(self.owner)
        edit = reverse('agenda:editar_disponibilidade', args=[self.slot.pk])
        response = self.client.post(edit, {'profissional': self.prof.pk, 'data': self.dia.isoformat(), 'horario': '10:30', 'ativo': 'on'})
        self.assertEqual(response.status_code, 302)
        self.slot.refresh_from_db()
        self.assertEqual(self.slot.horario, time(10, 30))
        self.payload['horario'] = '10:30'
        consulta = self.book()
        response = self.client.post(edit, {'profissional': self.prof.pk, 'data': self.dia.isoformat(), 'horario': '12:00', 'ativo': 'on'})
        self.assertTrue(response.context['form'].non_field_errors())
        response = self.client.post(reverse('agenda:alterar_disponibilidade', args=[self.slot.pk]), {'acao': 'desativar'})
        self.assertEqual(response.status_code, 302)
        consulta.refresh_from_db()
        self.assertEqual(consulta.horario, time(10, 30))
        self.assertFalse(Disponibilidade.objects.livres().filter(pk=self.slot.pk).exists())

    def test_owner_cannot_add_foreign_professional_slots(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.config_url, {'acao': 'horarios', 'horarios-profissional': self.other_prof.pk, 'horarios-data': self.dia.isoformat(), 'horarios-horarios': '15:00'})
        self.assertTrue(response.context['horarios_form'].errors)

    def test_patient_details_are_private_to_owner(self):
        consulta = self.book()
        url = reverse('agenda:detalhes_agendamento', args=[consulta.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.owner)
        response = self.client.get(url)
        self.assertContains(response, 'Medicação de teste')
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_ficha_failure_rolls_back_patient_and_reservation(self):
        form = PacienteAgendamentoForm(self.payload, formulario=self.formulario)
        self.assertTrue(form.is_valid())
        with patch('agenda.services.FichaPaciente.objects.create', side_effect=IntegrityError):
            with self.assertRaises(IntegrityError):
                reservar_consulta(form)
        self.assertEqual(Cliente.objects.count(), 0)
        self.assertEqual(Agendamento.objects.count(), 0)

    def test_admin_filters_new_models_by_owner(self):
        consulta = self.book()
        request = RequestFactory().get('/admin/')
        request.user = self.owner
        for model, expected in [(Profissional, [self.prof]), (FormularioAgendamento, [self.formulario]), (Disponibilidade, [self.slot]), (FichaPaciente, [consulta.ficha])]:
            self.assertEqual(list(admin.site._registry[model].get_queryset(request)), expected)


class ReservaConcorrenteTests(TransactionTestCase):
    def test_two_patients_cannot_reserve_the_same_slot_at_once(self):
        owner = get_user_model().objects.create_user(username='concorrencia')
        professional = Profissional.objects.create(responsavel=owner, nome='Nutricionista')
        formulario = FormularioAgendamento.objects.create(responsavel=owner)
        dia = timezone.localdate() + timedelta(days=2)
        Disponibilidade.objects.create(formulario=formulario, profissional=professional, data=dia, horario=time(9))
        payload = {
            'profissional': professional.pk, 'data': dia.isoformat(), 'horario': '09:00',
            'idade': 30, 'contato': '16999999999', 'tem_problemas_saude': 'nao',
            'usa_medicacoes': 'nao', 'motivo_consulta': 'Atendimento nutricional',
        }
        barrier = Barrier(2)

        def attempt(name):
            close_old_connections()
            try:
                item = FormularioAgendamento.objects.get(pk=formulario.pk)
                form = PacienteAgendamentoForm({**payload, 'nome': name}, formulario=item)
                assert form.is_valid(), form.errors
                barrier.wait(timeout=10)
                try:
                    reservar_consulta(form)
                    return 'reservado'
                except (ValidationError, IntegrityError, OperationalError):
                    return 'recusado'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, ['Paciente A', 'Paciente B']))
        self.assertEqual(sorted(results), ['recusado', 'reservado'])
        self.assertEqual(Agendamento.objects.count(), 1)
        self.assertEqual(Cliente.objects.count(), 1)
        self.assertEqual(FichaPaciente.objects.count(), 1)
