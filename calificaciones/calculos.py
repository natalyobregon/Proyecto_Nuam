from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

OCHO_DECIMALES = Decimal('0.00000001')
UNO = Decimal('1')
CERO = Decimal('0')

# Este archivo contiene funciones de cálculo de factores y validaciones de montos y factores
# que se usan en la vista de ingreso de calificaciones.


def parsear_decimal(valor, por_defecto=CERO):
    if valor is None or str(valor).strip() == '':
        return por_defecto
    try:
        texto = str(valor).strip().replace(',', '.')
        return Decimal(texto)
    except InvalidOperation:
        return None


def redondear_8_decimales(valor):
    return valor.quantize(OCHO_DECIMALES, rounding=ROUND_HALF_UP)


def calcular_factores_desde_montos(montos_por_col, divisor):
    """
    montos_por_col: dict {8: Decimal, 9: Decimal, ..., 36: Decimal}
    divisor: Decimal (ej. valor_historico o dividendo). Debe ser > 0.

    Devuelve un dict {8: Decimal, ..., 37: Decimal} con 8 decimales exactos.
    Lanza ValueError si el divisor es <= 0.
    """
    if divisor is None or divisor <= CERO:
        raise ValueError('El monto base/divisor debe ser mayor que cero para calcular los factores.')

    factores = {}
    for col in range(8, 37):
        monto = montos_por_col.get(col, CERO)
        factor = redondear_8_decimales(monto / divisor)
        factores[col] = factor

    # Columna 37: remanente o ajuste según corresponda (inicializado en 0.00000000 si no viene)
    factores[37] = redondear_8_decimales(CERO)
    return factores


def resolver_factores_editables(post_data, factores_calculados):
    """
    Lee los inputs factor_8 a factor_37 del POST si vienen informados;
    si están vacíos, conserva el factor calculado redondeado a 8 decimales.
    Lanza ValueError si algún factor es inválido o negativo.
    """
    factores_finales = {}
    for col in range(8, 38):
        calculado = redondear_8_decimales(
            parsear_decimal(factores_calculados.get(col), CERO) or CERO
        )
        raw_val = post_data.get(f'factor_{col}')
        if raw_val is None or str(raw_val).strip() == '':
            factores_finales[col] = calculado
            continue

        editado = parsear_decimal(raw_val, por_defecto=None)
        if editado is None:
            raise ValueError(f'Revise el factor {col}: debe ser un número válido.')
        if editado < CERO:
            raise ValueError(f'Revise el factor {col}: no puede ser menor que 0.')

        factores_finales[col] = redondear_8_decimales(editado)

    return factores_finales


def validar_suma_factores_8_a_16(factores):
    """Verifica que la suma de los factores de la columna 8 a la 16 sea <= 1."""
    suma = sum(
        (parsear_decimal(factores.get(col), CERO) or CERO)
        for col in range(8, 17)
    )
    return suma <= UNO, suma