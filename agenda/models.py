import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils import timezone


class Profissional(models.Model):
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profissionais"
    )
    nome = models.CharField("nome do nutricionista", max_length=150)
    crn = models.CharField("CRN", max_length=30, blank=True)
    ativo = models.BooleanField("ativo", default=True)

    class Meta:
        ordering = ["nome", "pk"]
        verbose_name = "nutricionista"
        verbose_name_plural = "nutricionistas"

    def __str__(self):
        return self.nome


class FormularioAgendamento(models.Model):
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="formularios"
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    titulo = models.CharField(
        "título", max_length=150, default="Agendamento nutricional"
    )
    descricao = models.TextField(
        "mensagem de apresentação", max_length=2000, blank=True
    )
    ativo = models.BooleanField("disponível para pacientes", default=True)
    campos_padrao = models.JSONField(default=dict, blank=True)
    perguntas = models.JSONField(default=list, blank=True)
    versao = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-pk"]
        verbose_name = "formulário de agendamento"
        verbose_name_plural = "formulários de agendamento"

    def __str__(self):
        return self.titulo


class ModeloFormulario(models.Model):
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="modelos_formulario",
    )
    nome = models.CharField("nome do modelo", max_length=150)
    titulo = models.CharField("título do formulário", max_length=150)
    descricao = models.TextField(
        "mensagem de apresentação", max_length=2000, blank=True
    )
    campos_padrao = models.JSONField(default=dict, blank=True)
    perguntas = models.JSONField(default=list, blank=True)
    versao = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["nome", "pk"]
        verbose_name = "modelo de formulário"
        verbose_name_plural = "modelos de formulário"

    def __str__(self):
        return self.nome


class DisponibilidadeQuerySet(models.QuerySet):
    def livres(self):
        agora = timezone.localtime()
        ocupados = Agendamento.objects.filter(
            profissional_id=models.OuterRef("profissional_id"),
            data=models.OuterRef("data"),
            horario=models.OuterRef("horario"),
        ).exclude(status="cancelado")
        return (
            self.filter(
                models.Q(data__gt=agora.date())
                | models.Q(
                    data=agora.date(), horario__gt=agora.time().replace(tzinfo=None)
                ),
                ativo=True,
                profissional__ativo=True,
                formulario__ativo=True,
                profissional__responsavel=models.F("formulario__responsavel"),
            )
            .annotate(ocupado=models.Exists(ocupados))
            .filter(ocupado=False)
        )


class Disponibilidade(models.Model):
    formulario = models.ForeignKey(
        FormularioAgendamento, on_delete=models.CASCADE, related_name="disponibilidades"
    )
    profissional = models.ForeignKey(
        Profissional,
        on_delete=models.PROTECT,
        related_name="disponibilidades",
        verbose_name="nutricionista",
    )
    data = models.DateField("data")
    horario = models.TimeField("horário")
    ativo = models.BooleanField("oferecer este horário", default=True)
    objects = DisponibilidadeQuerySet.as_manager()

    class Meta:
        ordering = ["data", "horario", "profissional__nome", "pk"]
        verbose_name = "horário disponível"
        verbose_name_plural = "horários disponíveis"
        constraints = [
            models.UniqueConstraint(
                fields=["profissional", "data", "horario"],
                name="unique_professional_availability",
                violation_error_message="Este nutricionista já tem esse horário cadastrado em um formulário.",
            )
        ]

    def clean(self):
        if self.formulario_id and self.profissional_id:
            if self.formulario.responsavel_id != self.profissional.responsavel_id:
                raise ValidationError(
                    {"profissional": "Selecione um nutricionista da mesma conta."}
                )
        if self.pk and self.agendamentos.exists():
            original = type(self).objects.get(pk=self.pk)
            if any(
                getattr(self, field) != getattr(original, field)
                for field in (
                    "formulario_id",
                    "profissional_id",
                    "data",
                    "horario",
                )
            ):
                raise ValidationError(
                    "Um horário com histórico de reservas não pode mudar de data, horário ou nutricionista. Desative-o e crie outro."
                )

    def __str__(self):
        return f"{self.profissional} — {self.data:%d/%m/%Y} às {self.horario:%H:%M}"


class Cliente(models.Model):
    nutricionista = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="clientes",
        verbose_name="nutricionista",
    )
    nome = models.CharField("nome", max_length=150)
    email = models.EmailField("e-mail", blank=True)
    telefone = models.CharField("telefone", max_length=25, blank=True)

    class Meta:
        ordering = ["nome", "pk"]
        verbose_name = "cliente"
        verbose_name_plural = "clientes"

    def __str__(self):
        return self.nome


