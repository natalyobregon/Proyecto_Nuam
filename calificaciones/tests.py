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
        datos = {'mercado': 'ACN', 'instrumento': 'COPEC', 'secuencia_evento': '10001',
                 'dividendo': '0', 'tipo_sociedad': 'A', 'fecha_pago': '2025-05-15', 'valor_historico': '0',
                 'ejercicio': '2025', 'descripcion': 'Prueba'}
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
            corredora=self.corredora, ejercicio=2025, mercado='ACN', instrumento='X',
            secuencia_evento=10001)
        FactorCalificacion(calificacion=cal, numero_columna=8, valor=D('0.9')).save()
        with self.assertRaises(Exception):
            FactorCalificacion(calificacion=cal, numero_columna=19, valor=D('0.2')).save()

    def test_caso_3_secuencia_invalida_no_graba_y_marca_el_campo(self):
        datos = {**self.datos_basicos(secuencia_evento='9999'), **self.montos_post(), 'accion': 'guardar'}
        r = self.client.post(reverse('ingresar'), datos)
        self.assertContains(r, 'debe ser mayor a 10.000')
        self.assertFalse(Calificacion.objects.exists())

    def test_secuencia_10001_es_valida_y_10000_no(self):
        for secuencia, graba in (('10000', False), ('10001', True)):
            datos = {**self.datos_basicos(secuencia_evento=secuencia), **self.montos_post(), 'accion': 'guardar'}
            self.client.post(reverse('ingresar'), datos)
            self.assertEqual(Calificacion.objects.filter(secuencia_evento=secuencia).exists(), graba)

    def test_el_ingreso_manual_siempre_es_local_aunque_el_navegador_diga_otra_cosa(self):
        datos = {**self.datos_basicos(origen='oficial_bolsa'), **self.montos_post(), 'accion': 'guardar'}
        self.client.post(reverse('ingresar'), datos)
        cal = Calificacion.objects.get()
        self.assertEqual(cal.origen, 'local_corredora')
        self.assertEqual(cal.fuente_ingreso, 'manual')
        self.assertEqual(cal.corredora, self.corredora)

    def test_el_formulario_no_ofrece_elegir_origen(self):
        self.assertNotContains(self.client.get(reverse('ingresar')), 'name="origen"')

    def test_el_administrador_no_puede_ingresar(self):
        admin = Usuario.objects.create_user('admin_x', password='Ventana123$',
                                            rol=Usuario.ROL_ADMIN, is_staff=True)
        self.client.force_login(admin)
        self.assertEqual(self.client.get(reverse('ingresar')).status_code, 403)

    def test_admin_de_django_muestra_calificaciones_solo_lectura(self):
        admin = Usuario.objects.create_user('admin_y', password='Ventana123$',
                                            rol=Usuario.ROL_ADMIN, is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        r = self.client.get('/admin/calificaciones/calificacion/add/')
        self.assertEqual(r.status_code, 403)


class Paso3BolsaYCamposTests(TestCase):
    """Bolsa visible para todas las corredoras, solo lectura, y el corredor prevalece."""

    @classmethod
    def setUpTestData(cls):
        cls.bolsa = Corredora.objects.create(nombre='Bolsa', rut='99.999.999-9', es_bolsa=True)
        cls.corr_a = Corredora.objects.create(nombre='A', rut='76.111.111-1')
        cls.corr_b = Corredora.objects.create(nombre='B', rut='76.222.222-2')
        cls.op_a = Usuario.objects.create_user('op_a', password='x', rol=Usuario.ROL_OPERADOR,
                                               corredora=cls.corr_a)
        cls.op_b = Usuario.objects.create_user('op_b', password='x', rol=Usuario.ROL_OPERADOR,
                                               corredora=cls.corr_b)

        def mk(corr, instr, origen):
            return Calificacion.objects.create(
                corredora=corr, ejercicio=2025, mercado='ACN', instrumento=instr,
                secuencia_evento=10001, origen=origen)
        cls.b_copec = mk(cls.bolsa, 'COPEC', 'oficial_bolsa')
        cls.b_sqm = mk(cls.bolsa, 'SQM-B', 'oficial_bolsa')
        cls.a_copec = mk(cls.corr_a, 'COPEC', 'local_corredora')

    def ids(self, usuario):
        from cuentas.alcance import calificaciones_visibles
        return set(calificaciones_visibles(usuario).values_list('pk', flat=True))

    def test_operador_ve_bolsa_y_lo_propio(self):
        self.assertIn(self.b_sqm.pk, self.ids(self.op_a))
        self.assertIn(self.b_sqm.pk, self.ids(self.op_b))

    def test_prevalece_la_calificacion_del_corredor(self):
        ids_a = self.ids(self.op_a)
        self.assertIn(self.a_copec.pk, ids_a)
        self.assertNotIn(self.b_copec.pk, ids_a)

    def test_otra_corredora_sigue_viendo_la_oficial_y_no_la_ajena(self):
        ids_b = self.ids(self.op_b)
        self.assertIn(self.b_copec.pk, ids_b)
        self.assertNotIn(self.a_copec.pk, ids_b)

    def test_bolsa_es_solo_lectura(self):
        from cuentas.alcance import es_editable_por
        self.assertFalse(es_editable_por(self.op_a, self.b_sqm))
        self.assertTrue(es_editable_por(self.op_a, self.a_copec))
        self.assertFalse(es_editable_por(self.op_b, self.a_copec))

    def test_grilla_no_ofrece_editar_sobre_bolsa(self):
        self.client.force_login(self.op_a)
        r = self.client.get(reverse('grilla'))
        filas = {f['obj'].pk: f['editable'] for f in r.context['filas']}
        self.assertFalse(filas[self.b_sqm.pk])
        self.assertTrue(filas[self.a_copec.pk])

    def test_ingreso_guarda_isfut_tipo_sociedad_y_numero_dividendo(self):
        self.client.force_login(self.op_a)
        datos = {'mercado': 'CFI', 'instrumento': 'CFIX', 'secuencia_evento': '10005',
                 'numero_dividendo': '3', 'dividendo': '0', 'tipo_sociedad': 'C', 'isfut': 'on',
                 'fecha_pago': '2025-05-15', 'valor_historico': '0', 'ejercicio': '2025',
                 'accion': 'guardar', **{f'monto_{c}': '0' if c != 8 else '100' for c in range(8, 38)}}
        r = self.client.post(reverse('ingresar'), datos)
        self.assertRedirects(r, reverse('grilla'))
        cal = Calificacion.objects.get(instrumento='CFIX')
        self.assertTrue(cal.isfut)
        self.assertEqual(cal.tipo_sociedad, 'C')


    def test_mercado_fuera_de_la_lista_se_rechaza(self):
        from calificaciones.forms import CalificacionBasicaForm
        f = CalificacionBasicaForm({'mercado': 'XYZ', 'instrumento': 'A', 'secuencia_evento': '10001',
                                    'dividendo': '0', 'tipo_sociedad': 'A', 'fecha_pago': '2025-05-15',
                                    'valor_historico': '0', 'ejercicio': '2025'})
        self.assertFalse(f.is_valid())
        self.assertIn('mercado', f.errors)