"""Logica de autenticacion: bloqueo por intentos fallidos y registro en la bitacora."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login
from django.db.models import F
from django.utils import timezone

from calificaciones.models import RegistroAuditoria

MENSAJE_CREDENCIALES = 'Usuario o contraseña incorrectos.'


def mensaje_bloqueo():
    return (f'Demasiados intentos fallidos. Espere {settings.LOGIN_BLOQUEO_MINUTOS} minutos '
            'e intente nuevamente.')


def ip_cliente(request):
    """IP de origen. X-Forwarded-For solo se usa si hay un proxy de confianza (Nginx)."""
    if settings.CONFIAR_X_FORWARDED_FOR:
        reenviada = request.META.get('HTTP_X_FORWARDED_FOR', '')
        if reenviada:
            return reenviada.split(',')[-1].strip() or None   # el ultimo salto lo agrega Nginx
    return request.META.get('REMOTE_ADDR') or None


def auditar(request, accion, usuario=None, **detalle):
    RegistroAuditoria.objects.create(
        usuario=usuario, accion=accion, ip=ip_cliente(request), detalle=detalle or None)


CAMPOS_AUDITADOS = ['mercado', 'instrumento', 'ejercicio', 'secuencia_evento', 'numero_dividendo',
                    'dividendo', 'tipo_sociedad', 'isfut', 'fecha_pago', 'valor_historico', 'descripcion']


def _texto(valor):
    if valor is None:
        return None
    if hasattr(valor, 'isoformat'):
        return valor.isoformat()
    if isinstance(valor, bool):
        return valor
    if hasattr(valor, 'quantize'):          # Decimal sin notación científica
        return format(valor, 'f')
    return valor


def instantanea(calificacion, montos=None, factores=None):
    """Foto de una calificación para la bitácora (campos básicos y, si se pasan, montos/factores).

    montos / factores: dict {columna: Decimal}. Solo se guardan los distintos de 0 para no inflar el JSON.
    """
    foto = {campo: _texto(getattr(calificacion, campo)) for campo in CAMPOS_AUDITADOS}
    for prefijo, valores in (('monto', montos), ('factor', factores)):
        for col, valor in sorted((valores or {}).items()):
            foto[f'{prefijo}_{col}'] = _texto(valor)
    return foto


def registrar(request, accion, usuario, calificacion, antes=None, despues=None, **extra):
    """Bitácora de calificaciones: quién, cuándo, desde dónde, de qué corredora y qué cambió.

    - crear:     guarda `despues`.
    - modificar: guarda `antes`/`despues` y `cambios` (solo lo que cambió).
    - eliminar:  guarda `antes`.
    """
    detalle = {
        'corredora_id': calificacion.corredora_id,
        'corredora': calificacion.corredora.nombre,
        'instrumento': calificacion.instrumento,
        'ejercicio': calificacion.ejercicio,
        **extra,
    }
    if antes is not None and despues is not None:
        detalle['cambios'] = {
            clave: {'antes': antes.get(clave), 'despues': despues.get(clave)}
            for clave in sorted(set(antes) | set(despues))
            if antes.get(clave) != despues.get(clave)
        }
    elif antes is not None:
        detalle['antes'] = antes
    elif despues is not None:
        detalle['despues'] = despues
    RegistroAuditoria.objects.create(
        usuario=usuario, accion=accion, id_calificacion=calificacion.id_calificacion,
        ip=ip_cliente(request), detalle=detalle)


def _registrar_fallo(usuario):
    """Suma un intento fallido de forma atomica y bloquea al llegar al maximo."""
    Usuario = get_user_model()
    Usuario.objects.filter(pk=usuario.pk).update(intentos_fallidos=F('intentos_fallidos') + 1)
    usuario.refresh_from_db(fields=['intentos_fallidos'])
    if usuario.intentos_fallidos >= settings.LOGIN_MAX_INTENTOS:
        hasta = timezone.now() + timedelta(minutes=settings.LOGIN_BLOQUEO_MINUTOS)
        Usuario.objects.filter(pk=usuario.pk).update(bloqueado_hasta=hasta, intentos_fallidos=0)
        return True
    return False


def iniciar_sesion(request, username, password):
    """Intenta autenticar. Devuelve (usuario | None, mensaje_de_error | None).

    - Mismo mensaje para usuario inexistente y contrasena incorrecta (no revela cuentas).
    - Cuenta bloqueada: no se evalua la contrasena hasta que pase el plazo.
    - Corredora desactivada: no puede entrar nadie de esa corredora.
    - Todo intento (exitoso o no) queda en la bitacora con IP.
    """
    Usuario = get_user_model()
    username = (username or '').strip()
    candidato = Usuario.objects.select_related('corredora').filter(username=username).first()
    ahora = timezone.now()

    if candidato and candidato.bloqueado_hasta and candidato.bloqueado_hasta > ahora:
        auditar(request, 'login_fallido', candidato, motivo='cuenta_bloqueada')
        return None, mensaje_bloqueo()

    usuario = authenticate(request, username=username, password=password)  # rechaza is_active=False

    if usuario and usuario.corredora_id and not usuario.corredora.activa:
        auditar(request, 'login_fallido', usuario, motivo='corredora_inactiva')
        return None, MENSAJE_CREDENCIALES

    if usuario is None:
        bloqueado_ahora = False
        if candidato:
            bloqueado_ahora = _registrar_fallo(candidato)
        auditar(request, 'login_fallido', candidato,
                usuario_intentado=username[:150], motivo='credenciales' if not bloqueado_ahora else 'bloqueo_aplicado')
        return None, (mensaje_bloqueo() if bloqueado_ahora else MENSAJE_CREDENCIALES)

    Usuario.objects.filter(pk=usuario.pk).update(intentos_fallidos=0, bloqueado_hasta=None)
    login(request, usuario)          # rota la clave de sesion (evita fijacion de sesion)
    auditar(request, 'login', usuario)
    return usuario, None