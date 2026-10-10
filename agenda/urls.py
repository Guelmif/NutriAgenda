from django.urls import path
from . import atendimento_views, formulario_views, pwa_views, views

app_name = "agenda"
urlpatterns = [
    path("manifest.webmanifest", pwa_views.manifest, name="manifest"),
    path("service-worker.js", pwa_views.service_worker, name="service_worker"),
    path("", views.calendario, name="calendario"),
    path("api/agendamentos/", views.agendamentos_do_dia, name="agendamentos_do_dia"),
    path("formularios/", formulario_views.formularios, name="formularios"),
    path(
        "formularios/novo/", formulario_views.criar_formulario, name="criar_formulario"
    ),
    path(
        "formularios/<uuid:token>/editar/",
        formulario_views.editar_formulario,
        name="editar_formulario",
    ),
    path(
        "formularios/<uuid:token>/perguntas/",
        formulario_views.editar_perguntas,
        name="editar_perguntas",
    ),
    path(
        "formularios/<uuid:token>/salvar-modelo/",
        formulario_views.salvar_modelo,
        name="salvar_modelo",
    ),
    path(
        "modelos/<int:pk>/editar/",
        formulario_views.editar_perguntas,
        name="editar_modelo",
    ),
    path(
        "nutricionistas/<int:pk>/editar/",
        formulario_views.editar_profissional,
        name="editar_profissional",
    ),
    path(
        "disponibilidades/<int:pk>/editar/",
        formulario_views.editar_disponibilidade,
        name="editar_disponibilidade",
    ),
    path(
        "disponibilidades/<int:pk>/situacao/",
        formulario_views.alterar_disponibilidade,
        name="alterar_disponibilidade",
    ),
    path(
        "agendar/<uuid:token>/",
        formulario_views.formulario_publico,
        name="formulario_publico",
    ),
    path(
        "agendar/<uuid:token>/disponibilidades/",
        formulario_views.disponibilidades_publicas,
        name="disponibilidades_publicas",
    ),
    path(
        "agendar/<uuid:token>/concluido/",
        formulario_views.formulario_sucesso,
        name="formulario_sucesso",
    ),
    path(
        "agendamentos/<int:pk>/",
        atendimento_views.detalhes_agendamento,
        name="detalhes_agendamento",
    ),
    path("atendimentos/", atendimento_views.atendimentos, name="atendimentos"),
    path(
        "agendamentos/<int:pk>/situacao/<str:acao>/",
        atendimento_views.situacao_agendamento,
        name="situacao_agendamento",
    ),
    path(
        "agendamentos/<int:pk>/vincular/",
        atendimento_views.vincular_agendamento,
        name="vincular_agendamento",
    ),
    path("clientes/", atendimento_views.clientes, name="clientes"),
    path("clientes/novo/", atendimento_views.editar_cliente, name="criar_cliente"),
    path(
        "clientes/<int:pk>/",
        atendimento_views.detalhes_cliente,
        name="detalhes_cliente",
    ),
    path(
        "clientes/<int:pk>/editar/",
        atendimento_views.editar_cliente,
        name="editar_cliente",
    ),
    path("equipe/", atendimento_views.equipe, name="equipe"),
    path(
        "equipe/<int:pk>/acesso/",
        atendimento_views.alterar_membro,
        name="alterar_membro",
    ),
]
