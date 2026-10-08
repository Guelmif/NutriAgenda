from django.conf import settings
from django.db import models


class Cliente(models.Model):
    nutricionista = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='clientes', verbose_name='nutricionista',
    )
    nome = models.CharField('nome', max_length=150)
    email = models.EmailField('e-mail', blank=True)
    telefone = models.CharField('telefone', max_length=25, blank=True)

    class Meta:
        ordering = ['nome', 'pk']
        verbose_name = 'cliente'
        verbose_name_plural = 'clientes'

    def __str__(self):
        return self.nome


class Agendamento(models.Model):
    class Status(models.TextChoices):
        CONFIRMADO = 'confirmado', 'Confirmado'
        PENDENTE = 'pendente', 'Pendente'
        CANCELADO = 'cancelado', 'Cancelado'

    cliente = models.ForeignKey(
        Cliente, on_delete=models.PROTECT, related_name='agendamentos',
        verbose_name='cliente',
    )
    data = models.DateField('data')
    horario = models.TimeField('horário')
    status = models.CharField(
        'status', max_length=12, choices=Status.choices, default=Status.CONFIRMADO,
    )

    class Meta:
        ordering = ['data', 'horario', 'pk']
        verbose_name = 'agendamento'
        verbose_name_plural = 'agendamentos'
        indexes = [models.Index(fields=['data', 'horario'])]

    def __str__(self):
        return f'{self.cliente} — {self.data:%d/%m/%Y} às {self.horario:%H:%M}'
