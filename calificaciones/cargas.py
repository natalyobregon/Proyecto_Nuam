"""Carga masiva por CSV (HDU 06A factores y 06B montos).

Formato entregado por el docente (una fila por calificación; separador «;»; coma decimal;
con encabezado `tipo_carga;ejercicio;...;c8;...;c37`, que se ignora):

    tipo_carga (MONTOS|FACTORES) ; ejercicio ; mercado ; instrumento ; fecha_pago (DD-MM-AAAA) ;
    secuencia ; numero_dividendo ; valor_historico ; descripcion ; c8 ... c37 (30 valores)

Cada fila trae su propio tipo: en las MONTOS el sistema calcula los factores con la misma regla
del ingreso manual (calculos.py); en las FACTORES se usan tal cual. Un archivo puede mezclar ambos.

Reglas: todo o nada (si una fila falla no se carga ninguna), errores por fila y columna,
llave única (corredora, mercado, instrumento, ejercicio, secuencia) con upsert, sin celdas vacías
en los 30 valores (se informa 0 si no aplica), sin separador de miles.
"""
import csv
import hashlib
import io
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from cuentas.servicios import instantanea, registrar

from .calculos import (CERO, COLUMNAS, UNO, calcular_factores_desde_montos,
                       redondear_8_decimales, validar_suma_factores_8_a_19)
from .models import Calificacion, CargaMasiva, FactorCalificacion, MontoCalificacion

MAX_BYTES = 5 * 1024 * 1024      # 5 MB
MAX_FILAS = 2000
MAX_ERRORES_DETALLE = 200        # lo que se guarda/muestra; el conteo real se informa aparte
N_BASICAS = 9
N_COLUMNAS = N_BASICAS + len(COLUMNAS)      # 39
RE_INSTRUMENTO = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._\- ]{0,29}$')   # sin =, +, @ al inicio (inyección en CSV)
MERCADOS_VALIDOS = {codigo for codigo, _ in Calificacion.MERCADOS}
ENCABEZADO_BASICO = ['tipo_carga', 'ejercicio', 'mercado', 'instrumento', 'fecha_pago', 'secuencia',
                     'numero_dividendo', 'valor_historico', 'descripcion']
TIPOS_FILA = ('MONTOS', 'FACTORES')
MAX_DESCRIPCION = 255
RE_FECHA = re.compile(r'^\d{2}-\d{2}-\d{4}$')
RE_NUMERO = re.compile(r'^\d+(?:[.,]\d+)?$')       # un solo separador decimal; sin miles ni signo
PELIGROSOS_AL_INICIO = ('=', '+', '-', '@', '\t', '\r')


class ArchivoInvalido(Exception):
    """Error que impide leer el archivo completo (tamaño, formato, vacío...)."""


def raiz_cargas():
    return Path(getattr(settings, 'CARGAS_ROOT', settings.BASE_DIR / 'archivos_cargas'))


def calcular_hash(contenido):
    return hashlib.sha256(contenido).hexdigest()


def guardar_original(contenido, hash_sha256):
    """Guarda el CSV tal como llegó. El nombre lo genera el sistema (no el usuario)."""
    ahora = timezone.now()
    relativa = Path(f'{ahora:%Y}') / f'{ahora:%m}' / f'{ahora:%Y%m%d%H%M%S}_{hash_sha256[:16]}.csv'
    destino = raiz_cargas() / relativa
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(contenido)
    return relativa.as_posix()


def leer_original(carga):
    """Devuelve los bytes guardados, verificando que la huella siga igual."""
    ruta = (raiz_cargas() / carga.archivo_ruta).resolve()
    if not str(ruta).startswith(str(raiz_cargas().resolve())) or not ruta.is_file():
        raise ArchivoInvalido('No se encontró el archivo original de la carga.')
    contenido = ruta.read_bytes()
    if calcular_hash(contenido) != carga.hash_sha256:
        raise ArchivoInvalido('El archivo guardado no coincide con su huella SHA-256: fue alterado.')
    return contenido


