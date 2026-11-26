"""Pruebas del cálculo de factores y del ingreso (HDU 02, 03 y 04).

Ejecutar:  python manage.py test calificaciones --settings=nuam.settings_test
"""
from decimal import Decimal as D

from django.test import TestCase
from django.urls import reverse

from calificaciones.calculos import (calcular_factores_desde_montos, redondear_8_decimales,
                                     suma_distribucion, validar_suma_factores_8_a_19)
from calificaciones.models import (Calificacion, Corredora, FactorCalificacion,
                                   MontoCalificacion, Usuario)

# Ejemplo del HDU (hoja «3.2 Homologacion columnas»)
MONTOS_HDU = {8: D('192770580'), 9: D('64161878'), 10: D('0'), 11: D('111812860'),
              25: D('71298705'), 30: D('15837333')}
FACTORES_HDU = {8: D('0.52277431'), 9: D('0.17400052'), 10: D('0.00000000'),
                11: D('0.30322517'), 25: D('0.19335488'), 30: D('0.04294924')}


class CalculoFactoresTests(TestCase):
    def test_ejemplo_del_hdu(self):
        """La «prueba de oro»: cada factor coincide con el del HDU, a 8 decimales."""
        factores = calcular_factores_desde_montos(MONTOS_HDU)
        for col, esperado in FACTORES_HDU.items():
            self.assertEqual(factores[col], esperado, f'columna {col}')

    def test_el_divisor_es_la_suma_de_montos_8_a_19(self):
        self.assertEqual(suma_distribucion(MONTOS_HDU), D('368745318'))

    def test_devuelve_los_30_factores_de_8_a_37(self):
        factores = calcular_factores_desde_montos(MONTOS_HDU)
        self.assertEqual(sorted(factores), list(range(8, 38)))

    def test_suma_8_a_19_del_ejemplo_no_supera_1(self):
        ok, suma = validar_suma_factores_8_a_19(calcular_factores_desde_montos(MONTOS_HDU))
        self.assertTrue(ok)
        self.assertLessEqual(suma, D('1'))

    def test_los_factores_son_decimal_con_8_decimales(self):
        for valor in calcular_factores_desde_montos(MONTOS_HDU).values():
            self.assertIsInstance(valor, D)
            self.assertEqual(valor, redondear_8_decimales(valor))

    def test_divisor_cero_se_rechaza(self):
        with self.assertRaises(ValueError):
            calcular_factores_desde_montos({25: D('1000')})   # solo columnas fuera de 8 a 19
        with self.assertRaises(ValueError):
            calcular_factores_desde_montos({})

    def test_suma_mayor_a_1_se_rechaza_sin_tolerancia(self):
        ok, suma = validar_suma_factores_8_a_19({8: D('0.60000000'), 9: D('0.50000000')})
        self.assertFalse(ok)
        self.assertEqual(suma, D('1.10000000'))
        ok, _ = validar_suma_factores_8_a_19({8: D('0.50000000'), 9: D('0.50000001')})
        self.assertFalse(ok)                                  # 1,00000001 no se acepta
        ok, _ = validar_suma_factores_8_a_19({8: D('0.50000000'), 9: D('0.50000000')})
        self.assertTrue(ok)

    def test_columnas_fuera_de_8_a_19_no_cuentan_en_la_suma(self):
        ok, _ = validar_suma_factores_8_a_19({8: D('1'), 25: D('0.9'), 30: D('0.9')})
        self.assertTrue(ok)


class IngresoManualTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.corredora = Corredora.objects.create(nombre='Corredora A', rut='76.111.111-1')
        cls.operador = Usuario.objects.create_user(
            'operador_a', password='Ventana123$', rol=Usuario.ROL_OPERADOR, corredora=cls.corredora)

    def setUp(self):
        self.client.force_login(self.operador)

    def datos_basicos(self, **extra):
        datos = {'mercado': 'ACCIONES', 'instrumento': 'COPEC', 'secuencia_evento': '10001',
                 'dividendo': '0', 'fecha_pago': '2025-05-15', 'valor_historico': '0',
                 'ejercicio': '2025', 'origen': 'local_corredora', 'descripcion': 'Prueba'}
        datos.update(extra)
        return datos

    def montos_post(self):
        datos = {f'monto_{col}': str(MONTOS_HDU.get(col, 0)) for col in range(8, 38)}
        return datos

    def test_caso_1_ejemplo_del_hdu_graba_con_los_factores_esperados(self):
        r = self.client.post(reverse('ingresar'),
                             {**self.datos_basicos(), **self.montos_post(), 'accion': 'guardar'})
        self.assertRedirects(r, reverse('grilla'))
        cal = Calificacion.objects.get(instrumento='COPEC')
        self.assertEqual(cal.montos.count(), 30)
        self.assertEqual(cal.factores.count(), 30)
        guardados = {f.numero_columna: f.valor for f in cal.factores.all()}
        for col, esperado in FACTORES_HDU.items():
            self.assertEqual(guardados[col], esperado)

    def test_caso_2_suma_mayor_a_1_no_graba_y_avisa_la_suma(self):
        datos = {**self.datos_basicos(), **self.montos_post(), 'accion': 'guardar',
                 'factor_8': '0.60000000', 'factor_9': '0.50000000', 'factor_11': '0'}
        r = self.client.post(reverse('ingresar'), datos)
        self.assertContains(r, '1.10000000')
        self.assertFalse(Calificacion.objects.exists())

    def test_los_factores_en_cero_se_muestran_como_0_00000000(self):
        datos = {**self.datos_basicos(), **self.montos_post(), 'accion': 'calcular'}
        r = self.client.post(reverse('ingresar'), datos)
        self.assertNotContains(r, '0E-8')
        self.assertContains(r, 'value="0.00000000"')

    def test_calcular_con_suma_de_montos_cero_avisa_y_no_graba(self):
        datos = {**self.datos_basicos(), 'accion': 'guardar',
                 **{f'monto_{col}': '0' for col in range(8, 38)}}
        r = self.client.post(reverse('ingresar'), datos)
        self.assertContains(r, 'columnas 8 a 19 es 0')
        self.assertFalse(Calificacion.objects.exists())

    def test_modelo_rechaza_factor_que_pasa_la_suma_8_a_19(self):
        cal = Calificacion.objects.create(
            corredora=self.corredora, ejercicio=2025, mercado='ACCIONES', instrumento='X',
            secuencia_evento=10001)
        FactorCalificacion(calificacion=cal, numero_columna=8, valor=D('0.9')).save()
        with self.assertRaises(Exception):
            FactorCalificacion(calificacion=cal, numero_columna=19, valor=D('0.2')).save()