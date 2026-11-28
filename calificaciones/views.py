from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.utils.http import urlencode
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.shortcuts import get_object_or_404 #ESTO ES PARA ELIMINAR UNA CALIFICACION

from cuentas.alcance import calificaciones_visibles, es_editable_por, obtener_calificacion
from cuentas.permisos import (
    ADMINISTRAR_USUARIOS,
    BITACORA,
    CARGA_MASIVA,
    ELIMINAR,
    INGRESAR,
    MODIFICAR,
    permiso_requerido,
    tiene_permiso,
)
from cuentas.servicios import CAMPOS_AUDITADOS, auditar, instantanea, registrar
from .calculos import (
    CERO,
    calcular_factores_desde_montos,
    parsear_decimal,
    redondear_8_decimales,
    resolver_factores_editables,
    validar_suma_factores_8_a_19,
)
from . import cargas
from .forms import CalificacionBasicaForm, CargaMasivaForm
from .models import Calificacion, CargaMasiva, FactorCalificacion, MontoCalificacion


POR_PAGINA = 25


@never_cache
@login_required
def grilla_calificaciones(request):
    instrumento = (request.GET.get('instrumento') or '').strip()[:30]
    mercado = (request.GET.get('mercado') or '').strip()
    origen = (request.GET.get('origen') or '').strip()
    periodo = (request.GET.get('periodo') or '').strip()

    base_visible = calificaciones_visibles(request.user)
    queryset = (
        base_visible
        .select_related('corredora')
        .prefetch_related('factores')
        .order_by('-ejercicio', 'instrumento', 'secuencia_evento', 'pk')
    )

    if instrumento:
        queryset = queryset.filter(instrumento__icontains=instrumento)
    if mercado:
        queryset = queryset.filter(mercado=mercado)
    if origen:
        queryset = queryset.filter(origen=origen)
    if periodo.isdigit():
        queryset = queryset.filter(ejercicio=periodo)

    periodos_disponibles = (
        base_visible.values_list('ejercicio', flat=True).distinct().order_by('-ejercicio'))

    pagina = Paginator(queryset, POR_PAGINA).get_page(request.GET.get('page'))
    columnas_factores = list(range(8, 38))
    filas = []
    for calif in pagina.object_list:
        mapa_factores = {f.numero_columna: f.valor for f in calif.factores.all()}
        filas.append({
            'obj': calif,
            'factores': [mapa_factores.get(col) for col in columnas_factores],
            'editable': es_editable_por(request.user, calif),
        })

    filtros = {'instrumento': instrumento, 'mercado': mercado, 'origen': origen,
               'periodo': periodo if periodo.isdigit() else ''}
    filtros_activos = {k: v for k, v in filtros.items() if v}

    contexto = {
        'filas': filas,
        'pagina': pagina,
        'total': pagina.paginator.count,
        'columnas_factores': columnas_factores,
        'filtro_instrumento': instrumento,
        'filtro_mercado': mercado,
        'filtro_origen': origen,
        'filtro_periodo': filtros['periodo'],
        'hay_filtros': bool(filtros_activos),
        'querystring': urlencode(filtros_activos),     # para los enlaces de paginación
        'mercados_disponibles': Calificacion.MERCADOS,  # lista controlada
        'periodos_disponibles': periodos_disponibles,
        'origenes_disponibles': Calificacion.ORIGENES,
        'puede_ingresar': tiene_permiso(request.user, INGRESAR),
        'puede_carga_masiva': tiene_permiso(request.user, CARGA_MASIVA),
        'puede_modificar': tiene_permiso(request.user, MODIFICAR),
        'puede_eliminar': tiene_permiso(request.user, ELIMINAR),
        'puede_bitacora': tiene_permiso(request.user, BITACORA),
        'puede_admin_usuarios': tiene_permiso(request.user, ADMINISTRAR_USUARIOS),
    }
    return render(request, 'calificaciones/grilla.html', contexto)


COLUMNAS = list(range(8, 38))
MSG_LLAVE_DUPLICADA = ('Ya existe una calificación con esa combinación de corredora, mercado, '
                       'instrumento, año, secuencia y origen.')


def _marcar_invalidos(form):
    for nombre_campo in form.errors:
        if nombre_campo in form.fields:
            clase = form.fields[nombre_campo].widget.attrs.get('class', '')
            if 'is-invalid' not in clase:
                form.fields[nombre_campo].widget.attrs['class'] = f'{clase} is-invalid'.strip()


