from datetime import date, time
from io import StringIO

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Agendamento, Cliente


class AgendaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            username="nutri", password="senha-teste"
        )
        cls.other_user = get_user_model().objects.create_user(
            username="outra", password="senha-teste"
        )
        cls.cliente = Cliente.objects.create(nome="Ana Silva", nutricionista=cls.user)
        cls.other_client = Cliente.objects.create(
            nome="Cliente privado", nutricionista=cls.other_user
        )
        cls.date = date(2028, 2, 29)
        cls.first = Agendamento.objects.create(
            cliente=cls.cliente, data=cls.date, horario=time(8)
        )
        cls.second = Agendamento.objects.create(
            cliente=cls.cliente,
            data=cls.date,
            horario=time(15),
            status="pendente",
        )
        Agendamento.objects.create(
            cliente=cls.other_client, data=cls.date, horario=time(10)
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_calendar_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("agenda:calendario"))
        self.assertRedirects(response, "/entrar/?next=/", fetch_redirect_response=False)

    def test_api_requires_login(self):
        self.client.logout()
        response = self.client.get(
            reverse("agenda:agendamentos_do_dia"), {"data": self.date.isoformat()}
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(b"Cliente privado", response.content)

    def test_login_returns_to_calendar(self):
        self.client.logout()
        response = self.client.post(
            reverse("login"), {"username": "nutri", "password": "senha-teste"}
        )
        self.assertRedirects(response, reverse("agenda:calendario"))

    def test_calendar_renders_leap_year_and_only_current_users_data(self):
        response = self.client.get("/", {"mes": 2, "ano": 2028})
        self.assertEqual(response.status_code, 200)
        days = [day for week in response.context["semanas"] for day in week if day]
        self.assertEqual([day["numero"] for day in days], list(range(1, 30)))
        self.assertEqual(response.context["total"], 2)
        self.assertEqual(response.context["confirmados"], 1)
        self.assertEqual(response.context["pendentes"], 1)
        self.assertContains(response, "Ana Silva")
        self.assertNotContains(response, "Cliente privado")

    def test_calendar_starts_on_sunday_and_can_render_six_weeks(self):
        response = self.client.get("/", {"mes": 8, "ano": 2026})
        self.assertEqual(len(response.context["semanas"]), 6)
        self.assertEqual(response.context["semanas"][0][:6], [None] * 6)
        self.assertEqual(response.context["semanas"][0][6]["numero"], 1)

    def test_december_and_january_navigation(self):
        december = self.client.get("/", {"mes": 12, "ano": 2026})
        january = self.client.get("/", {"mes": 1, "ano": 2027})
        self.assertEqual(december.context["proximo"], (2027, 1))
        self.assertEqual(january.context["anterior"], (2026, 12))

    def test_calendar_boundaries(self):
        first = self.client.get("/", {"mes": 1, "ano": 1900})
        last = self.client.get("/", {"mes": 12, "ano": 2100})
        self.assertIsNone(first.context["anterior"])
        self.assertIsNone(last.context["proximo"])

    def test_invalid_months_return_400(self):
        for params in [
            {"mes": "abc"},
            {"mes": ""},
            {"mes": 0},
            {"mes": 13},
            {"ano": 0},
            {"ano": 9999},
            {"ano": "abc"},
        ]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get("/", params).status_code, 400)

    def test_api_returns_ordered_appointments_only_for_the_requested_day_and_user(self):
        Agendamento.objects.create(
            cliente=self.cliente, data=date(2028, 3, 1), horario=time(7)
        )
        response = self.client.get(
            reverse("agenda:agendamentos_do_dia"), {"data": "2028-02-29"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "data": "2028-02-29",
                "agendamentos": [
                    {
                        "id": self.first.pk,
                        "cliente": "Ana Silva",
                        "horario": "08:00",
                        "status": "confirmado",
                        "status_label": "Confirmado",
                        "detalhes_url": reverse(
                            "agenda:detalhes_agendamento", args=[self.first.pk]
                        ),
                    },
                    {
                        "id": self.second.pk,
                        "cliente": "Ana Silva",
                        "horario": "15:00",
                        "status": "pendente",
                        "status_label": "Pendente",
                        "detalhes_url": reverse(
                            "agenda:detalhes_agendamento", args=[self.second.pk]
                        ),
                    },
                ],
            },
        )
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_api_returns_empty_day(self):
        response = self.client.get(
            reverse("agenda:agendamentos_do_dia"), {"data": "2028-02-28"}
        )
        self.assertEqual(response.json()["agendamentos"], [])

    def test_api_invalid_dates(self):
        for value in [
            "",
            "2026-02-29",
            "2026-13-01",
            "invalid",
            "20260201",
            "1800-01-01",
        ]:
            with self.subTest(value=value):
                response = self.client.get(
                    reverse("agenda:agendamentos_do_dia"), {"data": value}
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("erro", response.json())

    def test_read_only_routes_reject_posts(self):
        self.assertEqual(self.client.post("/").status_code, 405)
        self.assertEqual(
            self.client.post(reverse("agenda:agendamentos_do_dia")).status_code, 405
        )

    def test_form_button_opens_creation_screen(self):
        response = self.client.get("/")
        self.assertContains(response, 'href="/formularios/novo/"')
        self.assertContains(response, "Criar formulário")
        self.assertNotContains(response, "Em breve")

    def test_admin_limits_querysets_and_client_choices_to_owner(self):
        request = RequestFactory().get("/admin/")
        request.user = self.user
        client_admin = admin.site._registry[Cliente]
        appointment_admin = admin.site._registry[Agendamento]
        self.assertEqual(list(client_admin.get_queryset(request)), [self.cliente])
        self.assertEqual(
            list(appointment_admin.get_queryset(request)), [self.first, self.second]
        )
        field = appointment_admin.formfield_for_foreignkey(
            Agendamento._meta.get_field("cliente"), request
        )
        self.assertEqual(list(field.queryset), [self.cliente])

    def test_admin_assigns_owner_on_client_creation(self):
        request = RequestFactory().post("/admin/")
        request.user = self.user
        client = Cliente(nome="Novo cliente")
        admin.site._registry[Cliente].save_model(
            request, client, form=None, change=False
        )
        self.assertEqual(client.nutricionista, self.user)

    def test_seed_demo_is_repeatable_and_does_not_change_real_appointments(self):
        output = StringIO()
        call_command("seed_demo", usuario=self.user.username, stdout=output)
        call_command("seed_demo", usuario=self.user.username, stdout=output)
        self.assertEqual(Cliente.objects.filter(nutricionista=self.user).count(), 5)
        self.assertEqual(
            Agendamento.objects.filter(cliente__nutricionista=self.user).count(), 12
        )
        self.first.refresh_from_db()
        self.assertEqual(self.first.status, "confirmado")
        self.assertEqual(
            Agendamento.objects.filter(
                data__year=timezone.localdate().year, cliente__nome__endswith="(demo)"
            ).count(),
            10,
        )

    def test_logout_requires_post(self):
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertRedirects(self.client.post(reverse("logout")), reverse("login"))