def plantilla_csv():
    """CSV de ejemplo (caso del HDU en MONTOS y su equivalente en FACTORES); sirve de plantilla."""
    encabezado = ENCABEZADO_BASICO + [f'c{c}' for c in COLUMNAS]
    montos = {8: '192770580', 9: '64161878', 10: '0', 11: '111812860', 25: '71298705', 30: '15837333'}
    factores = {8: '0,52277431', 9: '0,17400052', 10: '0', 11: '0,30322517', 25: '0,19335488', 30: '0,04294924'}
    filas = [
        ['MONTOS', '2025', 'ACN', 'EMPRESA-HDU', '15-05-2025', '10001', '290', '48,50',
         'Ejemplo del HDU (montos)'] + [montos.get(c, '0') for c in COLUMNAS],
        ['FACTORES', '2025', 'ACN', 'EMPRESA-HDU-F', '15-05-2025', '10002', '291', '48,50',
         'Mismo ejemplo con factores directos'] + [factores.get(c, '0') for c in COLUMNAS],
    ]
    salida = io.StringIO()
    escritor = csv.writer(salida, delimiter=';', lineterminator='\n')
    escritor.writerow(encabezado)
    escritor.writerows(filas)
    return salida.getvalue()


def _decodificar(contenido):
    try:
        return contenido.decode('utf-8-sig')
    except UnicodeDecodeError:
        return contenido.decode('cp1252', errors='replace')   # Excel en Windows


def _delimitador(texto):
    primera = next((l for l in texto.splitlines() if l.strip()), '')
    return max((';', ',', '\t'), key=primera.count)


def _leer_filas(contenido):
    if len(contenido) > MAX_BYTES:
        raise ArchivoInvalido(f'El archivo supera el máximo de {MAX_BYTES // (1024 * 1024)} MB.')
    if b'\x00' in contenido:
        raise ArchivoInvalido('El archivo no es un CSV de texto válido.')
    texto = _decodificar(contenido)
    lector = csv.reader(io.StringIO(texto), delimiter=_delimitador(texto))
    filas = []
    try:
        for nro, celdas in enumerate(lector, start=1):
            if not any(c.strip() for c in celdas):
                continue
            if not filas and celdas[0].strip().strip('\ufeff').lower() == 'tipo_carga':
                continue                                    # encabezado
            filas.append((nro, [c.strip() for c in celdas]))
    except csv.Error as exc:
        raise ArchivoInvalido(f'El archivo no se puede leer como CSV: {exc}')
    if not filas:
        raise ArchivoInvalido('El archivo no contiene filas de datos.')
    if len(filas) > MAX_FILAS:
        raise ArchivoInvalido(f'El archivo tiene {len(filas)} filas; el máximo por carga es {MAX_FILAS}.')
    return filas


def _decimal_estricto(texto, max_decimales):
    """Texto -> (Decimal, None) o (None, mensaje). Acepta «,» o «.» como decimal, sin miles ni signo."""
    if texto == '':
        return None, 'Está vacío (si no aplica, escriba 0).'
    if texto.startswith('-'):
        return None, 'No puede ser negativo.'
    if not RE_NUMERO.match(texto):
        return None, 'Debe ser un número (sin separador de miles; decimales con coma o punto).'
    try:
        valor = Decimal(texto.replace(',', '.'))
    except InvalidOperation:
        return None, 'Debe ser un número válido.'
    if -valor.as_tuple().exponent > max_decimales and valor != valor.quantize(Decimal(1).scaleb(-max_decimales)):
        return None, f'Admite como máximo {max_decimales} decimales.'
    return valor, None