def _gestionar_formulario(request, calificacion=None):
    """Ingreso (calificacion=None) y modificación (calificacion existente) comparten reglas.

    El cálculo, la validación de la suma 8-19 y los mensajes son los mismos en ambos casos.
    """
    editando = calificacion is not None
    montos_previos, factores_previos = {}, {}
    if editando:
        montos_previos = {m.numero_columna: m.valor for m in calificacion.montos.all()}
        factores_previos = {f.numero_columna: f.valor for f in calificacion.factores.all()}
    # Foto «antes» ANTES de enlazar el formulario: validar el form modifica la instancia en memoria.
    foto_antes = instantanea(calificacion, montos_previos, factores_previos) if editando else None

    valores_montos = {col: format(montos_previos.get(col, CERO), 'f') if editando else '0' for col in COLUMNAS}
    valores_factores = {col: format(factores_previos[col], 'f') if col in factores_previos else ''
                        for col in COLUMNAS}
    factores_calculados = None

    if request.method == 'POST':
        form = CalificacionBasicaForm(request.POST, instance=calificacion)
        accion = request.POST.get('accion', 'guardar')
        for col in COLUMNAS:
            valores_montos[col] = request.POST.get(f'monto_{col}', '0')
            valores_factores[col] = request.POST.get(f'factor_{col}', '')

        form_ok = form.is_valid()
        montos = {}
        error_monto = None
        for col in COLUMNAS:
            dec = parsear_decimal(valores_montos[col])
            if dec is None or dec < CERO:
                error_monto = f'Revise el monto de la columna {col}: debe ser un número mayor o igual a 0.'
                break
            montos[col] = dec

        if not form_ok:
            _marcar_invalidos(form)
            messages.error(request, 'Revise los campos obligatorios resaltados antes de continuar.')
        elif error_monto:
            messages.error(request, error_monto)
        else:
            try:
                factores_calculados = calcular_factores_desde_montos(montos)
            except ValueError as exc:
                messages.error(request, str(exc))

            if factores_calculados is not None:
                if accion == 'calcular':
                    for col in COLUMNAS:
                        valores_factores[col] = format(redondear_8_decimales(factores_calculados[col]), 'f')
                    messages.info(request, 'Factores calculados. Revíselos o ajústelos a mano y luego presione "Guardar calificación".')
                else:
                    try:
                        finales = resolver_factores_editables(request.POST, factores_calculados)
                    except ValueError as exc:
                        messages.error(request, str(exc))
                        finales = None

                    if finales is not None:
                        for col in COLUMNAS:
                            valores_factores[col] = format(finales[col], 'f')
                        ok_suma, suma = validar_suma_factores_8_a_19(finales)
                        montos_cambiaron = editando and any(
                            montos[c] != montos_previos.get(c, CERO) for c in COLUMNAS)
                        factores_intactos = editando and all(
                            finales[c] == factores_previos.get(c, CERO) for c in COLUMNAS)
                        if not ok_suma:
                            messages.error(request, f'La suma de los factores 8 a 19 ({suma}) supera 1. No se puede guardar.')
                        elif montos_cambiaron and factores_intactos:
                            messages.error(request, 'Cambió los montos pero no los factores: presione "Calcular factores" antes de guardar.')
                        else:
                            try:
                                with transaction.atomic():
                                    if editando:
                                        calificacion = _guardar_modificacion(
                                            request, form, calificacion, montos, finales, foto_antes)
                                        messages.success(request, 'Calificación modificada correctamente.')
                                    else:
                                        _guardar_nueva(request, form, montos, finales)
                                        messages.success(request, 'Calificación, montos y factores guardados correctamente.')
                                return redirect('grilla')
                            except IntegrityError:
                                messages.error(request, MSG_LLAVE_DUPLICADA)
    else:
        form = CalificacionBasicaForm(instance=calificacion)

    campos_montos = [{'col': col, 'valor': valores_montos[col]} for col in COLUMNAS]
    campos_factores = [{'col': col, 'valor': valores_factores[col]} for col in COLUMNAS]
    mostrar_factores = editando or factores_calculados is not None or any(
        str(valores_factores[col]).strip() != '' for col in COLUMNAS)
    return render(request, 'calificaciones/ingresar.html', {
        'form': form,
        'modo': 'editar' if editando else 'ingresar',
        'calificacion': calificacion,
        'campos_montos': campos_montos,
        'campos_factores': campos_factores,
        'mostrar_factores': mostrar_factores,
    })


