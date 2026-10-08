from django.urls import path
from . import formulario_views, views

app_name = 'agenda'
urlpatterns = [
    path('', views.calendario, name='calendario'),
    path('api/agendamentos/', views.agendamentos_do_dia, name='agendamentos_do_dia'),
    path('formularios/', formulario_views.formularios, name='formularios'),
    path('formularios/novo/', formulario_views.criar_formulario, name='criar_formulario'),
    path('formularios/<uuid:token>/editar/', formulario_views.editar_formulario, name='editar_formulario'),
    path('nutricionistas/<int:pk>/editar/', formulario_views.editar_profissional, name='editar_profissional'),
    path('disponibilidades/<int:pk>/editar/', formulario_views.editar_disponibilidade, name='editar_disponibilidade'),
    path('disponibilidades/<int:pk>/situacao/', formulario_views.alterar_disponibilidade, name='alterar_disponibilidade'),
    path('agendar/<uuid:token>/', formulario_views.formulario_publico, name='formulario_publico'),
    path('agendar/<uuid:token>/disponibilidades/', formulario_views.disponibilidades_publicas, name='disponibilidades_publicas'),
    path('agendar/<uuid:token>/concluido/', formulario_views.formulario_sucesso, name='formulario_sucesso'),
    path('agendamentos/<int:pk>/', formulario_views.detalhes_agendamento, name='detalhes_agendamento'),
]
