from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import Client, TestCase
from django.urls import reverse

from .models import Cliente, ControleSenha, FormularioAgendamento


class PrimeiroAcessoTests(TestCase):
    temporary_password = "Inicial!2026-Clinica"
    new_password = "Pessoal!2026-Diferente"

    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(
            username="administrador", password="Admin!2026-Clinica"
        )
        cls.existing = get_user_model().objects.create_user(
            username="existente", password=cls.temporary_password
        )
        cls.patient = Cliente.objects.create(
            nome="Paciente restrito", nutricionista=cls.existing
        )
        cls.public_form = FormularioAgendamento.objects.create(
            responsavel=cls.existing, titulo="Agendamento público"
        )

    def setUp(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin:auth_user_add"),
            {
                "username": "novo-usuario",
                "usable_password": "true",
                "password1": self.temporary_password,
                "password2": self.temporary_password,
                "_save": "Salvar",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.user = get_user_model().objects.get(username="novo-usuario")
        self.client.logout()

    def credentials(self, **overrides):
        values = {
            "old_password": self.temporary_password,
            "new_password1": self.new_password,
            "new_password2": self.new_password,
        }
        values.update(overrides)
        return values

    def test_admin_creation_marks_only_new_account(self):
        self.assertTrue(self.user.controle_senha.troca_obrigatoria)
        self.assertFalse(ControleSenha.objects.filter(usuario=self.admin).exists())
        self.assertFalse(ControleSenha.objects.filter(usuario=self.existing).exists())

    def test_first_login_goes_directly_to_password_change(self):
        destination = reverse("agenda:clientes") + "?q=Ana"
        response = self.client.post(
            reverse("login") + "?next=" + destination,
            {"username": self.user.username, "password": self.temporary_password},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response.url).path, reverse("password_change"))
        self.assertTrue(self.user.controle_senha.troca_obrigatoria)

    def test_wrong_password_does_not_authenticate_or_clear_requirement(self):
        response = self.client.post(
            reverse("login"), {"username": self.user.username, "password": "errada"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(ControleSenha.objects.get(usuario=self.user).troca_obrigatoria)

    def test_pending_user_cannot_bypass_gate_through_pages_api_or_admin(self):
        self.client.force_login(self.user)
        for url in (
            reverse("agenda:calendario"),
            reverse("agenda:clientes"),
            reverse("agenda:detalhes_cliente", args=[self.patient.pk]),
            reverse("agenda:agendamentos_do_dia") + "?data=2026-10-22",
            reverse("admin:index"),
            reverse("admin:password_change"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(
                    urlsplit(response.url).path, reverse("password_change")
                )
                self.assertNotIn(b"Paciente restrito", response.content)
                self.assertIn("no-store", response["Cache-Control"])

    def test_blocked_post_does_not_mutate_data_or_replay_submission(self):
        self.client.force_login(self.user)
        count = Cliente.objects.count()
        response = self.client.post(
            reverse("agenda:criar_cliente"), {"nome": "Não deve ser criado"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Cliente.objects.count(), count)
        self.assertEqual(parse_qs(urlsplit(response.url).query)["next"], ["/"])

    def test_pending_user_can_logout(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_public_booking_and_installation_routes_remain_available(self):
        for logged_in in (False, True):
            if logged_in:
                self.client.force_login(self.user)
            for url in (
                reverse("agenda:formulario_publico", args=[self.public_form.token]),
                reverse("agenda:manifest"),
                reverse("agenda:service_worker"),
            ):
                with self.subTest(logged_in=logged_in, url=url):
                    self.assertEqual(self.client.get(url).status_code, 200)

    def test_password_page_requires_login_and_is_not_cached(self):
        response = self.client.get(reverse("password_change"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(urlsplit(response.url).path, reverse("login"))
        self.client.force_login(self.user)
        response = self.client.get(reverse("password_change"))
        self.assertContains(response, "Defina sua nova senha")
        self.assertNotContains(response, 'aria-label="Consultório"')
        self.assertNotContains(response, 'id="install-banner"')
        self.assertIn("no-store", response["Cache-Control"])

    def test_invalid_passwords_keep_access_blocked_and_do_not_echo_passwords(self):
        self.client.force_login(self.user)
        for fields in (
            {"old_password": "incorreta"},
            {"new_password2": "diferente"},
            {"new_password1": "curta", "new_password2": "curta"},
            {"new_password1": "12345678", "new_password2": "12345678"},
            {
                "new_password1": self.temporary_password,
                "new_password2": self.temporary_password,
            },
        ):
            with self.subTest(fields=list(fields)):
                response = self.client.post(
                    reverse("password_change"), self.credentials(**fields)
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["form"].errors)
                self.assertNotContains(response, self.temporary_password)
                self.assertNotContains(response, self.new_password)
                self.user.refresh_from_db()
                self.assertTrue(self.user.check_password(self.temporary_password))
                self.assertTrue(
                    ControleSenha.objects.get(usuario=self.user).troca_obrigatoria
                )

    def test_success_preserves_current_session_and_invalidates_other_sessions(self):
        other_session = Client()
        self.client.force_login(self.user)
        other_session.force_login(self.user)
        response = self.client.post(reverse("password_change"), self.credentials())
        self.assertRedirects(response, reverse("agenda:calendario"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.new_password))
        self.assertFalse(self.user.check_password(self.temporary_password))
        policy = ControleSenha.objects.get(usuario=self.user)
        self.assertFalse(policy.troca_obrigatoria)
        self.assertIsNotNone(policy.alterada_em)
        self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))
        self.assertEqual(
            other_session.get(reverse("agenda:calendario")).status_code, 302
        )
        self.assertNotIn("_auth_user_id", other_session.session)

    def test_later_login_does_not_require_another_change(self):
        self.client.force_login(self.user)
        self.client.post(reverse("password_change"), self.credentials())
        self.client.logout()
        response = self.client.post(
            reverse("login"),
            {"username": self.user.username, "password": self.new_password},
        )
        self.assertRedirects(response, reverse("agenda:calendario"))

    def test_returns_to_safe_destination_after_change(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("password_change"), self.credentials(next="/clientes/?q=Ana")
        )
        self.assertEqual(response.url, "/clientes/?q=Ana")

    def test_rejects_external_and_recursive_return_urls(self):
        self.client.force_login(self.user)
        for destination in (
            "https://externo.example/",
            "//externo.example/",
            "/\\externo.example/",
            reverse("password_change"),
            reverse("login"),
            reverse("logout"),
            reverse("admin:password_change"),
            "/pagina-inexistente/",
        ):
            with self.subTest(destination=destination):
                response = self.client.get(
                    reverse("password_change"), {"next": destination}
                )
                self.assertEqual(response.context["next"], reverse("agenda:calendario"))

    def test_existing_accounts_continue_working_and_can_change_voluntarily(self):
        self.client.force_login(self.existing)
        self.assertEqual(self.client.get(reverse("agenda:calendario")).status_code, 200)
        response = self.client.post(reverse("password_change"), self.credentials())
        self.assertRedirects(response, reverse("agenda:calendario"))
        self.existing.refresh_from_db()
        self.assertTrue(self.existing.check_password(self.new_password))

    def test_staff_admin_login_cannot_bypass_password_requirement(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        response = self.client.post(
            reverse("admin:login"),
            {
                "username": self.user.username,
                "password": self.temporary_password,
                "next": "/admin/",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.request["PATH_INFO"], reverse("password_change"))
        response = self.client.post(
            reverse("password_change"), self.credentials(next="/admin/")
        )
        self.assertRedirects(response, "/admin/")

    def test_admin_can_require_change_for_existing_accounts_and_open_sessions(self):
        self.client.force_login(self.existing)
        admin_client = Client()
        admin_client.force_login(self.admin)
        response = admin_client.post(
            reverse("admin:auth_user_changelist"),
            {"action": "exigir_troca_senha", "_selected_action": [self.existing.pk]},
        )
        self.assertEqual(response.status_code, 302)
        response = self.client.get(reverse("agenda:calendario"))
        self.assertEqual(urlsplit(response.url).path, reverse("password_change"))

    def test_password_change_requires_csrf_token(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.user)
        response = browser.post(reverse("password_change"), self.credentials())
        self.assertEqual(response.status_code, 403)
        self.assertTrue(ControleSenha.objects.get(usuario=self.user).troca_obrigatoria)

    def test_policy_write_failure_rolls_back_password_change(self):
        self.client.force_login(self.user)
        with patch(
            "agenda.conta_views.ControleSenha.objects.update_or_create",
            side_effect=DatabaseError,
        ):
            with self.assertRaises(DatabaseError):
                self.client.post(reverse("password_change"), self.credentials())
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.temporary_password))
        self.assertTrue(ControleSenha.objects.get(usuario=self.user).troca_obrigatoria)
