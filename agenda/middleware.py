from urllib.parse import urlencode

from django.shortcuts import redirect
from django.urls import reverse
from django.utils.cache import add_never_cache_headers
from django.utils.deprecation import MiddlewareMixin

from .models import ControleSenha


class TrocaSenhaObrigatoriaMiddleware(MiddlewareMixin):
    allowed_views = {
        "password_change",
        "logout",
        "admin:logout",
        "agenda:manifest",
        "agenda:service_worker",
        # Patient booking forms remain public, including on shared devices.
        "agenda:formulario_publico",
        "agenda:disponibilidades_publicas",
        "agenda:formulario_sucesso",
    }

    def process_view(self, request, view_func, view_args, view_kwargs):
        request.troca_senha_obrigatoria = (
            request.user.is_authenticated
            and ControleSenha.objects.filter(
                usuario=request.user, troca_obrigatoria=True
            ).exists()
        )
        if not request.troca_senha_obrigatoria:
            return None
        match = request.resolver_match
        if match and match.view_name in self.allowed_views:
            return None
        # Never replay a blocked POST or send its data to another endpoint.
        destination = (
            request.get_full_path()
            if request.method in {"GET", "HEAD"}
            else reverse("agenda:calendario")
        )
        response = redirect(
            f"{reverse('password_change')}?{urlencode({'next': destination})}"
        )
        add_never_cache_headers(response)
        return response
