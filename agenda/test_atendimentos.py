from datetime import timedelta, time
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .atendimento_services import alterar_situacao, salvar_sessao, vincular_cliente
from .models import Agendamento, AlteracaoStatus, Cliente, Disponibilidade, FichaPaciente, FormularioAgendamento, MembroEquipe, Profissional, RegistroSessao


class AtendimentosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = get_user_model()
        cls.owner = user.objects.create_user('clinica', password='teste')
        cls.member = user.objects.create_user('nutricionista-equipe', password='teste')
        cls.other = user.objects.create_user('outra-clinica', password='teste')
        cls.paciente = Cliente.objects.create(nutricionista=cls.owner, nome='Paciente de teste', email='paciente@example.com')
        cls.outro_paciente = Cliente.objects.create(nutricionista=cls.other, nome='Paciente privado')
        cls.prof = Profissional.objects.create(responsavel=cls.owner, nome='Ana Nutricionista')
        cls.prof2 = Profissional.objects.create(responsavel=cls.owner, nome='Bruno Nutricionista')
        cls.formulario = FormularioAgendamento.objects.create(responsavel=cls.owner)
        cls.dia = timezone.localdate() - timedelta(days=1)
        cls.consulta = Agendamento.objects.create(cliente=cls.paciente, profissional=cls.prof, data=cls.dia, horario=time(9), status='pendente')
        cls.privada = Agendamento.objects.create(cliente=cls.outro_paciente, data=cls.dia, horario=time(10))
        cls.future_slot = Disponibilidade.objects.create(formulario=cls.formulario, profissional=cls.prof, data=timezone.localdate()+timedelta(days=3), horario=time(9))
        cls.future = Agendamento.objects.create(cliente=cls.paciente, profissional=cls.prof, disponibilidade=cls.future_slot, data=cls.future_slot.data, horario=time(9), status='confirmado')
        cls.membership = MembroEquipe.objects.create(responsavel=cls.owner, usuario=cls.member)

    def setUp(self):
        self.client.force_login(self.owner)
        self.detail = reverse('agenda:detalhes_agendamento', args=[self.consulta.pk])
        self.record = {'versao_atual': 0, 'observacoes': 'Observação fictícia da sessão',
            'plano_alimentar': 'Plano fictício registrado pelo profissional', 'orientacoes': 'Retorno em 30 dias'}

    def change(self, action, status='pendente', pk=None, **data):
        return self.client.post(reverse('agenda:situacao_agendamento', args=[pk or self.consulta.pk, action]), {'status_anterior': status, **data})

    def test_confirm_complete_and_audit(self):
        self.assertEqual(self.change('confirmar').status_code, 302)
        self.assertEqual(self.change('concluir', 'confirmado').status_code, 302)
        self.consulta.refresh_from_db()
        self.assertEqual(self.consulta.status, 'concluido')
        self.assertIsNotNone(self.consulta.concluido_em)
        self.assertEqual(list(self.consulta.alteracoes_status.values_list('novo', flat=True)), ['concluido','confirmado'])
        self.assertTrue(all(x.realizado_por_id == self.owner.pk for x in self.consulta.alteracoes_status.all()))
        response = self.client.get('/', {'ano': self.dia.year, 'mes': self.dia.month})
        self.assertEqual(response.context['concluidos'], 1)
        self.assertContains(response, 'Concluído')
        api = self.client.get(reverse('agenda:agendamentos_do_dia'), {'data': self.dia.isoformat()}).json()
        self.assertEqual(api['agendamentos'][0]['status'], 'concluido')

    def test_cancellation_preserves_record_and_releases_future_slot(self):
        salvar_sessao(self.future.pk, self.owner, 0, self.record)
        response = self.change('cancelar', 'confirmado', pk=self.future.pk, motivo='Paciente pediu cancelamento')
        self.assertEqual(response.status_code, 302)
        self.future.refresh_from_db()
        self.assertEqual(self.future.status, 'cancelado')
        self.assertIsNotNone(self.future.cancelado_em)
        self.assertEqual(self.future.motivo_cancelamento, 'Paciente pediu cancelamento')
        self.assertTrue(Disponibilidade.objects.livres().filter(pk=self.future_slot.pk).exists())
        self.assertEqual(self.future.sessao.observacoes, self.record['observacoes'])
        self.assertContains(self.client.get(reverse('agenda:detalhes_agendamento', args=[self.future.pk])), self.record['plano_alimentar'])
        with self.assertRaises(ValidationError):
            salvar_sessao(self.future.pk, self.owner, 1, self.record)

    def test_completed_slot_never_reopens(self):
        slot = Disponibilidade.objects.create(formulario=self.formulario, profissional=self.prof2, data=self.dia, horario=time(11))
        item = Agendamento.objects.create(cliente=self.paciente, profissional=self.prof2, disponibilidade=slot, data=self.dia, horario=time(11), status='confirmado')
        alterar_situacao(item.pk, self.owner, 'confirmado', 'concluido')
        self.assertEqual(self.change('cancelar', 'concluido', pk=item.pk).status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.status, 'concluido')
        self.assertEqual(item.alteracoes_status.count(), 1)

    def test_future_completion_and_stale_or_invalid_transitions_rejected(self):
        response = self.change('concluir', 'confirmado', pk=self.future.pk)
        self.assertContains(response, 'Só é possível concluir')
        self.assertEqual(self.change('confirmar').status_code, 302)
        self.assertContains(self.change('cancelar'), 'já mudou')
        self.assertContains(self.change('confirmar', 'confirmado'), 'não está disponível')
        self.assertEqual(self.client.post(reverse('agenda:situacao_agendamento', args=[self.consulta.pk, 'invalida']), {}).status_code, 400)
        self.assertEqual(self.client.post(reverse('agenda:situacao_agendamento', args=[self.consulta.pk, 'cancelar']), {}).status_code, 200)
        self.consulta.refresh_from_db(); self.future.refresh_from_db()
        self.assertEqual(self.consulta.status, 'confirmado')
        self.assertEqual(self.future.status, 'confirmado')

    def test_get_review_does_not_mutate_and_csrf_required(self):
        url = reverse('agenda:situacao_agendamento', args=[self.consulta.pk, 'cancelar'])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.consulta.refresh_from_db(); self.assertEqual(self.consulta.status, 'pendente')
        strict = Client(enforce_csrf_checks=True); strict.force_login(self.owner)
        for target, data in [(url, {'status_anterior':'pendente'}), (self.detail,self.record), (reverse('agenda:equipe'), {'usuario':self.other.username})]:
            self.assertEqual(strict.post(target,data).status_code,403)

    def test_atomic_status_change_rolls_back_if_audit_fails(self):
        with patch('agenda.atendimento_services.AlteracaoStatus.objects.create', side_effect=IntegrityError):
            with self.assertRaises(IntegrityError):
                alterar_situacao(self.consulta.pk, self.owner, 'pendente', 'concluido')
        self.consulta.refresh_from_db()
        self.assertEqual(self.consulta.status, 'pendente')
        self.assertIsNone(self.consulta.concluido_em)

    def test_save_edit_and_preserve_form_answers(self):
        ficha = FichaPaciente.objects.create(agendamento=self.consulta, contato='paciente@example.com', respostas=[{'identificador':'nome','pergunta':'Nome original','resposta':'Paciente original'}])
        self.assertEqual(self.client.post(self.detail,self.record).status_code,302)
        self.assertEqual(self.client.post(self.detail,{**self.record,'versao_atual':1,'plano_alimentar':'Plano revisado'}).status_code,302)
        sessao=RegistroSessao.objects.get(agendamento=self.consulta)
        self.assertEqual(sessao.versao,2)
        self.assertEqual(sessao.atualizado_por,self.owner)
        self.assertEqual(sessao.plano_alimentar,'Plano revisado')
        self.assertEqual(list(sessao.revisoes.values_list('plano_alimentar',flat=True)), ['Plano revisado',self.record['plano_alimentar']])
        ficha.refresh_from_db(); self.assertEqual(ficha.respostas[0]['resposta'],'Paciente original')
        detail=self.client.get(reverse('agenda:detalhes_cliente',args=[self.paciente.pk]))
        self.assertContains(detail,'Plano revisado')
        self.assertContains(detail,self.record['observacoes'])

    def test_stale_session_does_not_overwrite_and_text_limit(self):
        self.assertEqual(self.client.post(self.detail,self.record).status_code,302)
        response=self.client.post(self.detail,{**self.record,'observacoes':'Outra edição'})
        self.assertContains(response,'Outro registro')
        self.assertContains(response,'Carregar registro atualizado')
        fresh=self.client.get(self.detail)
        self.assertEqual(fresh.context['sessao_form']['versao_atual'].value(),1)
        self.assertEqual(RegistroSessao.objects.get().observacoes,self.record['observacoes'])
        response=self.client.post(self.detail,{**self.record,'versao_atual':1,'plano_alimentar':'x'*10001})
        self.assertIn('plano_alimentar',response.context['sessao_form'].errors)
        self.assertNotContains(self.client.get(self.detail),'Versao atual')

    def test_revision_failure_rolls_back_note_edit(self):
        salvar_sessao(self.consulta.pk,self.owner,0,self.record)
        with patch('agenda.atendimento_services.RevisaoSessao.objects.create',side_effect=IntegrityError):
            with self.assertRaises(IntegrityError):
                salvar_sessao(self.consulta.pk,self.owner,1,{**self.record,'observacoes':'Não deve persistir'})
        sessao=RegistroSessao.objects.get(agendamento=self.consulta)
        self.assertEqual(sessao.versao,1)
        self.assertEqual(sessao.observacoes,self.record['observacoes'])
        self.assertEqual(sessao.revisoes.count(),1)

    def test_team_shares_history_all_professionals_notes_and_control(self):
        Agendamento.objects.create(cliente=self.paciente, profissional=self.prof2, data=self.dia, horario=time(12))
        self.client.force_login(self.member)
        for route in ['agenda:clientes','agenda:atendimentos']:
            response=self.client.get(reverse(route));self.assertContains(response,'Paciente de teste');self.assertNotContains(response,'Paciente privado')
            self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertEqual(self.client.post(self.detail,self.record).status_code,302)
        self.assertEqual(RegistroSessao.objects.get().atualizado_por,self.member)
        history=self.client.get(reverse('agenda:detalhes_cliente',args=[self.paciente.pk]))
        self.assertContains(history,self.prof.nome);self.assertContains(history,self.prof2.nome)
        self.assertContains(history,self.record['plano_alimentar'])
        self.assertEqual(self.change('concluir').status_code,302)
        self.assertEqual(AlteracaoStatus.objects.get().realizado_por,self.member)
        api=self.client.get(reverse('agenda:agendamentos_do_dia'),{'data':self.dia.isoformat()}).json()
        self.assertEqual(len(api['agendamentos']),2)
        self.assertEqual(self.client.get(reverse('agenda:editar_formulario',args=[self.formulario.token])).status_code,404)

    def test_no_unauthorized_access_and_revoke_membership(self):
        self.client.force_login(self.other)
        targets=[self.detail,reverse('agenda:detalhes_cliente',args=[self.paciente.pk]),reverse('agenda:editar_cliente',args=[self.paciente.pk]),reverse('agenda:situacao_agendamento',args=[self.consulta.pk,'cancelar']),reverse('agenda:vincular_agendamento',args=[self.consulta.pk])]
        for url in targets:
            self.assertEqual(self.client.get(url).status_code,404)
            self.assertIn(self.client.post(url,self.record).status_code,[404,405])
        self.client.force_login(self.member)
        self.membership.ativo=False;self.membership.save()
        for url in targets:
            self.assertEqual(self.client.get(url).status_code,404)
        self.assertNotContains(self.client.get(reverse('agenda:clientes')),'Paciente de teste')
        self.assertEqual(self.client.get('/').context['total'],0)

    def test_team_management_exact_user_idempotency_and_owner_permissions(self):
        url=reverse('agenda:equipe')
        for username in ['nao-existe',self.owner.username]:
            self.assertEqual(self.client.post(url,{'usuario':username}).status_code,200)
        for _ in range(2):
            self.assertEqual(self.client.post(url,{'usuario':self.member.username}).status_code,302)
        self.assertEqual(MembroEquipe.objects.filter(responsavel=self.owner,usuario=self.member).count(),1)
        access=reverse('agenda:alterar_membro',args=[self.membership.pk])
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(access,{'acao':'desativar'}).status_code,404)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(access).status_code,405)
        self.assertEqual(self.client.post(access,{'acao':'invalida'}).status_code,400)
        self.assertEqual(self.client.post(access,{'acao':'desativar'}).status_code,302)
        self.membership.refresh_from_db();self.assertFalse(self.membership.ativo)
        self.assertEqual(self.client.post(url,{'usuario':self.member.username}).status_code,302)
        self.membership.refresh_from_db();self.assertTrue(self.membership.ativo)

    def test_catalog_search_pagination_and_filters(self):
        self.assertContains(self.client.get(reverse('agenda:clientes'),{'q':'paciente@example.com'}),'Paciente de teste')
        self.assertNotContains(self.client.get(reverse('agenda:clientes'),{'q':'inexistente'}),'Paciente de teste')
        response=self.client.get(reverse('agenda:atendimentos'),{'status':'pendente','profissional':self.prof.pk})
        self.assertEqual(response.context['page'].paginator.count,1)
        self.assertEqual(self.client.get(reverse('agenda:atendimentos'),{'profissional':'9'*200}).status_code,200)
        for index in range(22):
            Cliente.objects.create(nutricionista=self.owner,nome=f'Outro paciente {index}')
        response=self.client.get(reverse('agenda:clientes'),{'page':2})
        self.assertEqual(response.context['page'].paginator.count,23)
        self.assertEqual(len(response.context['page']),3)

    def test_patient_creation_and_edits_by_team_are_scoped(self):
        self.client.force_login(self.member)
        url=reverse('agenda:criar_cliente')
        data={'nome':'Paciente cadastrado','email':'novo@example.com','telefone':'(16) 99999-9999','conta':self.owner.pk}
        self.assertEqual(self.client.post(url,{**data,'conta':self.other.pk}).status_code,200)
        self.assertEqual(self.client.post(url,data).status_code,302)
        paciente=Cliente.objects.get(nome=data['nome']);self.assertEqual(paciente.nutricionista,self.owner)
        self.assertEqual(paciente.telefone,'16999999999')
        self.assertEqual(self.client.post(reverse('agenda:editar_cliente',args=[paciente.pk]),{**data,'nome':'Nome revisado'}).status_code,302)
        paciente.refresh_from_db();self.assertEqual(paciente.nome,'Nome revisado')

    def test_link_consultation_to_existing_patient_preserves_session_and_limits_account(self):
        salvar_sessao(self.consulta.pk,self.owner,0,self.record)
        target=Cliente.objects.create(nutricionista=self.owner,nome='Paciente com histórico')
        url=reverse('agenda:vincular_agendamento',args=[self.consulta.pk])
        payload={'cliente_anterior':self.paciente.pk,'cliente':target.pk}
        self.assertEqual(self.client.post(url,{**payload,'cliente':self.outro_paciente.pk}).status_code,200)
        self.client.force_login(self.member)
        self.assertEqual(self.client.post(url,payload).status_code,302)
        self.consulta.refresh_from_db();self.assertEqual(self.consulta.cliente,target)
        self.assertEqual(self.consulta.sessao.observacoes,self.record['observacoes'])
        self.assertContains(self.client.get(reverse('agenda:detalhes_cliente',args=[target.pk])),self.record['plano_alimentar'])
        self.assertContains(self.client.post(url,{**payload,'cliente':self.paciente.pk}),'já mudou')
        self.assertTrue(Cliente.objects.filter(pk=self.paciente.pk).exists())

    def test_clinical_data_never_public_and_text_is_escaped(self):
        self.client.post(self.detail,{**self.record,'observacoes':'<script>alert(1)</script>'})
        self.assertContains(self.client.get(self.detail),'&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(self.client.get(self.detail),'<script>alert(1)</script>')
        self.client.logout()
        for url in [self.detail,reverse('agenda:clientes'),reverse('agenda:atendimentos'),reverse('agenda:detalhes_cliente',args=[self.paciente.pk]),reverse('agenda:equipe')]:
            response=self.client.get(url);self.assertEqual(response.status_code,302);self.assertNotIn(b'Plano fict',response.content)
        response=self.client.get(reverse('agenda:formulario_publico',args=[self.formulario.token]))
        self.assertNotContains(response,self.record['plano_alimentar'])
        public=self.client.get(reverse('agenda:disponibilidades_publicas',args=[self.formulario.token]),{'profissional':self.prof.pk})
        self.assertNotIn('Plano fict',str(public.json()))
        readonly=admin.site._registry[Agendamento].get_readonly_fields(None,self.consulta)
        self.assertIn('status',readonly)
        self.assertFalse(admin.site._registry[RegistroSessao].has_change_permission(None))
