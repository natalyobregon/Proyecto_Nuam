"""Cálculo y validación de factores (HDU 03, 04 y 06B).

Una sola implementación para el ingreso manual, la edición y la carga masiva.
Regla del HDU:  factor(n) = monto(n) / suma de los montos de las columnas 8 a 19,
para cada columna n de la 8 a la 37, con 8 decimales exactos (Decimal, nunca float).
"""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

OCHO_DECIMALES = Decimal('0.00000001')
UNO = Decimal('1')
CERO = Decimal('0')

COLUMNAS = range(8, 38)               # 30 columnas: montos y factores
COLUMNAS_DISTRIBUCION = range(8, 20)  # 8 a 19: divisor y suma máxima 1


def parsear_decimal(valor, por_defecto=CERO):
    """Texto -> Decimal. Acepta coma o punto. Devuelve None si no es un número."""
    if valor is None or str(valor).strip() == '':
        return por_defecto
    try:
        resultado = Decimal(str(valor).strip().replace(',', '.'))
    except InvalidOperation:
        return None
    return resultado if resultado.is_finite() else None


def redondear_8_decimales(valor):
    return valor.quantize(OCHO_DECIMALES, rounding=ROUND_HALF_UP)


def suma_distribucion(valores):
    """Suma de las columnas 8 a 19 de un dict {columna: Decimal}."""
    return sum((valores.get(col, CERO) or CERO for col in COLUMNAS_DISTRIBUCION), CERO)


def calcular_factores_desde_montos(montos_por_col):
    """montos_por_col: dict {8: Decimal, ..., 37: Decimal}. Las columnas que faltan valen 0.

    Devuelve {8: Decimal, ..., 37: Decimal} con 8 decimales exactos.
    Lanza ValueError si la suma de los montos 8 a 19 es 0 (no hay divisor).
    """
    divisor = suma_distribucion(montos_por_col)
    if divisor <= CERO:
        raise ValueError('La suma de los montos de las columnas 8 a 19 es 0: no se pueden calcular los factores.')
    exactos = {col: montos_por_col.get(col, CERO) / divisor for col in COLUMNAS}
    factores = {col: redondear_8_decimales(valor) for col, valor in exactos.items()}
    return _ajustar_redondeo_8_a_19(factores, exactos)


def _ajustar_redondeo_8_a_19(factores, exactos):
    """Si redondear cada factor hace que la suma de 8 a 19 pase de 1 (p. ej. 1,00000001), resta
    1e-8 a los factores que más se «subieron» al redondear hasta que la suma sea <= 1.

    La suma exacta de los factores 8 a 19 es 1; el redondeo individual puede dejarla 1e-8 más arriba
    y la regla del HDU (suma <= 1) no admite tolerancia. Solo se corrige lo calculado a partir de
    montos; un factor ingresado directamente nunca se ajusta, se rechaza.
    """
    exceso = suma_distribucion(factores) - UNO
    while exceso > CERO:
        col = max(COLUMNAS_DISTRIBUCION, key=lambda c: factores[c] - exactos[c])
        factores[col] -= OCHO_DECIMALES
        exceso -= OCHO_DECIMALES
    return factores


def resolver_factores_editables(post_data, factores_calculados):
    """Lee factor_8 a factor_37 del POST; si un campo viene vacío usa el factor calculado.

    Lanza ValueError si algún factor no es un número o es negativo.
    """
    factores_finales = {}
    for col in COLUMNAS:
        calculado = redondear_8_decimales(
            parsear_decimal(factores_calculados.get(col), CERO) or CERO)
        crudo = post_data.get(f'factor_{col}')
        if crudo is None or str(crudo).strip() == '':
            factores_finales[col] = calculado
            continue
        editado = parsear_decimal(crudo, por_defecto=None)
        if editado is None:
            raise ValueError(f'Revise el factor {col}: debe ser un número válido.')
        if editado < CERO:
            raise ValueError(f'Revise el factor {col}: no puede ser menor que 0.')
        factores_finales[col] = redondear_8_decimales(editado)
    return factores_finales


def validar_suma_factores_8_a_19(factores):
    """True si la suma de los factores 8 a 19 es <= 1 (sin tolerancia). Devuelve (ok, suma)."""
    suma = suma_distribucion({c: parsear_decimal(v, CERO) or CERO for c, v in factores.items()})
    return suma <= UNO, suma