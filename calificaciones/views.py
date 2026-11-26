from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.shortcuts import get_object_or_404 #ESTO ES PARA ELIMINAR UNA CALIFICACION

from cuentas.alcance import calificaciones_visibles, es_editable_por
from cuentas.permisos import (
    ADMINISTRAR_USUARIOS,
    CARGA_MASIVA,
    ELIMINAR,
    INGRESAR,
    MODIFICAR,
    permiso_requerido,
    tiene_permiso,
)
from cuentas.servicios import auditar
from .calculos import (
    CERO,
    calcular_factores_desde_montos,
    parsear_decimal,
    redondear_8_decimales,
    resolver_factores_editables,
    validar_suma_factores_8_a_19,
)
from .forms import CalificacionBasicaForm
from .models import Calificacion, FactorCalificacion, MontoCalificacion


@never_cache
@login_required
def grilla_calificaciones(request):
    mercado = (request.GET.get('mercado') or '').strip()
    origen = (request.GET.get('origen') or '').strip()
    periodo = (request.GET.get('periodo') or '').strip()

    queryset = (
        calificaciones_visibles(request.user)
        .filter(eliminado=False)
        .select_related('corredora')
        .prefetch_related('factores')
        .order_by('-ejercicio', 'instrumento', 'secuencia_evento')
    )

    if mercado:
        queryset = queryset.filter(mercado=mercado)
    if origen:
        queryset = queryset.filter(origen=origen)
    if periodo:
        queryset = queryset.filter(ejercicio=periodo)

    base_visible = calificaciones_visibles(request.user).filter(eliminado=False)
    mercados_disponibles = Calificacion.MERCADOS  # lista controlada
    periodos_disponibles = (
        base_visible.values_list('ejercicio', flat=True)
        .distinct()
        .order_by('-ejercicio')
    )

    columnas_factores = list(range(8, 38))
    filas = []
    for calif in queryset[:100]:
        mapa_factores = {f.numero_columna: f.valor for f in calif.factores.all()}
        valores_factores = [mapa_factores.get(col) for col in columnas_factores]
        filas.append({
            'obj': calif,
            'factores': valores_factores,
            'editable': es_editable_por(request.user, calif),
        })

    contexto = {
        'filas': filas,
        'columnas_factores': columnas_factores,
        'filtro_mercado': mercado,
        'filtro_origen': origen,
        'filtro_periodo': periodo,
        'mercados_disponibles': mercados_disponibles,
        'periodos_disponibles': periodos_disponibles,
        'origenes_disponibles': Calificacion.ORIGENES,
        'puede_ingresar': tiene_permiso(request.user, INGRESAR),
        'puede_carga_masiva': tiene_permiso(request.user, CARGA_MASIVA),
        'puede_modificar': tiene_permiso(request.user, MODIFICAR),
        'puede_eliminar': tiene_permiso(request.user, ELIMINAR),
        'puede_admin_usuarios': tiene_permiso(request.user, ADMINISTRAR_USUARIOS),
    }
    return render(request, 'calificaciones/grilla.html', contexto)


