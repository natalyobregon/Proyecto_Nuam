"""URL configuration for nuam project."""
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import include, path
from django.utils.http import urlencode

from cuentas import views as cuentas_views

handler403 = 'cuentas.views.acceso_denegado'


def admin_login_unico(request):
    """El panel /admin/ usa el mismo login del sistema (con bloqueo y bitacora).

    Quien ya inicio sesion pero no es personal del panel recibe «Acceso denegado» (S02).
    """
    if request.user.is_authenticated:
        raise PermissionDenied
    destino = request.GET.get('next', '/admin/')
    return redirect(f"/?{urlencode({'next': destino})}")


urlpatterns = [
    path('admin/login/', admin_login_unico),
    path('admin/', admin.site.urls),
    path('calificaciones/', cuentas_views.grilla, name='grilla'),   # provisoria: la reemplaza la grilla real
    path('', include('cuentas.urls')),
]
