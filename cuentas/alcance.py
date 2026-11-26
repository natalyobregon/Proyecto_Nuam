"""Aislamiento por corredora (RNF04, caso S01).

REGLA: toda consulta de calificaciones pasa por `calificaciones_visibles(usuario)`.
Nunca usar `Calificacion.objects.all()` ni `.get(pk=...)` directo en una vista.
"""
from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef, Q

from calificaciones.models import Calificacion, Usuario


def calificaciones_visibles(usuario):
    """Calificaciones (no eliminadas) que este usuario puede ver.

    - Administrador de Nuam (sin corredora): todas.
    - Operador: las de su corredora + las oficiales de la Bolsa (solo lectura),
      salvo que su corredora tenga una propia del mismo evento: la del corredor
      prevalece sobre la de la Bolsa (HDU) y la de la Bolsa se oculta para él.
    - Cualquier otro caso (operador sin corredora, usuario inactivo): ninguna.
    """
    base = Calificacion.objects.filter(eliminado=False)
    if not getattr(usuario, 'is_authenticated', False) or not usuario.is_active:
        return base.none()
    if usuario.rol == Usuario.ROL_ADMIN and usuario.corredora_id is None:
        return base
    if usuario.corredora_id is None:
        return base.none()
    propias = base.filter(corredora_id=usuario.corredora_id)
    pisadas = propias.filter(
        mercado=OuterRef('mercado'), instrumento=OuterRef('instrumento'),
        ejercicio=OuterRef('ejercicio'), secuencia_evento=OuterRef('secuencia_evento'))
    bolsa = base.filter(corredora__es_bolsa=True).exclude(Exists(pisadas))
    return base.filter(Q(corredora_id=usuario.corredora_id) | Q(pk__in=bolsa.values('pk')))


def es_editable_por(usuario, calificacion):
    """Solo se modifica/elimina lo de la propia corredora; lo de la Bolsa es solo lectura."""
    return (usuario.corredora_id is not None
            and calificacion.corredora_id == usuario.corredora_id
            and not calificacion.corredora.es_bolsa)


def obtener_calificacion(usuario, pk):
    """Devuelve la calificacion o lanza PermissionDenied («Acceso denegado»).

    Se responde igual si el ID no existe o es de otra corredora, para no revelar
    que registros existen en otras corredoras (S01).
    """
    try:
        return calificaciones_visibles(usuario).get(pk=pk)
    except Calificacion.DoesNotExist:
        raise PermissionDenied