@never_cache
@permiso_requerido(INGRESAR)
def ingresar_calificacion(request):
    if not request.user.corredora:
        messages.error(request, 'Su usuario no tiene una corredora asignada para ingresar calificaciones.')
        return redirect('grilla')

    columnas_montos = list(range(8, 38))
    columnas_factores = list(range(8, 38))
    valores_montos = {col: '0' for col in columnas_montos}
    factores_calculados = None
    valores_factores = {col: '' for col in columnas_factores}

    if request.method == 'POST':
        form = CalificacionBasicaForm(request.POST)
        accion = request.POST.get('accion', 'guardar')

        for col in columnas_montos:
            valores_montos[col] = request.POST.get(f'monto_{col}', '0')

        for col in columnas_factores:
            valores_factores[col] = request.POST.get(f'factor_{col}', '')

        form_ok = form.is_valid()
        montos_decimales = {}
        error_monto = None

        for col in columnas_montos:
            dec = parsear_decimal(valores_montos[col])
            if dec is None or dec < CERO:
                error_monto = f'Revise el monto de la columna {col}: debe ser un número mayor o igual a 0.'
                break
            montos_decimales[col] = dec

        if not form_ok:
            for nombre_campo in form.errors:
                if nombre_campo in form.fields:
                    clase_actual = form.fields[nombre_campo].widget.attrs.get('class', '')
                    if 'is-invalid' not in clase_actual:
                        form.fields[nombre_campo].widget.attrs['class'] = f'{clase_actual} is-invalid'.strip()
            messages.error(request, 'Revise los campos obligatorios resaltados antes de continuar.')
        elif error_monto:
            messages.error(request, error_monto)
        else:
            try:
                factores_calculados = calcular_factores_desde_montos(montos_decimales)
            except ValueError as exc:
                messages.error(request, str(exc))
                factores_calculados = None

            if factores_calculados is not None:
                if accion == 'calcular':
                    for col in columnas_factores:
                        valores_factores[col] = format(redondear_8_decimales(factores_calculados[col]), 'f')
                    messages.info(
                        request,
                        'Factores calculados. Revíselos o ajústelos a mano y luego presione "Guardar calificación".'
                    )
                else:
                    try:
                        factores_finales = resolver_factores_editables(request.POST, factores_calculados)
                    except ValueError as exc:
                        messages.error(request, str(exc))
                        factores_finales = None

                    if factores_finales is not None:
                        for col in columnas_factores:
                            valores_factores[col] = format(factores_finales[col], 'f')

                        suma_valida, suma_8_19 = validar_suma_factores_8_a_19(factores_finales)
                        if not suma_valida:
                            messages.error(
                                request,
                                f'La suma de los factores 8 a 19 ({suma_8_19}) supera 1. No se puede guardar.'
                            )
                        else:
                            try:
                                with transaction.atomic():
                                    calificacion = form.save(commit=False)
                                    calificacion.corredora = request.user.corredora
                                    calificacion.origen = 'local_corredora'   # el ingreso manual siempre es del corredor
                                    calificacion.fuente_ingreso = 'manual'
                                    calificacion.save()

                                    MontoCalificacion.objects.bulk_create([
                                        MontoCalificacion(
                                            calificacion=calificacion,
                                            numero_columna=col,
                                            valor=montos_decimales[col],
                                        )
                                        for col in columnas_montos
                                    ])

                                    FactorCalificacion.objects.bulk_create([
                                        FactorCalificacion(
                                            calificacion=calificacion,
                                            numero_columna=col,
                                            valor=factores_finales[col],
                                        )
                                        for col in columnas_factores
                                    ])

                                    auditar(
                                        request,
                                        'crear',
                                        request.user,
                                        id_calificacion=calificacion.id_calificacion,
                                        via='manual',
                                        instrumento=calificacion.instrumento,
                                        ejercicio=calificacion.ejercicio,
                                    )

                                messages.success(request, 'Calificación, montos y factores guardados correctamente.')
                                return redirect('grilla')
                            except IntegrityError:
                                messages.error(
                                    request,
                                    'Ya existe una calificación con esa combinación de corredora, mercado, instrumento, año, secuencia y origen.'
                                )
    else:
        form = CalificacionBasicaForm()

    campos_montos = [{'col': col, 'valor': valores_montos[col]} for col in columnas_montos]
    campos_factores = [{'col': col, 'valor': valores_factores[col]} for col in columnas_factores]
    mostrar_factores = factores_calculados is not None or any(
        str(valores_factores[col]).strip() != '' for col in columnas_factores
    )

    return render(request, 'calificaciones/ingresar.html', {
        'form': form,
        'columnas_montos': columnas_montos,
        'valores_montos': valores_montos,
        'campos_montos': campos_montos,
        'factores_calculados': factores_calculados,
        'campos_factores': campos_factores,
        'mostrar_factores': mostrar_factores,
    })

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
    })