class Agendamento(models.Model):
    class Status(models.TextChoices):
        CONFIRMADO = "confirmado", "Confirmado"
        PENDENTE = "pendente", "Pendente"
        CANCELADO = "cancelado", "Cancelado"
        CONCLUIDO = "concluido", "Concluído"

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        related_name="agendamentos",
        verbose_name="cliente",
    )
    profissional = models.ForeignKey(
        Profissional,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="agendamentos",
        verbose_name="nutricionista da consulta",
    )
    disponibilidade = models.ForeignKey(
        Disponibilidade,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="agendamentos",
    )
    data = models.DateField("data")
    horario = models.TimeField("horário")
    status = models.CharField(
        "status",
        max_length=12,
        choices=Status.choices,
        default=Status.CONFIRMADO,
    )

    concluido_em = models.DateTimeField("concluído em", null=True, blank=True)
    cancelado_em = models.DateTimeField("cancelado em", null=True, blank=True)
    motivo_cancelamento = models.TextField(
        "motivo do cancelamento", max_length=2000, blank=True
    )

    class Meta:
        ordering = ["data", "horario", "pk"]
        verbose_name = "agendamento"
        verbose_name_plural = "agendamentos"
        indexes = [models.Index(fields=["data", "horario"])]
        constraints = [
            models.UniqueConstraint(
                fields=["profissional", "data", "horario"],
                condition=models.Q(profissional__isnull=False)
                & ~models.Q(status="cancelado"),
                name="unique_active_professional_booking",
                violation_error_message="Este nutricionista já possui um agendamento nesse horário.",
            )
        ]

    def clean(self):
        if self.profissional_id and self.cliente_id:
            if self.profissional.responsavel_id != self.cliente.nutricionista_id:
                raise ValidationError(
                    {
                        "profissional": "Selecione um nutricionista da mesma conta do cliente."
                    }
                )
        if self.disponibilidade_id:
            slot = self.disponibilidade
            if (self.profissional_id, self.data, self.horario) != (
                slot.profissional_id,
                slot.data,
                slot.horario,
            ):
                raise ValidationError(
                    "A consulta deve corresponder ao nutricionista, data e horário da disponibilidade."
                )
            if (
                self.cliente_id
                and slot.formulario.responsavel_id != self.cliente.nutricionista_id
            ):
                raise ValidationError(
                    "A disponibilidade deve pertencer à mesma conta do cliente."
                )

    def __str__(self):
        return f"{self.cliente} — {self.data:%d/%m/%Y} às {self.horario:%H:%M}"


class FichaPaciente(models.Model):
    agendamento = models.OneToOneField(
        Agendamento, on_delete=models.CASCADE, related_name="ficha"
    )
    idade = models.PositiveSmallIntegerField(
        "idade", validators=[MaxValueValidator(120)], null=True, blank=True
    )
    contato = models.CharField("contato", max_length=120)
    tem_problemas_saude = models.BooleanField(
        "tem problemas de saúde", null=True, blank=True
    )
    problemas_saude = models.TextField(
        "quais problemas de saúde", max_length=2000, blank=True
    )
    usa_medicacoes = models.BooleanField("usa medicações", null=True, blank=True)
    medicacoes = models.TextField("quais medicações", max_length=2000, blank=True)
    ultimos_exames = models.CharField(
        "última vez que fez exames", max_length=200, blank=True
    )
    motivo_consulta = models.TextField(
        "motivo da consulta", max_length=2000, blank=True
    )
    observacoes = models.TextField("observações", max_length=2000, blank=True)

    respostas = models.JSONField(
        "perguntas e respostas recebidas", default=list, blank=True
    )

    class Meta:
        verbose_name = "ficha do paciente"
        verbose_name_plural = "fichas dos pacientes"

    def __str__(self):
        return str(self.agendamento)


class RegistroSessao(models.Model):
    agendamento = models.OneToOneField(
        Agendamento, on_delete=models.CASCADE, related_name="sessao"
    )
    observacoes = models.TextField(
        "observações da sessão", max_length=10000, blank=True
    )
    plano_alimentar = models.TextField("plano alimentar", max_length=10000, blank=True)
    orientacoes = models.TextField(
        "orientações e próximos passos", max_length=10000, blank=True
    )
    atualizado_em = models.DateTimeField(auto_now=True)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sessoes_editadas",
    )
    versao = models.PositiveIntegerField(default=1)

    class Meta:
        verbose_name = "registro da sessão"
        verbose_name_plural = "registros das sessões"

    def __str__(self):
        return str(self.agendamento)


class AlteracaoStatus(models.Model):
    agendamento = models.ForeignKey(
        Agendamento, on_delete=models.CASCADE, related_name="alteracoes_status"
    )
    anterior = models.CharField(max_length=12, choices=Agendamento.Status.choices)
    novo = models.CharField(max_length=12, choices=Agendamento.Status.choices)
    motivo = models.TextField(max_length=2000, blank=True)
    realizado_em = models.DateTimeField(auto_now_add=True)
    realizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="alteracoes_consultas",
    )

    class Meta:
        ordering = ["-realizado_em", "-pk"]
        verbose_name = "alteração de consulta"
        verbose_name_plural = "alterações de consultas"


class MembroEquipe(models.Model):
    responsavel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="membros_equipe",
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="equipes_compartilhadas",
    )
    ativo = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["responsavel", "usuario"], name="unique_team_member"
            )
        ]
        ordering = ["usuario__username"]
        verbose_name = "membro da equipe"
        verbose_name_plural = "membros da equipe"

    def clean(self):
        if self.responsavel_id == self.usuario_id:
            raise ValidationError("A conta responsável já tem acesso à própria equipe.")


class RevisaoSessao(models.Model):
    sessao = models.ForeignKey(
        RegistroSessao, on_delete=models.CASCADE, related_name="revisoes"
    )
    versao = models.PositiveIntegerField()
    observacoes = models.TextField(max_length=10000, blank=True)
    plano_alimentar = models.TextField(max_length=10000, blank=True)
    orientacoes = models.TextField(max_length=10000, blank=True)
    autor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="revisoes_sessoes",
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-versao"]
        constraints = [
            models.UniqueConstraint(
                fields=["sessao", "versao"], name="unique_session_revision"
            )
        ]
        verbose_name = "versão do registro da sessão"
        verbose_name_plural = "versões dos registros das sessões"
