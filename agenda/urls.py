from django.urls import path
from . import views

app_name = 'agenda'
urlpatterns = [
    path('', views.calendario, name='calendario'),
    path('api/agendamentos/', views.agendamentos_do_dia, name='agendamentos_do_dia'),
]
