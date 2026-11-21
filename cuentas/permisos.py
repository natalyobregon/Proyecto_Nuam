"""Permisos por rol (informe, 5.4 «Permisos por funcionalidad»).

Principio de minimo privilegio: lo que no esta en la lista del rol, esta prohibido.
La verificacion se hace SIEMPRE en el servidor; ocultar un boton en la interfaz no basta.

Uso en una vista:

    from cuentas.permisos import permiso_requerido, PermisoRequeridoMixin

    @permiso_requerido('eliminar_calificacion')
    def eliminar(request, pk): ...

    class IngresarView(PermisoRequeridoMixin, View):
        permiso = 'ingresar_calificacion'
"""
from functools import wraps

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from calificaciones.models import RegistroAuditoria, Usuario

CONSULTAR = 'consultar_calificaciones'
INGRESAR = 'ingresar_calificacion'
EDITAR_FACTORES = 'editar_factores'
MODIFICAR = 'modificar_calificacion'
ELIMINAR = 'eliminar_calificacion'
CARGA_MASIVA = 'carga_masiva'
BITACORA = 'consultar_bitacora'
ADMINISTRAR_USUARIOS = 'administrar_usuarios'

PERMISOS_POR_ROL = {
    Usuario.ROL_OPERADOR: frozenset({CONSULTAR, INGRESAR, EDITAR_FACTORES, CARGA_MASIVA}),
    Usuario.ROL_ADMIN: frozenset({CONSULTAR, MODIFICAR, ELIMINAR, BITACORA, ADMINISTRAR_USUARIOS}),
}


def tiene_permiso(usuario, permiso):
    if not getattr(usuario, 'is_authenticated', False) or not usuario.is_active:
        return False
    return permiso in PERMISOS_POR_ROL.get(usuario.rol, frozenset())


def registrar_denegado(request, permiso):
    """Deja constancia del intento de acceso indebido (el informe pide registrarlos)."""
    from cuentas.servicios import ip_cliente
    RegistroAuditoria.objects.create(
        usuario=request.user if request.user.is_authenticated else None,
        accion='otro',
        ip=ip_cliente(request),
        detalle={'evento': 'acceso_denegado', 'permiso': permiso, 'ruta': request.path[:200]},
    )


def permiso_requerido(permiso):
    """Decorador para vistas de funcion. Sin sesion -> login; sin permiso -> «Acceso denegado» (403)."""
    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not tiene_permiso(request.user, permiso):
                registrar_denegado(request, permiso)
                raise PermissionDenied
            return vista(request, *args, **kwargs)
        return envoltura
    return decorador


class PermisoRequeridoMixin(LoginRequiredMixin):
    """Equivalente para vistas basadas en clases: definir `permiso = '...'`."""
    permiso = None

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not tiene_permiso(request.user, self.permiso):
            registrar_denegado(request, self.permiso)
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
