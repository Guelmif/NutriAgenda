import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils import timezone


class Profissional(models.Model):
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profissionais')
    nome = models.CharField('nome do nutricionista', max_length=150)
    crn = models.CharField('CRN', max_length=30, blank=True)
    ativo = models.BooleanField('ativo', default=True)

    class Meta:
        ordering = ['nome', 'pk']
        verbose_name = 'nutricionista'
        verbose_name_plural = 'nutricionistas'

    def __str__(self):
        return self.nome


class FormularioAgendamento(models.Model):
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='formularios')
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    titulo = models.CharField('título', max_length=150, default='Agendamento nutricional')
    descricao = models.TextField('mensagem de apresentação', max_length=2000, blank=True)
    ativo = models.BooleanField('disponível para pacientes', default=True)

    class Meta:
        ordering = ['-pk']
        verbose_name = 'formulário de agendamento'
        verbose_name_plural = 'formulários de agendamento'

    def __str__(self):
        return self.titulo


class DisponibilidadeQuerySet(models.QuerySet):
    def livres(self):
        agora = timezone.localtime()
        ocupados = Agendamento.objects.filter(
            profissional_id=models.OuterRef('profissional_id'),
            data=models.OuterRef('data'), horario=models.OuterRef('horario'),
        ).exclude(status='cancelado')
        return self.filter(
            models.Q(data__gt=agora.date()) |
            models.Q(data=agora.date(), horario__gt=agora.time().replace(tzinfo=None)),
            ativo=True, profissional__ativo=True, formulario__ativo=True,
            profissional__responsavel=models.F('formulario__responsavel'),
        ).annotate(ocupado=models.Exists(ocupados)).filter(ocupado=False)


class Disponibilidade(models.Model):
    formulario = models.ForeignKey(FormularioAgendamento, on_delete=models.CASCADE, related_name='disponibilidades')
    profissional = models.ForeignKey(Profissional, on_delete=models.PROTECT, related_name='disponibilidades', verbose_name='nutricionista')
    data = models.DateField('data')
    horario = models.TimeField('horário')
    ativo = models.BooleanField('oferecer este horário', default=True)
    objects = DisponibilidadeQuerySet.as_manager()

    class Meta:
        ordering = ['data', 'horario', 'profissional__nome', 'pk']
        verbose_name = 'horário disponível'
        verbose_name_plural = 'horários disponíveis'
        constraints = [models.UniqueConstraint(
            fields=['profissional', 'data', 'horario'], name='unique_professional_availability',
            violation_error_message='Este nutricionista já tem esse horário cadastrado em um formulário.',
        )]

    def clean(self):
        if self.formulario_id and self.profissional_id:
            if self.formulario.responsavel_id != self.profissional.responsavel_id:
                raise ValidationError({'profissional': 'Selecione um nutricionista da mesma conta.'})
        if self.pk and self.agendamentos.exists():
            original = type(self).objects.get(pk=self.pk)
            if any(getattr(self, field) != getattr(original, field) for field in (
                'formulario_id', 'profissional_id', 'data', 'horario',
            )):
                raise ValidationError('Um horário com histórico de reservas não pode mudar de data, horário ou nutricionista. Desative-o e crie outro.')

    def __str__(self):
        return f'{self.profissional} — {self.data:%d/%m/%Y} às {self.horario:%H:%M}'


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
    profissional = models.ForeignKey(Profissional, on_delete=models.PROTECT, null=True, blank=True, related_name='agendamentos', verbose_name='nutricionista da consulta')
    disponibilidade = models.ForeignKey(Disponibilidade, on_delete=models.PROTECT, null=True, blank=True, related_name='agendamentos')
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
        constraints = [models.UniqueConstraint(
            fields=['profissional', 'data', 'horario'],
            condition=models.Q(profissional__isnull=False) & ~models.Q(status='cancelado'),
            name='unique_active_professional_booking',
            violation_error_message='Este nutricionista já possui um agendamento nesse horário.',
        )]

    def clean(self):
        if self.profissional_id and self.cliente_id:
            if self.profissional.responsavel_id != self.cliente.nutricionista_id:
                raise ValidationError({'profissional': 'Selecione um nutricionista da mesma conta do cliente.'})
        if self.disponibilidade_id:
            slot = self.disponibilidade
            if (self.profissional_id, self.data, self.horario) != (slot.profissional_id, slot.data, slot.horario):
                raise ValidationError('A consulta deve corresponder ao nutricionista, data e horário da disponibilidade.')
            if self.cliente_id and slot.formulario.responsavel_id != self.cliente.nutricionista_id:
                raise ValidationError('A disponibilidade deve pertencer à mesma conta do cliente.')

    def __str__(self):
        return f'{self.cliente} — {self.data:%d/%m/%Y} às {self.horario:%H:%M}'


class FichaPaciente(models.Model):
    agendamento = models.OneToOneField(Agendamento, on_delete=models.CASCADE, related_name='ficha')
    idade = models.PositiveSmallIntegerField('idade', validators=[MaxValueValidator(120)])
    contato = models.CharField('contato', max_length=120)
    tem_problemas_saude = models.BooleanField('tem problemas de saúde')
    problemas_saude = models.TextField('quais problemas de saúde', max_length=2000, blank=True)
    usa_medicacoes = models.BooleanField('usa medicações')
    medicacoes = models.TextField('quais medicações', max_length=2000, blank=True)
    ultimos_exames = models.CharField('última vez que fez exames', max_length=200, blank=True)
    motivo_consulta = models.TextField('motivo da consulta', max_length=2000)
    observacoes = models.TextField('observações', max_length=2000, blank=True)

    class Meta:
        verbose_name = 'ficha do paciente'
        verbose_name_plural = 'fichas dos pacientes'

    def __str__(self):
        return str(self.agendamento)
