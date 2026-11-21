"""Aislamiento por corredora (RNF04, caso S01).

REGLA: toda consulta de calificaciones pasa por `calificaciones_visibles(usuario)`.
Nunca usar `Calificacion.objects.all()` ni `.get(pk=...)` directo en una vista.
"""
from django.core.exceptions import PermissionDenied

from calificaciones.models import Calificacion, Usuario


def calificaciones_visibles(usuario):
    """Calificaciones (no eliminadas) que este usuario puede ver.

    - Operador: solo las de su corredora.
    - Administrador de Nuam (sin corredora): todas.
    - Cualquier otro caso (operador sin corredora, usuario inactivo): ninguna.
    """
    base = Calificacion.objects.filter(eliminado=False)
    if not getattr(usuario, 'is_authenticated', False) or not usuario.is_active:
        return base.none()
    if usuario.rol == Usuario.ROL_ADMIN and usuario.corredora_id is None:
        return base
    if usuario.corredora_id is None:
        return base.none()
    return base.filter(corredora_id=usuario.corredora_id)


def obtener_calificacion(usuario, pk):
    """Devuelve la calificacion o lanza PermissionDenied («Acceso denegado»).

    Se responde igual si el ID no existe o es de otra corredora, para no revelar
    que registros existen en otras corredoras (S01).
    """
    try:
        return calificaciones_visibles(usuario).get(pk=pk)
    except Calificacion.DoesNotExist:
        raise PermissionDenied