def _guardar_nueva(request, form, montos, factores):
    """Crea la calificación del corredor. Si existía una eliminada con la misma llave, la reactiva."""
    datos = form.cleaned_data
    previa = Calificacion.objects.filter(
        corredora=request.user.corredora, origen='local_corredora', eliminado=True,
        mercado=datos['mercado'], instrumento=datos['instrumento'],
        ejercicio=datos['ejercicio'], secuencia_evento=datos['secuencia_evento']).first()
    reactivada = previa is not None
    if reactivada:
        calificacion = previa
        for campo in CAMPOS_AUDITADOS:
            setattr(calificacion, campo, datos.get(campo))
        calificacion.eliminado = False
        calificacion.carga = None
        calificacion.dividendo = datos.get('dividendo') or CERO
        calificacion.valor_historico = datos.get('valor_historico') or CERO
        calificacion.tipo_sociedad = datos.get('tipo_sociedad') or 'A'
        calificacion.isfut = bool(datos.get('isfut'))
        calificacion.fuente_ingreso = 'manual'
        calificacion.save()
        calificacion.montos.all().delete()
        calificacion.factores.all().delete()
    else:
        calificacion = form.save(commit=False)
        calificacion.corredora = request.user.corredora
        calificacion.origen = 'local_corredora'          # el ingreso manual siempre es del corredor
        calificacion.fuente_ingreso = 'manual'
        calificacion.save()

    MontoCalificacion.objects.bulk_create([
        MontoCalificacion(calificacion=calificacion, numero_columna=c, valor=montos[c]) for c in COLUMNAS])
    FactorCalificacion.objects.bulk_create([
        FactorCalificacion(calificacion=calificacion, numero_columna=c, valor=factores[c]) for c in COLUMNAS])
    registrar(request, 'crear', request.user, calificacion,
              despues=instantanea(calificacion,
                                  {c: v for c, v in montos.items() if v},
                                  {c: v for c, v in factores.items() if v}),
              via='manual', reactivada=reactivada)
    return calificacion


def _guardar_modificacion(request, form, calificacion, montos, factores, antes):
    calificacion = form.save(commit=False)
    calificacion.save()
    for modelo, nuevos in ((MontoCalificacion, montos), (FactorCalificacion, factores)):
        filas = list(modelo.objects.filter(calificacion=calificacion))
        for fila in filas:
            fila.valor = nuevos[fila.numero_columna]
        modelo.objects.bulk_update(filas, ['valor'])   # sin save(): la suma 8-19 ya se validó completa
    despues = instantanea(calificacion, montos, factores)
    registrar(request, 'modificar', request.user, calificacion,
              antes=antes, despues=despues, via='manual')
    return calificacion


@never_cache
@permiso_requerido(INGRESAR)
def ingresar_calificacion(request):
    if not request.user.corredora:
        messages.error(request, 'Su usuario no tiene una corredora asignada para ingresar calificaciones.')
        return redirect('grilla')
    return _gestionar_formulario(request)


def _calificacion_editable(request, pk):
    """Visible para el usuario y propia de su corredora; la de la Bolsa es solo lectura."""
    calificacion = obtener_calificacion(request.user, pk)
    if not es_editable_por(request.user, calificacion):
        raise PermissionDenied
    return calificacion


@never_cache
@permiso_requerido(MODIFICAR)
def editar_calificacion(request, pk):
    calificacion = _calificacion_editable(request, pk)
    return _gestionar_formulario(request, calificacion)


@never_cache
@permiso_requerido(ELIMINAR)
def eliminar_calificacion(request, pk):
    """GET muestra la confirmación; solo el POST elimina (borrado lógico)."""
    calificacion = _calificacion_editable(request, pk)
    if request.method == 'POST':
        with transaction.atomic():
            antes = instantanea(calificacion)
            calificacion.eliminado = True
            calificacion.save(update_fields=['eliminado', 'fecha_modificacion'])
            registrar(request, 'eliminar', request.user, calificacion, antes=antes, via='manual')
        messages.success(request, 'Calificación eliminada correctamente.')
        return redirect('grilla')
    return render(request, 'calificaciones/eliminar.html', {'calificacion': calificacion})


