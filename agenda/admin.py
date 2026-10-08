from django.contrib import admin
from .models import Agendamento, Cliente


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
    list_display = ['cliente', 'data', 'horario', 'status']
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
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
