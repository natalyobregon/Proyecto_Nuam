"""Pantalla de Bitácora (solo lectura) para el administrador de Nuam (permiso BITACORA).

Muestra quién hizo qué, cuándo, desde qué IP, en qué corredora y qué cambió (antes/después).
La bitácora es append-only: aquí solo se consulta; no hay formularios de edición ni borrado.
"""
from datetime import date

from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.utils.http import urlencode
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from cuentas.permisos import BITACORA, permiso_requerido

from .models import Corredora, RegistroAuditoria

POR_PAGINA = 25
ETIQUETAS_CAMPOS = {
    'mercado': 'Mercado', 'instrumento': 'Instrumento', 'ejercicio': 'Ejercicio',
    'secuencia_evento': 'Secuencia', 'numero_dividendo': 'N.° dividendo', 'dividendo': 'Dividendo',
    'tipo_sociedad': 'Tipo de sociedad', 'isfut': 'ISFUT', 'fecha_pago': 'Fecha de pago',
    'valor_historico': 'Valor histórico', 'descripcion': 'Descripción',
}
CLAVES_GENERALES = ('corredora', 'corredora_id', 'instrumento', 'ejercicio')


def _fecha(texto):
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


def etiqueta_campo(clave):
    if clave in ETIQUETAS_CAMPOS:
        return ETIQUETAS_CAMPOS[clave]
    for prefijo, nombre in (('monto_', 'Monto columna '), ('factor_', 'Factor columna ')):
        if clave.startswith(prefijo):
            return nombre + clave[len(prefijo):]
    return clave


def resumen(registro):
    """Texto corto para la lista: qué pasó en una línea."""
    d = registro.detalle if isinstance(registro.detalle, dict) else {}
    if 'cambios' in d:
        n = len(d['cambios'])
        return f'{n} campo{"s" if n != 1 else ""} modificado{"s" if n != 1 else ""}'
    if registro.accion == 'carga' and 'creadas' in d:
        omitidas = d.get('filas_omitidas_por_error', 0)
        extra = f', {omitidas} omitidas por error' if omitidas else ''
        return f'{d["creadas"]} creadas, {d["actualizadas"]} actualizadas{extra}'
    if registro.accion == 'carga' and 'operacion' in d:
        return f'Carga masiva ({d["operacion"]})'
    if registro.accion == 'crear':
        return 'Calificación creada'
    if registro.accion == 'eliminar':
        return 'Eliminación lógica'
    return d.get('evento') or d.get('motivo') or ''


@never_cache
@require_GET
@permiso_requerido(BITACORA)
def bitacora(request):
    f = {k: (request.GET.get(k) or '').strip()[:60] for k in ('usuario', 'accion', 'corredora', 'desde', 'hasta')}
    consulta = RegistroAuditoria.objects.select_related('usuario').order_by('-fecha', '-id_registro')

    if f['usuario']:
        consulta = consulta.filter(usuario__username__icontains=f['usuario'])
    if f['accion'] in dict(RegistroAuditoria.ACCIONES):
        consulta = consulta.filter(accion=f['accion'])
    else:
        f['accion'] = ''
    if f['corredora'].isdigit():
        consulta = consulta.filter(detalle__corredora_id=int(f['corredora']))
    else:
        f['corredora'] = ''
    desde, hasta = _fecha(f['desde']), _fecha(f['hasta'])
    if desde:
        consulta = consulta.filter(fecha__date__gte=desde)
    else:
        f['desde'] = ''
    if hasta:
        consulta = consulta.filter(fecha__date__lte=hasta)
    else:
        f['hasta'] = ''

    pagina = Paginator(consulta, POR_PAGINA).get_page(request.GET.get('page'))
    filas = []
    for r in pagina.object_list:
        d = r.detalle if isinstance(r.detalle, dict) else {}
        filas.append({'obj': r, 'corredora': d.get('corredora', ''), 'instrumento': d.get('instrumento', ''),
                      'resumen': resumen(r)})
    activos = {k: v for k, v in f.items() if v}
    return render(request, 'calificaciones/bitacora.html', {
        'filas': filas, 'pagina': pagina, 'total': pagina.paginator.count, 'f': f,
        'hay_filtros': bool(activos), 'querystring': urlencode(activos),
        'acciones': RegistroAuditoria.ACCIONES, 'corredoras': Corredora.objects.order_by('nombre')})


@never_cache
@require_GET
@permiso_requerido(BITACORA)
def bitacora_detalle(request, pk):
    r = get_object_or_404(RegistroAuditoria.objects.select_related('usuario'), pk=pk)
    d = r.detalle if isinstance(r.detalle, dict) else {}
    cambios = [{'campo': etiqueta_campo(k), 'antes': v.get('antes'), 'despues': v.get('despues')}
               for k, v in d.get('cambios', {}).items()]
    instantanea = [{'campo': etiqueta_campo(k), 'valor': v} for k, v in
                   (d.get('antes') or d.get('despues') or {}).items()]
    otros = [{'clave': k, 'valor': v} for k, v in d.items()
             if k not in CLAVES_GENERALES + ('cambios', 'antes', 'despues') and not isinstance(v, (dict, list))]
    return render(request, 'calificaciones/bitacora_detalle.html', {
        'r': r, 'detalle': d, 'cambios': cambios, 'instantanea': instantanea,
        'instantanea_titulo': 'Valores antes de eliminar' if 'antes' in d else 'Valores registrados',
        'otros': otros, 'resumen': resumen(r)})