@never_cache #funcion para mostrar el detalle de una calificacion, con sus montos y factores
@login_required
def detalle_calificacion(request, pk):
    calificacion = get_object_or_404(
        calificaciones_visibles(request.user)
        .filter(eliminado=False)
        .select_related('corredora')
        .prefetch_related('montos', 'factores'),
        pk=pk,
    )
    mapa_montos = {m.numero_columna: m.valor for m in calificacion.montos.all()}
    mapa_factores = {f.numero_columna: f.valor for f in calificacion.factores.all()}

    filas = [
        {
            'col': col,
            'monto': mapa_montos.get(col),
            'factor': mapa_factores.get(col),
        }
        for col in range(8, 38)
    ]

    return render(request, 'calificaciones/detalle.html', {
        'calificacion': calificacion,
        'filas': filas,
        'editable': es_editable_por(request.user, calificacion),
        'puede_modificar': tiene_permiso(request.user, MODIFICAR),
        'puede_eliminar': tiene_permiso(request.user, ELIMINAR),
    })


# ---------------------------------------------------------------- carga masiva
def _carga_propia(request, pk):
    """La carga debe ser de la corredora del usuario (aislamiento, igual que las calificaciones)."""
    try:
        return CargaMasiva.objects.select_related('corredora', 'usuario').get(
            pk=pk, corredora_id=request.user.corredora_id)
    except CargaMasiva.DoesNotExist:
        raise PermissionDenied