def _validar_fila(nro, celdas):
    """Devuelve (datos | None, [errores]). Reúne todos los errores de la fila, no solo el primero."""
    errores = []

    def error(columna, mensaje):
        errores.append({'fila': nro, 'columna': columna, 'error': mensaje})

    if len(celdas) != N_COLUMNAS:
        error('(fila)', f'Tiene {len(celdas)} columnas y deben ser {N_COLUMNAS} '
                        '(9 de datos básicos + 30 valores, c8 a c37).')
        return None, errores

    tipo = celdas[0].upper()
    if tipo not in TIPOS_FILA:
        error('tipo_carga', 'Debe ser MONTOS o FACTORES.')

    ejercicio = None
    if not celdas[1].isdigit() or len(celdas[1]) != 4 or not 1900 <= int(celdas[1]) <= 2100:
        error('ejercicio', 'Debe ser un año de 4 dígitos entre 1900 y 2100.')
    else:
        ejercicio = int(celdas[1])

    mercado = celdas[2].upper()
    if mercado not in MERCADOS_VALIDOS:
        error('mercado', f'«{celdas[2][:10]}» no es un mercado válido ({", ".join(sorted(MERCADOS_VALIDOS))}).')

    instrumento = celdas[3]
    if not RE_INSTRUMENTO.match(instrumento):
        error('instrumento', 'Obligatorio, hasta 30 caracteres (letras, números, punto, guion o espacio).')

    fecha = None
    if not RE_FECHA.match(celdas[4]):
        error('fecha_pago', 'Debe tener formato DD-MM-AAAA.')
    else:
        try:
            fecha = datetime.strptime(celdas[4], '%d-%m-%Y').date()
        except ValueError:
            error('fecha_pago', 'No es una fecha real.')

    secuencia = None
    if not celdas[5].isdigit() or int(celdas[5]) <= 10000:
        error('secuencia', 'Debe ser un entero mayor a 10.000.')
    else:
        secuencia = int(celdas[5])

    n_div = None
    if celdas[6] != '':
        if not celdas[6].isdigit():
            error('numero_dividendo', 'Debe ser un entero mayor o igual a 0.')
        else:
            n_div = int(celdas[6])

    valor_hist, mensaje = _decimal_estricto(celdas[7], 2)
    if mensaje:
        error('valor_historico', mensaje)

    descripcion = celdas[8]
    if len(descripcion) > MAX_DESCRIPCION:
        error('descripcion', f'Supera el máximo de {MAX_DESCRIPCION} caracteres ({len(descripcion)}).')
    elif descripcion.startswith(PELIGROSOS_AL_INICIO):
        error('descripcion', 'No puede comenzar con =, +, - ni @ (podría interpretarse como fórmula en Excel).')

    es_factor = tipo == 'FACTORES'
    valores = {}
    for desplazamiento, col in enumerate(COLUMNAS):
        dec, mensaje = _decimal_estricto(celdas[N_BASICAS + desplazamiento], 2 if tipo == 'MONTOS' else 8)
        if mensaje:
            error(f'c{col}', mensaje)
        else:
            valores[col] = dec

    if errores:
        return None, errores

    if es_factor:
        factores = {col: redondear_8_decimales(v) for col, v in valores.items()}   # ya tienen <= 8 decimales
        montos = None
    else:
        try:
            factores = calcular_factores_desde_montos(valores)
        except ValueError as exc:
            error('c8..c19', str(exc))
            return None, errores
        montos = valores

    for col, factor in factores.items():
        if factor > UNO:
            error(f'c{col}', f'El factor calculado es {factor} y no puede superar 1.' if not es_factor
                  else f'El factor es {factor} y no puede superar 1.')
    ok, suma = validar_suma_factores_8_a_19(factores)
    if not ok:
        error('c8..c19', f'La suma de los factores 8 a 19 es {suma} y supera 1.')
    if errores:
        return None, errores

    return {
        'fila': nro, 'tipo_carga': tipo, 'ejercicio': ejercicio, 'mercado': mercado,
        'instrumento': instrumento, 'fecha_pago': fecha, 'secuencia_evento': secuencia,
        'numero_dividendo': n_div, 'valor_historico': valor_hist, 'descripcion': descripcion,
        'montos': montos, 'factores': factores,
    }, []


def _llave(d):
    return (d['mercado'], d['instrumento'], d['ejercicio'], d['secuencia_evento'])


def tipo_de_carga(filas):
    """'montos', 'factores' o 'mixto' según las filas del archivo."""
    tipos = {f['tipo_carga'] for f in filas}
    if tipos == {'MONTOS'}:
        return 'montos'
    if tipos == {'FACTORES'}:
        return 'factores'
    return 'mixto'


def validar_archivo(contenido):
    """Valida TODO el archivo sin escribir nada. Lanza ArchivoInvalido si no se puede ni leer.

    Devuelve {'filas': [datos], 'errores': [...], 'filas_con_error': n, 'total': n}.
    """
    filas_crudas = _leer_filas(contenido)
    filas, errores, vistas, con_error = [], [], {}, set()
    for nro, celdas in filas_crudas:
        datos, errs = _validar_fila(nro, celdas)
        if datos:
            llave = _llave(datos)
            if llave in vistas:
                errs = [{'fila': nro, 'columna': '(llave)',
                         'error': f'Repite la calificación de la fila {vistas[llave]} '
                                  '(mismo mercado, instrumento, ejercicio y secuencia).'}]
                datos = None
            else:
                vistas[llave] = nro
        if errs:
            con_error.add(nro)
            errores.extend(errs)
        else:
            filas.append(datos)
    return {'filas': filas, 'errores': errores, 'filas_con_error': len(con_error),
            'total': len(filas_crudas)}


