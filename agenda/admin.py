from django.contrib import admin
from django.db.models import F
from .models import Agendamento, Cliente, Disponibilidade, FichaPaciente, FormularioAgendamento, ModeloFormulario, Profissional, RegistroSessao, AlteracaoStatus


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ['nome', 'nutricionista', 'email', 'telefone']
    search_fields = ['nome', 'email']

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related('nutricionista')
        if request.user.is_superuser:
            return queryset
        return queryset.filter(nutricionista=request.user)

    def get_exclude(self, request, obj=None):
        return [] if request.user.is_superuser else ['nutricionista']

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            obj.nutricionista = request.user
        super().save_model(request, obj, form, change)


@admin.register(Agendamento)
class AgendamentoAdmin(admin.ModelAdmin):
    list_display = ['cliente', 'profissional', 'data', 'horario', 'status']
    list_filter = ['status', 'data']
    search_fields = ['cliente__nome']
    date_hierarchy = 'data'

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related('cliente')
        if request.user.is_superuser:
            return queryset
        return queryset.filter(cliente__nutricionista=request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'cliente' and not request.user.is_superuser:
            kwargs['queryset'] = Cliente.objects.filter(nutricionista=request.user)
        elif db_field.name == 'profissional' and not request.user.is_superuser:
            kwargs['queryset'] = Profissional.objects.filter(responsavel=request.user)
        elif db_field.name == 'disponibilidade' and not request.user.is_superuser:
            kwargs['queryset'] = Disponibilidade.objects.filter(formulario__responsavel=request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        return ['cliente', 'disponibilidade', 'profissional', 'data', 'horario', 'status', 'concluido_em', 'cancelado_em', 'motivo_cancelamento'] if obj else ['concluido_em', 'cancelado_em', 'motivo_cancelamento']

    def formfield_for_choice_field(self, db_field, request, **kwargs):
        if db_field.name == 'status':
            kwargs['choices'] = [(value, label) for value, label in Agendamento.Status.choices if value in ('pendente', 'confirmado')]
        return super().formfield_for_choice_field(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change:
            super().save_model(request, obj, form, change)
        # Existing records are controlled by the transactional appointment UI.


class ResponsavelAdmin(admin.ModelAdmin):
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset if request.user.is_superuser else queryset.filter(responsavel=request.user)

    def get_exclude(self, request, obj=None):
        return [] if request.user.is_superuser else ['responsavel']

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            obj.responsavel = request.user
        super().save_model(request, obj, form, change)


@admin.register(Profissional)
class ProfissionalAdmin(ResponsavelAdmin):
    list_display = ['nome', 'crn', 'responsavel', 'ativo']
    search_fields = ['nome', 'crn']


@admin.register(FormularioAgendamento)
class FormularioAdmin(ResponsavelAdmin):
    list_display = ['titulo', 'responsavel', 'ativo']
    readonly_fields = ['token', 'campos_padrao', 'perguntas', 'versao']

    def save_model(self, request, obj, form, change):
        if change:
            # Presentation edits must not overwrite a concurrent schema edit.
            obj.save(update_fields=['titulo', 'descricao', 'ativo', 'responsavel'])
        else:
            super().save_model(request, obj, form, change)



@admin.register(ModeloFormulario)
class ModeloFormularioAdmin(ResponsavelAdmin):
    list_display = ['nome', 'titulo', 'responsavel']
    readonly_fields = ['campos_padrao', 'perguntas', 'versao']

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            obj.responsavel = request.user
        obj.versao = F('versao') + 1
        obj.save(update_fields=['nome', 'titulo', 'descricao', 'responsavel', 'versao'])


    def has_add_permission(self, request):
        return False  # Save complete templates through the questionnaire editor.


@admin.register(Disponibilidade)
class DisponibilidadeAdmin(admin.ModelAdmin):
    list_display = ['formulario', 'profissional', 'data', 'horario', 'ativo']
    list_filter = ['ativo', 'data']

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related('formulario', 'profissional')
        return queryset if request.user.is_superuser else queryset.filter(formulario__responsavel=request.user)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not request.user.is_superuser:
            if db_field.name == 'formulario':
                kwargs['queryset'] = FormularioAgendamento.objects.filter(responsavel=request.user)
            elif db_field.name == 'profissional':
                kwargs['queryset'] = Profissional.objects.filter(responsavel=request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        # For existing slots, scheduling edits use the dedicated locked editor.
        return ['formulario', 'profissional', 'data', 'horario'] if obj else []


@admin.register(FichaPaciente)
class FichaPacienteAdmin(admin.ModelAdmin):
    list_display = ['agendamento', 'idade']
    readonly_fields = ['agendamento', 'respostas']

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.respostas:
            return [field.name for field in FichaPaciente._meta.fields]
        return self.readonly_fields

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related('agendamento__cliente')
        return queryset if request.user.is_superuser else queryset.filter(agendamento__cliente__nutricionista=request.user)


class HistoricoAtendimentoAdmin(admin.ModelAdmin):
    def get_queryset(self, request):
        items = super().get_queryset(request)
        return items if request.user.is_superuser else items.filter(agendamento__cliente__nutricionista=request.user)

    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RegistroSessao)
class RegistroSessaoAdmin(HistoricoAtendimentoAdmin):
    list_display = ['agendamento', 'atualizado_em', 'atualizado_por']


@admin.register(AlteracaoStatus)
class AlteracaoStatusAdmin(HistoricoAtendimentoAdmin):
    list_display = ['agendamento', 'anterior', 'novo', 'realizado_em', 'realizado_por']