@never_cache
@permiso_requerido(CARGA_MASIVA)
def carga_masiva(request):
    if not request.user.corredora_id:
        messages.error(request, 'Su usuario no tiene una corredora asignada para cargar archivos.')
        return redirect('grilla')

    if request.method == 'POST':
        form = CargaMasivaForm(request.POST, request.FILES)
        if form.is_valid():
            archivo = form.cleaned_data['archivo']
            if archivo.size > cargas.MAX_BYTES:
                form.add_error('archivo', f'El archivo supera el máximo de {cargas.MAX_BYTES // (1024 * 1024)} MB.')
            else:
                contenido = archivo.read()
                try:
                    resultado = cargas.validar_archivo(contenido)
                except cargas.ArchivoInvalido as exc:
                    form.add_error('archivo', str(exc))
                else:
                    huella = cargas.calcular_hash(contenido)
                    con_errores = bool(resultado['errores'])
                    carga = CargaMasiva.objects.create(
                        corredora=request.user.corredora, usuario=request.user,
                        tipo=cargas.tipo_de_carga(resultado['filas']) if resultado['filas'] else 'mixto',
                        nombre_archivo=archivo.name[:255], hash_sha256=huella,
                        archivo_ruta=cargas.guardar_original(contenido, huella),
                        total_registros=resultado['total'],
                        registros_ok=len(resultado['filas']),
                        registros_error=resultado['filas_con_error'],
                        estado='con_errores' if con_errores else 'pendiente',
                        detalle_errores=resultado['errores'][:cargas.MAX_ERRORES_DETALLE] or None)
                    return redirect('carga_detalle', pk=carga.pk)
    else:
        form = CargaMasivaForm()

    historial = CargaMasiva.objects.filter(corredora_id=request.user.corredora_id).order_by('-fecha_carga')[:10]
    return render(request, 'calificaciones/carga_masiva.html', {
        'form': form, 'historial': historial,
        'max_mb': cargas.MAX_BYTES // (1024 * 1024), 'max_filas': cargas.MAX_FILAS})


@never_cache
@permiso_requerido(CARGA_MASIVA)
def carga_plantilla(request):
    respuesta = HttpResponse(cargas.plantilla_csv(), content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = 'attachment; filename="plantilla_carga_masiva.csv"'
    return respuesta


@never_cache
@permiso_requerido(CARGA_MASIVA)
def carga_detalle(request, pk):
    """Vista previa (carga pendiente) o resultado (carga ya procesada)."""
    carga = _carga_propia(request, pk)
    previa, aviso = [], None
    if carga.estado in ('pendiente', 'con_errores'):
        try:
            resultado = cargas.validar_archivo(cargas.leer_original(carga))
            previa = cargas.marcar_operaciones(resultado['filas'], carga.corredora)
            nuevas = sum(1 for f in previa if f['operacion'] == 'crear')
            aviso = {'crear': nuevas, 'actualizar': len(previa) - nuevas}
        except cargas.ArchivoInvalido as exc:
            messages.error(request, str(exc))
    if isinstance(carga.detalle_errores, list):
        errores = carga.detalle_errores
    else:
        errores = (carga.detalle_errores or {}).get('errores', [])
    return render(request, 'calificaciones/carga_detalle.html', {
        'carga': carga, 'previa': previa[:20], 'total_previa': len(previa), 'aviso': aviso,
        'errores': errores, 'errores_truncados': carga.registros_error > len({e['fila'] for e in errores}),
        'resumen': carga.detalle_errores if isinstance(carga.detalle_errores, dict) else None,
        'puede_confirmar': carga.estado == 'pendiente',
        'puede_cargar_validas': carga.estado == 'con_errores' and bool(previa)})


@never_cache
@permiso_requerido(CARGA_MASIVA)
def carga_confirmar(request, pk):
    """Solo POST. Vuelve a validar el archivo guardado y recién ahí graba.

    modo=todo     (por defecto): solo si el archivo no tiene errores (todo o nada).
    modo=validas: graba las filas válidas y deja las demás informadas como error.
    """
    carga = _carga_propia(request, pk)
    if request.method != 'POST':
        return redirect('carga_detalle', pk=pk)
    solo_validas = request.POST.get('modo') == 'validas'
    estados_permitidos = ('pendiente', 'con_errores') if solo_validas else ('pendiente',)
    if carga.estado not in estados_permitidos:
        messages.error(request, 'Esta carga ya fue procesada o tiene errores; no se puede confirmar.')
        return redirect('carga_detalle', pk=pk)
    try:
        resultado = cargas.validar_archivo(cargas.leer_original(carga))
    except cargas.ArchivoInvalido as exc:
        carga.estado = 'fallida'
        carga.detalle_errores = [{'fila': 0, 'columna': '(archivo)', 'error': str(exc)}]
        carga.save()
        messages.error(request, str(exc))
        return redirect('carga_detalle', pk=pk)
    if resultado['errores'] and not solo_validas:
        carga.estado = 'con_errores'
        carga.registros_error = resultado['filas_con_error']
        carga.detalle_errores = resultado['errores'][:cargas.MAX_ERRORES_DETALLE]
        carga.save()
        messages.error(request, 'El archivo tiene errores. No se cargó ningún registro.')
        return redirect('carga_detalle', pk=pk)
    if not resultado['filas']:
        messages.error(request, 'El archivo no tiene filas válidas para cargar.')
        return redirect('carga_detalle', pk=pk)
    try:
        with transaction.atomic():
            bloqueada = CargaMasiva.objects.select_for_update().get(pk=carga.pk)
            if bloqueada.estado not in estados_permitidos:          # doble clic / dos pestañas
                messages.error(request, 'Esta carga ya fue procesada.')
                return redirect('carga_detalle', pk=pk)
            creadas, actualizadas = cargas.aplicar_carga(
                request, bloqueada, resultado['filas'],
                errores=resultado['errores'], filas_con_error=resultado['filas_con_error'])
            auditar(request, 'carga', request.user, carga_id=carga.pk, archivo=carga.nombre_archivo,
                    sha256=carga.hash_sha256, tipo=carga.tipo, corredora_id=carga.corredora_id,
                    creadas=creadas, actualizadas=actualizadas,
                    filas_omitidas_por_error=resultado['filas_con_error'])
    except Exception:
        carga.refresh_from_db()
        carga.estado = 'fallida'
        carga.detalle_errores = [{'fila': 0, 'columna': '(sistema)',
                                  'error': 'Error inesperado al grabar. No se cargó ningún registro.'}]
        carga.save()
        messages.error(request, 'Error inesperado al grabar. No se cargó ningún registro.')
        return redirect('carga_detalle', pk=pk)
    mensaje = f'Carga completada: {creadas} creadas y {actualizadas} actualizadas.'
    if resultado['filas_con_error']:
        mensaje += f' Se omitieron {resultado["filas_con_error"]} filas con error (ver detalle).'
    messages.success(request, mensaje)
    return redirect('carga_detalle', pk=pk)