from datetime import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from agenda.models import Agendamento, Cliente


class Command(BaseCommand):
    help = 'Adiciona clientes fictícios e consultas no mês atual para um usuário existente.'

    def add_arguments(self, parser):
        parser.add_argument('--usuario', required=True, help='Nome de usuário do nutricionista.')

    @transaction.atomic
    def handle(self, *args, **options):
        try:
            user = get_user_model().objects.get(username=options['usuario'])
        except get_user_model().DoesNotExist as error:
            raise CommandError('Usuário não encontrado. Execute createsuperuser primeiro.') from error

        clientes = []
        for nome, email in [
            ('Ana Silva (demo)', 'ana@example.com'),
            ('Lucas Martins (demo)', 'lucas@example.com'),
            ('Mariana Costa (demo)', 'mariana@example.com'),
            ('Pedro Santos (demo)', 'pedro@example.com'),
        ]:
            cliente, _ = Cliente.objects.get_or_create(
                nutricionista=user, nome=nome, email=email,
            )
            clientes.append(cliente)

        mes = timezone.localdate().replace(day=1)
        criados = 0
        for dia, hora, indice, status in [
            (3, 9, 0, 'confirmado'), (3, 14, 1, 'confirmado'),
            (7, 8, 2, 'confirmado'), (7, 10, 0, 'pendente'),
            (7, 15, 3, 'confirmado'), (12, 9, 1, 'confirmado'),
            (16, 11, 2, 'pendente'), (22, 14, 0, 'confirmado'),
            (22, 16, 3, 'cancelado'), (28, 10, 1, 'confirmado'),
        ]:
            _, criado = Agendamento.objects.get_or_create(
                cliente=clientes[indice], data=mes.replace(day=dia), horario=time(hora),
                defaults={'status': status},
            )
            criados += criado
        self.stdout.write(self.style.SUCCESS(f'{criados} agendamentos fictícios criados para {user.username}.'))
