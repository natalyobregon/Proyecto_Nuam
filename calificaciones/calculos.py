from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

OCHO_DECIMALES = Decimal('0.00000001')
UNO = Decimal('1')
CERO = Decimal('0')

#este archvivo contiene funciones de calculo de factores y validaciones de montos y factores que se usan n la vista de ingreso de calificaciones


def parsear_decimal(valor, por_defecto=CERO):
    if valor is None or str(valor).strip() == '':
        return por_defecto
    try:
        texto = str(valor).strip().replace(',', '.')
        return Decimal(texto)
    except InvalidOperation:
        return None


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
        factor = (monto / divisor).quantize(OCHO_DECIMALES, rounding=ROUND_HALF_UP)
        factores[col] = factor

    # Columna 37: remanente o ajuste según corresponda (inicializado en 0.00000000 si no viene)
    factores[37] = CERO.quantize(OCHO_DECIMALES, rounding=ROUND_HALF_UP)
    return factores


def validar_suma_factores_8_a_16(factores):
    """Verifica que la suma de los factores de la columna 8 a la 16 sea <= 1."""
    suma = sum(
        (parsear_decimal(factores.get(col), CERO) or CERO)
        for col in range(8, 17)
    )
    return suma <= UNO, suma