from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (Calificacion, CargaMasiva, Corredora, FactorCalificacion,
                     MontoCalificacion, RegistroAuditoria, Usuario)


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Nuam', {'fields': ('corredora', 'rol', 'intentos_fallidos', 'bloqueado_hasta')}),)
    list_display = ('username', 'email', 'rol', 'corredora', 'is_active')


class MontoInline(admin.TabularInline):
    model = MontoCalificacion
    extra = 0


class FactorInline(admin.TabularInline):
    model = FactorCalificacion
    extra = 0


@admin.register(Calificacion)
class CalificacionAdmin(admin.ModelAdmin):
    list_display = ('id_calificacion', 'corredora', 'mercado', 'instrumento', 'ejercicio',
                    'secuencia_evento', 'origen', 'eliminado')
    list_filter = ('origen', 'ejercicio', 'eliminado', 'corredora')
    inlines = [MontoInline, FactorInline]


@admin.register(RegistroAuditoria)
class AuditoriaAdmin(admin.ModelAdmin):
    list_display = ('id_registro', 'fecha', 'usuario', 'accion', 'id_calificacion')

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(Corredora)
admin.site.register(CargaMasiva)