def marcar_operaciones(filas, corredora):
    """Agrega a cada fila si se va a 'crear' o 'actualizar' (llave única de la corredora)."""
    existentes = set(Calificacion.objects.filter(
        corredora=corredora, origen='local_corredora').values_list(
        'mercado', 'instrumento', 'ejercicio', 'secuencia_evento'))
    for d in filas:
        d['operacion'] = 'actualizar' if _llave(d) in existentes else 'crear'
    return filas


@transaction.atomic
def aplicar_carga(request, carga, filas, errores=None, filas_con_error=0):
    """Graba las filas dadas (upsert por llave única). Si algo falla, no queda nada (rollback).

    `errores`/`filas_con_error`: filas omitidas por inválidas (modo «solo las válidas»).
    """
    corredora, usuario = carga.corredora, carga.usuario
    creadas = actualizadas = 0
    for d in filas:
        existente = Calificacion.objects.filter(
            corredora=corredora, origen='local_corredora', mercado=d['mercado'],
            instrumento=d['instrumento'], ejercicio=d['ejercicio'],
            secuencia_evento=d['secuencia_evento']).first()
        campos = {'fecha_pago': d['fecha_pago'], 'numero_dividendo': d['numero_dividendo'],
                  'valor_historico': d['valor_historico'], 'descripcion': d['descripcion']}
        if existente:
            montos_antes = {m.numero_columna: m.valor for m in existente.montos.all()}
            factores_antes = {f.numero_columna: f.valor for f in existente.factores.all()}
            antes = instantanea(existente, montos_antes, factores_antes)
            for k, v in campos.items():
                setattr(existente, k, v)
            existente.eliminado = False
            existente.fuente_ingreso = 'archivo'
            existente.carga = carga
            existente.save()
            calificacion = existente
            _actualizar_hijos(MontoCalificacion, calificacion, d['montos'])
            _actualizar_hijos(FactorCalificacion, calificacion, d['factores'])
            operacion = 'actualizar'
            actualizadas += 1
        else:
            calificacion = Calificacion.objects.create(
                corredora=corredora, origen='local_corredora', fuente_ingreso='archivo', carga=carga,
                mercado=d['mercado'], instrumento=d['instrumento'], ejercicio=d['ejercicio'],
                secuencia_evento=d['secuencia_evento'], **campos)
            MontoCalificacion.objects.bulk_create([
                MontoCalificacion(calificacion=calificacion, numero_columna=c,
                                  valor=(d['montos'] or {}).get(c, CERO)) for c in COLUMNAS])
            FactorCalificacion.objects.bulk_create([
                FactorCalificacion(calificacion=calificacion, numero_columna=c, valor=d['factores'][c])
                for c in COLUMNAS])
            antes = None
            operacion = 'crear'
            creadas += 1

        despues = instantanea(calificacion,
                              d['montos'] if d['montos'] is not None else None,
                              d['factores'])
        if operacion == 'actualizar' and d['montos'] is None:
            despues = {k: v for k, v in despues.items() if not k.startswith('monto_')}
            antes = {k: v for k, v in antes.items() if not k.startswith('monto_')}
        registrar(request, 'carga', usuario, calificacion,
                  antes=antes, despues=despues,
                  via='archivo', carga_id=carga.id_carga, operacion=operacion, fila=d['fila'])

    carga.estado = 'parcial' if filas_con_error else 'completada'
    carga.total_registros = len(filas) + filas_con_error
    carga.registros_ok = len(filas)
    carga.registros_error = filas_con_error
    carga.detalle_errores = {'creadas': creadas, 'actualizadas': actualizadas}
    if errores:
        carga.detalle_errores['errores'] = errores[:MAX_ERRORES_DETALLE]
    carga.save()
    return creadas, actualizadas


def _actualizar_hijos(modelo, calificacion, valores):
    """Actualiza (o crea si faltara) las 30 filas hijas. valores=None deja los montos como estaban."""
    if valores is None:
        return
    actuales = {h.numero_columna: h for h in modelo.objects.filter(calificacion=calificacion)}
    nuevos, a_actualizar = [], []
    for col in COLUMNAS:
        if col in actuales:
            actuales[col].valor = valores[col]
            a_actualizar.append(actuales[col])
        else:
            nuevos.append(modelo(calificacion=calificacion, numero_columna=col, valor=valores[col]))
    if a_actualizar:
        modelo.objects.bulk_update(a_actualizar, ['valor'])
    if nuevos:
        modelo.objects.bulk_create(nuevos)