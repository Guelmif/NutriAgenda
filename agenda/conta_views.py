from urllib.parse import urlencode, urlsplit

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.db import transaction
from django.urls import Resolver404, resolve, reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache

from .conta_forms import AlterarSenhaForm
from .models import ControleSenha


class EntrarView(LoginView):
    template_name = "agenda/login.html"
    redirect_authenticated_user = True

    def get_success_url(self):
        destination = super().get_success_url()
        if ControleSenha.objects.filter(
            usuario=self.request.user, troca_obrigatoria=True
        ).exists():
            return f"{reverse('password_change')}?{urlencode({'next': destination})}"
        return destination


@method_decorator(never_cache, name="dispatch")
class AlterarSenhaView(PasswordChangeView):
    template_name = "agenda/alterar_senha.html"
    form_class = AlterarSenhaForm

    def get_success_url(self):
        destination = self.request.POST.get("next") or self.request.GET.get("next", "")
        # Only local application routes may be used as a return destination.
        if destination.startswith("/") and url_has_allowed_host_and_scheme(
            destination,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            try:
                match = resolve(urlsplit(destination).path)
            except Resolver404:
                pass
            else:
                if match.view_name not in {
                    "password_change",
                    "login",
                    "logout",
                    "admin:login",
                    "admin:logout",
                    "admin:password_change",
                }:
                    return destination
        return reverse("agenda:calendario")

    def get_context_data(self, **kwargs):
        return super().get_context_data(next=self.get_success_url(), **kwargs)

    def form_valid(self, form):
        # Serialize simultaneous password changes and update the flag atomically.
        # PasswordChangeView also updates the current session's authentication hash.
        with transaction.atomic():
            user = (
                get_user_model()
                .objects.select_for_update()
                .get(pk=self.request.user.pk)
            )
            if not user.check_password(form.cleaned_data["old_password"]):
                form.add_error(
                    "old_password", "A senha atual está incorreta. Tente novamente."
                )
                return self.form_invalid(form)
            form.user = user
            response = super().form_valid(form)
            ControleSenha.objects.update_or_create(
                usuario=user,
                defaults={"troca_obrigatoria": False, "alterada_em": timezone.now()},
            )
        messages.success(self.request, "Senha alterada com sucesso.")
        return response
