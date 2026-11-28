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
        from cuentas.alcance import calificaciones_visibles, es_editable_por  # noqa
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
        self.assertEqual(cal.numero_dividendo, 3)

    def test_mercado_fuera_de_la_lista_se_rechaza(self):
        from calificaciones.forms import CalificacionBasicaForm
        f = CalificacionBasicaForm({'mercado': 'XYZ', 'instrumento': 'A', 'secuencia_evento': '10001',
                                    'dividendo': '0', 'tipo_sociedad': 'A', 'fecha_pago': '2025-05-15',
                                    'valor_historico': '0', 'ejercicio': '2025'})
        self.assertFalse(f.is_valid())
        self.assertIn('mercado', f.errors)



class Paso4ModificarEliminarTests(TestCase):
    """HDU 05: el corredor modifica y elimina (lógico) solo lo suyo; todo queda en la bitácora."""

    @classmethod
    def setUpTestData(cls):
        cls.bolsa = Corredora.objects.create(nombre='Bolsa', rut='99.999.999-9', es_bolsa=True)
        cls.corr_a = Corredora.objects.create(nombre='A', rut='76.111.111-1')
        cls.corr_b = Corredora.objects.create(nombre='B', rut='76.222.222-2')
        cls.op_a = Usuario.objects.create_user('op_a', password='x', rol=Usuario.ROL_OPERADOR,
                                               corredora=cls.corr_a)
        cls.op_b = Usuario.objects.create_user('op_b', password='x', rol=Usuario.ROL_OPERADOR,
                                               corredora=cls.corr_b)
        cls.admin = Usuario.objects.create_user('adm', password='x', rol=Usuario.ROL_ADMIN, is_staff=True)

    def crear(self, corredora=None, origen='local_corredora', instrumento='COPEC'):
        cal = Calificacion.objects.create(
            corredora=corredora or self.corr_a, ejercicio=2025, mercado='ACN', instrumento=instrumento,
            secuencia_evento=10001, origen=origen, tipo_sociedad='A')
        for col in range(8, 38):
            MontoCalificacion.objects.create(calificacion=cal, numero_columna=col,
                                             valor=D('100') if col == 8 else D('0'))
            FactorCalificacion.objects.create(calificacion=cal, numero_columna=col,
                                              valor=D('1') if col == 8 else D('0'))
        return cal

    def post_edicion(self, cal, **cambios):
        datos = {'mercado': 'ACN', 'instrumento': cal.instrumento, 'secuencia_evento': '10001',
                 'dividendo': '0', 'tipo_sociedad': 'A', 'fecha_pago': '2025-05-15',
                 'valor_historico': '0', 'ejercicio': '2025', 'descripcion': '', 'accion': 'guardar',
                 **{f'monto_{c}': '100' if c == 8 else '0' for c in range(8, 38)},
                 **{f'factor_{c}': '1.00000000' if c == 8 else '0.00000000' for c in range(8, 38)}}
        datos.update(cambios)
        return datos

    def test_modificar_descripcion_guarda_y_registra_antes_y_despues(self):
        from calificaciones.models import RegistroAuditoria
        cal = self.crear()
        self.client.force_login(self.op_a)
        r = self.client.post(reverse('editar', args=[cal.pk]),
                             self.post_edicion(cal, descripcion='Nueva descripcion'))
        self.assertRedirects(r, reverse('grilla'))
        cal.refresh_from_db()
        self.assertEqual(cal.descripcion, 'Nueva descripcion')
        log = RegistroAuditoria.objects.get(accion='modificar')
        self.assertEqual(log.usuario, self.op_a)
        self.assertEqual(log.id_calificacion, cal.pk)
        self.assertEqual(log.detalle['corredora_id'], self.corr_a.pk)
        self.assertEqual(log.detalle['cambios']['descripcion'], {'antes': '', 'despues': 'Nueva descripcion'})
        self.assertNotIn('instrumento', log.detalle['cambios'])      # solo lo que cambió

    def test_modificar_montos_exige_recalcular_factores(self):
        cal = self.crear()
        self.client.force_login(self.op_a)
        datos = self.post_edicion(cal, monto_8='50', monto_9='50')
        r = self.client.post(reverse('editar', args=[cal.pk]), datos)
        self.assertContains(r, 'Calcular factores')
        cal.refresh_from_db()
        self.assertEqual(cal.montos.get(numero_columna=8).valor, D('100'))   # no se grabó

    def test_modificar_con_factores_recalculados_graba(self):
        cal = self.crear()
        self.client.force_login(self.op_a)
        datos = self.post_edicion(cal, monto_8='50', monto_9='50', factor_8='0.50000000', factor_9='0.50000000')
        self.client.post(reverse('editar', args=[cal.pk]), datos)
        self.assertEqual(cal.factores.get(numero_columna=9).valor, D('0.5'))
        self.assertEqual(cal.montos.get(numero_columna=9).valor, D('50'))

    def test_modificar_suma_mayor_a_1_no_graba(self):
        cal = self.crear()
        self.client.force_login(self.op_a)
        datos = self.post_edicion(cal, factor_9='0.50000000')
        r = self.client.post(reverse('editar', args=[cal.pk]), datos)
        self.assertContains(r, 'supera 1')
        self.assertEqual(cal.factores.get(numero_columna=9).valor, D('0'))

    def test_no_se_puede_modificar_lo_de_otra_corredora_ni_la_bolsa(self):
        ajena = self.crear(self.corr_b, instrumento='AJENA')
        oficial = self.crear(self.bolsa, origen='oficial_bolsa', instrumento='OFICIAL')
        self.client.force_login(self.op_a)
        for cal in (ajena, oficial):
            self.assertEqual(self.client.get(reverse('editar', args=[cal.pk])).status_code, 403)
            r = self.client.post(reverse('editar', args=[cal.pk]), self.post_edicion(cal, descripcion='X'))
            self.assertEqual(r.status_code, 403)
            cal.refresh_from_db()
            self.assertEqual(cal.descripcion, '')

    def test_administrador_no_modifica_ni_elimina(self):
        cal = self.crear()
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('editar', args=[cal.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('eliminar', args=[cal.pk])).status_code, 403)
        cal.refresh_from_db()
        self.assertFalse(cal.eliminado)

    def test_eliminar_get_pide_confirmacion_y_no_elimina(self):
        cal = self.crear()
        self.client.force_login(self.op_a)
        r = self.client.get(reverse('eliminar', args=[cal.pk]))
        self.assertContains(r, '¿Está seguro')
        cal.refresh_from_db()
        self.assertFalse(cal.eliminado)

    def test_eliminar_post_es_logico_desaparece_de_la_grilla_y_se_registra(self):
        from calificaciones.models import RegistroAuditoria
        cal = self.crear()
        self.client.force_login(self.op_a)
        self.client.post(reverse('eliminar', args=[cal.pk]))
        cal.refresh_from_db()
        self.assertTrue(cal.eliminado)                          # sigue en la base
        self.assertEqual(Calificacion.objects.filter(pk=cal.pk).count(), 1)
        r = self.client.get(reverse('grilla'))
        self.assertNotIn(cal.pk, [f['obj'].pk for f in r.context['filas']])
        self.assertEqual(self.client.get(reverse('detalle', args=[cal.pk])).status_code, 404)
        log = RegistroAuditoria.objects.get(accion='eliminar')
        self.assertEqual(log.detalle['antes']['instrumento'], 'COPEC')
        self.assertEqual(log.detalle['corredora_id'], self.corr_a.pk)

    def test_no_se_elimina_lo_ajeno_ni_lo_oficial(self):
        ajena = self.crear(self.corr_b, instrumento='AJENA')
        oficial = self.crear(self.bolsa, origen='oficial_bolsa', instrumento='OFICIAL')
        self.client.force_login(self.op_a)
        for cal in (ajena, oficial):
            self.assertEqual(self.client.post(reverse('eliminar', args=[cal.pk])).status_code, 403)
            cal.refresh_from_db()
            self.assertFalse(cal.eliminado)

    def test_reingresar_una_eliminada_la_reactiva_sin_chocar_con_la_llave(self):
        cal = self.crear()
        self.client.force_login(self.op_a)
        self.client.post(reverse('eliminar', args=[cal.pk]))
        datos = {**self.post_edicion(cal), 'descripcion': 'De nuevo'}
        for c in range(8, 38):
            datos.pop(f'factor_{c}')
        r = self.client.post(reverse('ingresar'), datos)
        self.assertRedirects(r, reverse('grilla'))
        self.assertEqual(Calificacion.objects.filter(instrumento='COPEC').count(), 1)
        cal.refresh_from_db()
        self.assertFalse(cal.eliminado)
        self.assertEqual(cal.descripcion, 'De nuevo')

    def test_el_ingreso_registra_despues_y_corredora(self):
        from calificaciones.models import RegistroAuditoria
        self.client.force_login(self.op_a)
        datos = self.post_edicion(Calificacion(instrumento='NUEVA'))
        for c in range(8, 38):
            datos.pop(f'factor_{c}')
        self.client.post(reverse('ingresar'), datos)
        log = RegistroAuditoria.objects.get(accion='crear')
        self.assertEqual(log.detalle['corredora_id'], self.corr_a.pk)
        self.assertEqual(log.detalle['despues']['instrumento'], 'NUEVA')

    def test_grilla_muestra_editar_y_eliminar_solo_en_filas_propias(self):
        propia = self.crear()
        oficial = self.crear(self.bolsa, origen='oficial_bolsa', instrumento='OFICIAL')
        self.client.force_login(self.op_a)
        html = self.client.get(reverse('grilla')).content.decode()
        self.assertIn(reverse('editar', args=[propia.pk]), html)
        self.assertIn(reverse('eliminar', args=[propia.pk]), html)
        self.assertNotIn(reverse('editar', args=[oficial.pk]), html)
        self.assertNotIn(reverse('eliminar', args=[oficial.pk]), html)


    def test_admin_nuam_ve_la_bitacora_en_el_admin_de_django_pero_no_la_modifica(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/admin/calificaciones/registroauditoria/').status_code, 200)
        self.assertEqual(self.client.get('/admin/calificaciones/registroauditoria/add/').status_code, 403)

    def test_operador_no_ve_la_bitacora(self):
        self.client.force_login(self.op_a)
        self.assertNotEqual(self.client.get('/admin/calificaciones/registroauditoria/').status_code, 200)



import hashlib
import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from calificaciones import cargas
from calificaciones.calculos import calcular_factores_desde_montos as calc
from calificaciones.models import CargaMasiva, RegistroAuditoria

_TMP_CARGAS = tempfile.mkdtemp(prefix='cargas_test_')
FIXTURES = Path(__file__).resolve().parent / 'fixtures_csv'
ENCABEZADO = ';'.join(cargas.ENCABEZADO_BASICO + [f'c{c}' for c in range(8, 38)])


def fila_csv(tipo='MONTOS', **cambios):
    """Fila válida (ejemplo del HDU). Ajustes: tipo=, ejercicio=, mercado=, instrumento=, fecha=,
    secuencia=, ndiv=, historico=, descripcion=, o c8=..c37=."""
    base = cargas.plantilla_csv().splitlines()[1 if tipo == 'MONTOS' else 2].split(';')
    nombres = ['tipo', 'ejercicio', 'mercado', 'instrumento', 'fecha', 'secuencia', 'ndiv', 'historico', 'descripcion']
    base[0] = tipo
    for clave, valor in cambios.items():
        if clave.startswith('c') and clave[1:].isdigit():
            base[cargas.N_BASICAS + int(clave[1:]) - 8] = str(valor)
        else:
            base[nombres.index(clave)] = str(valor)
    return ';'.join(base)


def csv_bytes(*filas, encabezado=True):
    return ('\n'.join(([ENCABEZADO] if encabezado else []) + list(filas)) + '\n').encode('utf-8')


def errores_por_fila(resultado):
    por = {}
    for e in resultado['errores']:
        por.setdefault(e['fila'], set()).add(e['columna'])
    return por


class AjusteRedondeoTests(TestCase):
    def test_montos_que_redondeados_suman_1_00000001_se_ajustan_a_1(self):
        # Fila real del archivo del docente (VINA-VALLE, secuencia 10006).
        montos = {12: D(126616000), 14: D(148849000), 16: D(243806000), 19: D(135466000)}
        factores = calc(montos)
        ok, suma = validar_suma_factores_8_a_19(factores)
        self.assertTrue(ok)
        self.assertEqual(suma, D('1.00000000'))
        self.assertEqual(factores[14], D('0.22734166'))     # el que más se había subido al redondear

    def test_el_ajuste_no_toca_el_ejemplo_del_hdu(self):
        factores = calc(MONTOS_HDU)
        for col, esperado in FACTORES_HDU.items():
            self.assertEqual(factores[col], esperado)

    def test_suma_menor_a_1_por_redondeo_no_se_ajusta(self):
        montos = {8: D(76298000), 11: D(30028000), 15: D(22161000), 17: D(162009000)}   # fila 4 del archivo
        ok, suma = validar_suma_factores_8_a_19(calc(montos))
        self.assertTrue(ok)
        self.assertEqual(suma, D('0.99999999'))


class FormatoDocenteTests(TestCase):
    """Los dos archivos que entregó el profe son el criterio de aceptación de la carga masiva."""

    def validar(self, nombre):
        return cargas.validar_archivo((FIXTURES / nombre).read_bytes())

    def test_archivo_de_prueba_20_filas_validas_y_13_con_el_error_esperado(self):
        r = self.validar('carga_masiva_prueba_nuam.csv')
        self.assertEqual(r['total'], 33)
        self.assertEqual([f['fila'] for f in r['filas']], list(range(2, 22)))
        self.assertEqual(errores_por_fila(r), {
            22: {'descripcion'},                  # =HYPERLINK(...)
            23: {'secuencia'},                    # 9999
            24: {'c8..c19'},                      # montos solo fuera de 8 a 19: sin divisor
            25: {'c9'},                           # monto negativo
            26: {'c11'},                          # «N/A»
            27: {'instrumento'},                  # vacío
            28: {'fecha_pago'},                   # 31-02-2025
            29: {'mercado'},                      # BONOS
            30: {'c8..c19'},                      # factores suman 1,05
            31: {'c9'},                           # 9 decimales
            32: {'(llave)'},                      # repite la fila 6
            33: {'(fila)'},                       # 21 columnas
            34: {'fecha_pago'},                   # 15-13-2025
        })

    def test_archivo_de_errores_cada_fila_mala_falla_en_su_columna(self):
        r = self.validar('carga_masiva_errores_nuam.csv')
        self.assertEqual(r['total'], 38)
        self.assertEqual(errores_por_fila(r), {
            6: {'tipo_carga'}, 7: {'ejercicio'}, 8: {'ejercicio'}, 10: {'mercado'},
            13: {'fecha_pago'}, 14: {'fecha_pago'}, 15: {'fecha_pago'},
            16: {'secuencia'}, 17: {'secuencia'}, 18: {'secuencia'},
            20: {'numero_dividendo'}, 21: {'valor_historico'}, 22: {'valor_historico'},
            24: {'descripcion'}, 25: {'descripcion'}, 26: {'descripcion'},
            28: {'c11'}, 29: {'c15'}, 30: {'c8..c19'},
            32: {'c20'}, 33: {'c9'}, 34: {'c8..c19'}, 35: {'c9'},
            37: {'(llave)'}, 38: {'(fila)'}, 39: {'(fila)'},
        })

    def test_archivo_de_errores_filas_que_si_se_aceptan(self):
        """Decisiones de formato (a confirmar con el docente): tipo y mercado sin distinguir
        mayúsculas, FM como mercado, dividendo 0, descripción vacía, decimales con coma o punto."""
        r = self.validar('carga_masiva_errores_nuam.csv')
        self.assertEqual([f['fila'] for f in r['filas']], [2, 3, 4, 5, 9, 11, 12, 19, 23, 27, 31, 36])

    def test_los_dos_archivos_traen_bom_y_crlf_y_se_leen(self):
        for nombre in ('carga_masiva_prueba_nuam.csv', 'carga_masiva_errores_nuam.csv'):
            crudo = (FIXTURES / nombre).read_bytes()
            self.assertTrue(crudo.startswith(b'\xef\xbb\xbf'))
            self.assertIn(b'\r\n', crudo)

    def test_el_ejemplo_del_hdu_del_archivo_de_prueba_da_los_factores_del_hdu(self):
        r = self.validar('carga_masiva_prueba_nuam.csv')
        hdu = next(f for f in r['filas'] if f['instrumento'] == 'EMPRESA-HDU')
        for col, esperado in FACTORES_HDU.items():
            self.assertEqual(hdu['factores'][col], esperado)
        self.assertEqual(hdu['valor_historico'], D('48.50'))
        self.assertEqual(hdu['numero_dividendo'], 290)

    def test_descripcion_con_tildes_y_enie_se_conserva(self):
        r = self.validar('carga_masiva_prueba_nuam.csv')
        fila = next(f for f in r['filas'] if f['secuencia_evento'] == 10018)
        self.assertIn('tildes y ñ', fila['descripcion'])
        self.assertIn('–', fila['descripcion'])


@override_settings(CARGAS_ROOT=_TMP_CARGAS)
class Paso5CargaMasivaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.corr_a = Corredora.objects.create(nombre='A', rut='76.111.111-1')
        cls.corr_b = Corredora.objects.create(nombre='B', rut='76.222.222-2')
        cls.op_a = Usuario.objects.create_user('op_a', password='x', rol=Usuario.ROL_OPERADOR,
                                               corredora=cls.corr_a)
        cls.op_b = Usuario.objects.create_user('op_b', password='x', rol=Usuario.ROL_OPERADOR,
                                               corredora=cls.corr_b)
        cls.admin = Usuario.objects.create_user('adm', password='x', rol=Usuario.ROL_ADMIN, is_staff=True)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TMP_CARGAS, ignore_errors=True)

    def setUp(self):
        self.client.force_login(self.op_a)

    def subir_bytes(self, contenido, nombre='carga.csv'):
        return self.client.post(reverse('carga_masiva'), {
            'archivo': SimpleUploadedFile(nombre, contenido, content_type='text/csv')})

    def subir(self, *filas, nombre='carga.csv'):
        contenido = csv_bytes(*filas)
        return self.subir_bytes(contenido, nombre), contenido

    def cargar_y_confirmar(self, *filas):
        self.subir(*filas)
        carga = CargaMasiva.objects.latest('id_carga')
        self.client.post(reverse('carga_confirmar', args=[carga.pk]))
        carga.refresh_from_db()
        return carga

    # ---- flujo feliz
    def test_subir_valido_deja_pendiente_y_no_graba_hasta_confirmar(self):
        r, contenido = self.subir(fila_csv())
        carga = CargaMasiva.objects.get()
        self.assertRedirects(r, reverse('carga_detalle', args=[carga.pk]))
        self.assertEqual(carga.estado, 'pendiente')
        self.assertEqual(carga.tipo, 'montos')
        self.assertEqual(carga.hash_sha256, hashlib.sha256(contenido).hexdigest())
        self.assertFalse(Calificacion.objects.exists())
        self.assertContains(self.client.get(reverse('carga_detalle', args=[carga.pk])), 'Confirmar carga')

    def test_confirmar_crea_con_fuente_archivo_origen_local_y_factores_del_hdu(self):
        carga = self.cargar_y_confirmar(fila_csv())
        self.assertEqual(carga.estado, 'completada')
        cal = Calificacion.objects.get()
        self.assertEqual((cal.fuente_ingreso, cal.origen, cal.corredora), ('archivo', 'local_corredora', self.corr_a))
        self.assertEqual(cal.carga, carga)
        self.assertEqual(cal.factores.count(), 30)
        self.assertEqual(cal.montos.count(), 30)
        self.assertEqual(cal.factores.get(numero_columna=8).valor, D('0.52277431'))
        self.assertEqual(cal.numero_dividendo, 290)
        self.assertEqual(cal.valor_historico, D('48.50'))
        self.assertEqual(cal.descripcion, 'Ejemplo del HDU (montos)')

    def test_un_archivo_puede_mezclar_montos_y_factores(self):
        carga = self.cargar_y_confirmar(fila_csv('MONTOS'), fila_csv('FACTORES'))
        self.assertEqual(carga.tipo, 'mixto')
        self.assertEqual(Calificacion.objects.count(), 2)
        directa = Calificacion.objects.get(instrumento='EMPRESA-HDU-F')
        self.assertEqual(directa.factores.get(numero_columna=8).valor, D('0.52277431'))
        self.assertTrue(all(m.valor == 0 for m in directa.montos.all()))    # no se informaron montos

    def test_el_csv_original_se_guarda_y_verifica_su_huella(self):
        r, contenido = self.subir(fila_csv())
        self.assertEqual(cargas.leer_original(CargaMasiva.objects.get()), contenido)

    def test_la_plantilla_descargable_es_cargable(self):
        plantilla = self.client.get(reverse('carga_plantilla')).content
        r = cargas.validar_archivo(plantilla)
        self.assertEqual(r['errores'], [])
        self.assertEqual(len(r['filas']), 2)

    def test_sube_y_confirma_el_archivo_de_prueba_del_docente_no_carga_nada_por_sus_errores(self):
        self.subir_bytes((FIXTURES / 'carga_masiva_prueba_nuam.csv').read_bytes(), 'prueba.csv')
        carga = CargaMasiva.objects.get()
        self.assertEqual(carga.estado, 'con_errores')
        self.assertEqual((carga.total_registros, carga.registros_ok, carga.registros_error), (33, 20, 13))
        self.client.post(reverse('carga_confirmar', args=[carga.pk]))
        self.assertFalse(Calificacion.objects.exists())                  # todo o nada

    def test_las_20_filas_buenas_del_archivo_de_prueba_se_cargan_si_se_corrigen_las_malas(self):
        lineas = (FIXTURES / 'carga_masiva_prueba_nuam.csv').read_text(encoding='utf-8-sig').splitlines()
        carga = self.cargar_y_confirmar(*lineas[1:21])
        self.assertEqual(carga.estado, 'completada')
        self.assertEqual(Calificacion.objects.count(), 20)
        self.assertEqual(carga.detalle_errores, {'creadas': 20, 'actualizadas': 0})
        for cal in Calificacion.objects.filter(factores__numero_columna__lte=19).distinct():
            suma = sum(f.valor for f in cal.factores.filter(numero_columna__lte=19))
            self.assertLessEqual(suma, 1, cal.instrumento)

    def test_modo_solo_validas_con_el_archivo_de_prueba_carga_20_y_reporta_13(self):
        self.subir_bytes((FIXTURES / 'carga_masiva_prueba_nuam.csv').read_bytes(), 'prueba.csv')
        carga = CargaMasiva.objects.get()
        self.assertEqual(carga.estado, 'con_errores')
        self.assertContains(self.client.get(reverse('carga_detalle', args=[carga.pk])), 'Cargar solo las 20 filas válidas')
        self.client.post(reverse('carga_confirmar', args=[carga.pk]), {'modo': 'validas'})
        carga.refresh_from_db()
        self.assertEqual(carga.estado, 'parcial')
        self.assertEqual((carga.total_registros, carga.registros_ok, carga.registros_error), (33, 20, 13))
        self.assertEqual(Calificacion.objects.count(), 20)
        self.assertEqual(carga.detalle_errores['creadas'], 20)
        self.assertEqual(len({e['fila'] for e in carga.detalle_errores['errores']}), 13)
        self.assertFalse(Calificacion.objects.filter(instrumento='BANCO-ANDINO', secuencia_evento=10021).exists())
        r = self.client.get(reverse('carga_detalle', args=[carga.pk]))
        self.assertContains(r, 'no se cargaron')
        self.assertNotContains(r, 'Cargar solo las')                  # ya no se puede repetir

    def test_modo_solo_validas_con_el_archivo_de_errores_carga_12(self):
        self.subir_bytes((FIXTURES / 'carga_masiva_errores_nuam.csv').read_bytes(), 'errores.csv')
        carga = CargaMasiva.objects.get()
        self.client.post(reverse('carga_confirmar', args=[carga.pk]), {'modo': 'validas'})
        carga.refresh_from_db()
        self.assertEqual((carga.estado, carga.registros_ok, carga.registros_error), ('parcial', 12, 26))
        self.assertEqual(Calificacion.objects.count(), 12)

    def test_modo_solo_validas_no_se_puede_dos_veces_ni_sin_filas_validas(self):
        self.subir(fila_csv(), fila_csv(secuencia=5, instrumento='MALA'))
        carga = CargaMasiva.objects.get()
        for _ in range(2):
            self.client.post(reverse('carga_confirmar', args=[carga.pk]), {'modo': 'validas'})
        self.assertEqual(Calificacion.objects.count(), 1)
        self.assertEqual(RegistroAuditoria.objects.filter(accion='carga', id_calificacion__isnull=True).count(), 1)
        self.subir(fila_csv(secuencia=5))
        otra = CargaMasiva.objects.latest('id_carga')
        self.client.post(reverse('carga_confirmar', args=[otra.pk]), {'modo': 'validas'})
        otra.refresh_from_db()
        self.assertEqual(otra.estado, 'con_errores')

    def test_la_bitacora_resume_las_filas_omitidas(self):
        self.subir(fila_csv(), fila_csv(secuencia=5, instrumento='MALA'))
        carga = CargaMasiva.objects.get()
        self.client.post(reverse('carga_confirmar', args=[carga.pk]), {'modo': 'validas'})
        resumen = RegistroAuditoria.objects.get(accion='carga', id_calificacion__isnull=True)
        self.assertEqual(resumen.detalle['filas_omitidas_por_error'], 1)

    # ---- errores y todo-o-nada
    def test_una_fila_mala_bloquea_toda_la_carga(self):
        self.subir(fila_csv(), fila_csv(instrumento='SQM-B', secuencia=5))
        carga = CargaMasiva.objects.get()
        self.assertEqual(carga.estado, 'con_errores')
        self.assertEqual(carga.registros_error, 1)
        self.assertEqual(carga.detalle_errores[0]['fila'], 3)
        self.assertEqual(carga.detalle_errores[0]['columna'], 'secuencia')
        self.client.post(reverse('carga_confirmar', args=[carga.pk]))
        self.assertFalse(Calificacion.objects.exists())
        self.assertContains(self.client.get(reverse('carga_detalle', args=[carga.pk])), 'No se cargó ningún registro')

    def test_reporta_todos_los_errores_de_una_fila(self):
        r = cargas.validar_archivo(csv_bytes(fila_csv(ejercicio=1800, mercado='XXX', fecha='31-02-2025', tipo='OTRO')))
        self.assertEqual({e['columna'] for e in r['errores']}, {'tipo_carga', 'ejercicio', 'mercado', 'fecha_pago'})

    def test_factores_directos_nunca_se_ajustan_se_rechazan(self):
        r = cargas.validar_archivo(csv_bytes(fila_csv('FACTORES', c8='0,5', c9='0,3', c11='0,20000001', c25=0, c30=0)))
        self.assertEqual(r['errores'][0]['columna'], 'c8..c19')
        self.assertIn('1.00000001', r['errores'][0]['error'])

    def test_celda_vacia_decimales_de_mas_y_separador_de_miles(self):
        r = cargas.validar_archivo(csv_bytes(
            fila_csv(c10=''), fila_csv(secuencia=10002, c11='1.200.000'),
            fila_csv('FACTORES', secuencia=10003, c8='0,500000001', c9='0,5', c11=0, c25=0, c30=0)))
        self.assertEqual(errores_por_fila(r), {2: {'c10'}, 3: {'c11'}, 4: {'c8'}})

    def test_columnas_de_mas_y_de_menos(self):
        r = cargas.validar_archivo(csv_bytes(fila_csv() + ';1', ';'.join(fila_csv().split(';')[:-1])))
        self.assertTrue(all(e['columna'] == '(fila)' for e in r['errores']))
        self.assertEqual({e['fila'] for e in r['errores']}, {2, 3})

    def test_texto_peligroso_en_instrumento_y_descripcion_se_rechaza(self):
        for malo in ('=CMD()', '+1', '@SUM(A1)', '-2+3'):
            r = cargas.validar_archivo(csv_bytes(fila_csv(instrumento=malo)))
            self.assertEqual(r['errores'][0]['columna'], 'instrumento', malo)
            r = cargas.validar_archivo(csv_bytes(fila_csv(descripcion=malo)))
            self.assertEqual(r['errores'][0]['columna'], 'descripcion', malo)

    def test_limites_de_tamano_filas_y_formato(self):
        for malo in (b'', b'a' * (cargas.MAX_BYTES + 1), b'\x00\x01\x02'):
            with self.assertRaises(cargas.ArchivoInvalido):
                cargas.validar_archivo(malo)
        filas = [fila_csv(secuencia=10001 + i) for i in range(cargas.MAX_FILAS + 1)]
        with self.assertRaises(cargas.ArchivoInvalido):
            cargas.validar_archivo(csv_bytes(*filas))

    def test_extension_distinta_de_csv_se_rechaza(self):
        r, _ = self.subir(fila_csv(), nombre='datos.xlsx')
        self.assertContains(r, 'debe ser un .csv')
        self.assertFalse(CargaMasiva.objects.exists())

    # ---- upsert
    def test_cargar_de_nuevo_actualiza_sin_duplicar(self):
        self.cargar_y_confirmar(fila_csv())
        carga2 = self.cargar_y_confirmar(fila_csv('FACTORES', instrumento='EMPRESA-HDU', secuencia=10001,
                                                  c8='0,4', c9='0,3', c11='0,3', c25=0, c30=0, historico='500',
                                                  descripcion='Corregida'))
        self.assertEqual(Calificacion.objects.count(), 1)
        cal = Calificacion.objects.get()
        self.assertEqual(cal.factores.get(numero_columna=8).valor, D('0.4'))
        self.assertEqual(cal.montos.get(numero_columna=8).valor, D('192770580'))   # fila FACTORES no pisa montos
        self.assertEqual((cal.valor_historico, cal.descripcion), (D('500'), 'Corregida'))
        self.assertEqual(cal.carga, carga2)
        self.assertEqual(carga2.detalle_errores, {'creadas': 0, 'actualizadas': 1})
        log = RegistroAuditoria.objects.filter(accion='carga', id_calificacion=cal.pk).latest('id_registro')
        self.assertEqual(log.detalle['operacion'], 'actualizar')
        self.assertEqual(log.detalle['cambios']['factor_8'], {'antes': '0.52277431', 'despues': '0.40000000'})
        self.assertNotIn('monto_8', log.detalle['cambios'])

    def test_una_carga_reactiva_una_calificacion_eliminada(self):
        self.cargar_y_confirmar(fila_csv())
        cal = Calificacion.objects.get()
        self.client.post(reverse('eliminar', args=[cal.pk]))
        self.cargar_y_confirmar(fila_csv())
        cal.refresh_from_db()
        self.assertFalse(cal.eliminado)
        self.assertEqual(Calificacion.objects.count(), 1)

    def test_la_carga_nunca_toca_la_bolsa_ni_otra_corredora(self):
        bolsa = Corredora.objects.create(nombre='Bolsa', rut='99.999.999-9', es_bolsa=True)
        llave = dict(ejercicio=2025, mercado='ACN', instrumento='EMPRESA-HDU', secuencia_evento=10001)
        oficial = Calificacion.objects.create(corredora=bolsa, origen='oficial_bolsa', valor_historico=D('7'), **llave)
        ajena = Calificacion.objects.create(corredora=self.corr_b, valor_historico=D('9'), **llave)
        self.cargar_y_confirmar(fila_csv(historico='123'))
        oficial.refresh_from_db(); ajena.refresh_from_db()
        self.assertEqual((oficial.valor_historico, ajena.valor_historico), (D('7'), D('9')))
        self.assertEqual(Calificacion.objects.filter(corredora=self.corr_a).count(), 1)

    # ---- bitácora
    def test_la_carga_queda_en_la_bitacora_con_hash_y_corredora(self):
        self.cargar_y_confirmar(fila_csv())
        resumen = RegistroAuditoria.objects.filter(accion='carga', id_calificacion__isnull=True).get()
        self.assertEqual(resumen.usuario, self.op_a)
        self.assertEqual(resumen.detalle['creadas'], 1)
        self.assertEqual(resumen.detalle['corredora_id'], self.corr_a.pk)
        self.assertEqual(len(resumen.detalle['sha256']), 64)
        fila = RegistroAuditoria.objects.filter(accion='carga', id_calificacion__isnull=False).get()
        self.assertEqual(fila.detalle['operacion'], 'crear')

    # ---- seguridad
    def test_confirmar_exige_post_y_no_se_puede_dos_veces(self):
        self.subir(fila_csv())
        carga = CargaMasiva.objects.get()
        self.client.get(reverse('carga_confirmar', args=[carga.pk]))
        self.assertFalse(Calificacion.objects.exists())
        self.client.post(reverse('carga_confirmar', args=[carga.pk]))
        self.client.post(reverse('carga_confirmar', args=[carga.pk]))
        self.assertEqual(Calificacion.objects.count(), 1)
        self.assertEqual(RegistroAuditoria.objects.filter(accion='carga', id_calificacion__isnull=True).count(), 1)

    def test_archivo_alterado_en_disco_no_se_carga(self):
        self.subir(fila_csv())
        carga = CargaMasiva.objects.get()
        (cargas.raiz_cargas() / carga.archivo_ruta).write_text('alterado')
        self.client.post(reverse('carga_confirmar', args=[carga.pk]))
        carga.refresh_from_db()
        self.assertEqual(carga.estado, 'fallida')
        self.assertFalse(Calificacion.objects.exists())

    def test_otra_corredora_no_ve_ni_confirma_la_carga(self):
        self.subir(fila_csv())
        carga = CargaMasiva.objects.get()
        self.client.force_login(self.op_b)
        self.assertEqual(self.client.get(reverse('carga_detalle', args=[carga.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('carga_confirmar', args=[carga.pk])).status_code, 403)
        carga.refresh_from_db()
        self.assertEqual(carga.estado, 'pendiente')

    def test_administrador_no_puede_cargar(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('carga_masiva')).status_code, 403)
        self.assertEqual(self.client.get(reverse('carga_plantilla')).status_code, 403)

    def test_el_boton_carga_masiva_de_la_grilla_apunta_a_la_pagina(self):
        self.assertContains(self.client.get(reverse('grilla')), reverse('carga_masiva'))

    def test_rollback_total_si_falla_la_grabacion(self):
        from unittest import mock
        self.subir(fila_csv(), fila_csv(instrumento='SQM-B', secuencia=10002))
        carga = CargaMasiva.objects.get()
        original = cargas.registrar
        llamadas = {'n': 0}

        def falla_en_la_segunda(*a, **k):
            llamadas['n'] += 1
            if llamadas['n'] == 2:
                raise RuntimeError('boom')
            return original(*a, **k)
        with mock.patch.object(cargas, 'registrar', falla_en_la_segunda):
            self.client.post(reverse('carga_confirmar', args=[carga.pk]))
        carga.refresh_from_db()
        self.assertEqual(carga.estado, 'fallida')
        self.assertFalse(Calificacion.objects.exists())


class Paso6GrillaTests(TestCase):
    """Mantenedor completo: filtro por instrumento, paginación, texto sin resultados, punto decimal."""

    @classmethod
    def setUpTestData(cls):
        cls.corr = Corredora.objects.create(nombre='A', rut='76.111.111-1')
        cls.op = Usuario.objects.create_user('op', password='x', rol=Usuario.ROL_OPERADOR, corredora=cls.corr)
        cls.admin = Usuario.objects.create_user('adm', password='x', rol=Usuario.ROL_ADMIN, is_staff=True)
        for i in range(30):
            cal = Calificacion.objects.create(
                corredora=cls.corr, ejercicio=2025 if i % 2 else 2024, mercado='ACN' if i < 20 else 'CFI',
                instrumento=f'COPEC-{i:02d}' if i < 28 else f'SQM-{i}', secuencia_evento=10001 + i)
            FactorCalificacion.objects.create(calificacion=cal, numero_columna=8, valor=D('0.1'))

    def setUp(self):
        self.client.force_login(self.op)

    def get(self, **params):
        return self.client.get(reverse('grilla'), params)

    def test_pagina_de_25_y_segunda_pagina_con_el_resto(self):
        r = self.get()
        self.assertEqual(len(r.context['filas']), 25)
        self.assertContains(r, 'Mostrando 1–25 de 30')
        r2 = self.get(page=2)
        self.assertEqual(len(r2.context['filas']), 5)
        self.assertContains(r2, 'Mostrando 26–30 de 30')

    def test_pagina_invalida_no_rompe(self):
        for malo in ('abc', '0', '-3', '999'):
            self.assertEqual(self.get(page=malo).status_code, 200)

    def test_filtro_por_instrumento_parcial_sin_distinguir_mayusculas(self):
        r = self.get(instrumento='sqm')
        self.assertEqual({f['obj'].instrumento for f in r.context['filas']}, {'SQM-28', 'SQM-29'})
        self.assertContains(r, 'Mostrando 1–2 de 2')

    def test_filtros_combinados_y_se_conservan_al_paginar(self):
        r = self.get(instrumento='COPEC', mercado='ACN', periodo='2025')
        self.assertTrue(all(f['obj'].mercado == 'ACN' and f['obj'].ejercicio == 2025 for f in r.context['filas']))
        self.assertEqual(r.context['total'], 10)
        r = self.get(instrumento='COPEC')
        self.assertIn('instrumento=COPEC', r.context['querystring'])
        self.assertContains(r, 'instrumento=COPEC&amp;page=2')

    def test_sin_resultados_con_filtros_muestra_el_texto_pedido(self):
        r = self.get(instrumento='NOEXISTE')
        self.assertContains(r, 'No se encontraron registros para los filtros seleccionados')
        self.assertEqual(r.context['filas'], [])

    def test_sin_datos_y_sin_filtros_muestra_otro_texto(self):
        Calificacion.objects.all().delete()
        r = self.get()
        self.assertContains(r, 'No hay calificaciones registradas')
        self.assertNotContains(r, 'No se encontraron registros')

    def test_periodo_no_numerico_se_ignora(self):
        self.assertEqual(self.get(periodo="2025' OR 1=1").context['total'], 30)

    def test_los_decimales_se_muestran_con_punto(self):
        html = self.get().content.decode()
        self.assertIn('0.10000000', html)
        self.assertNotIn('0,10000000', html)
        cal = Calificacion.objects.first()
        MontoCalificacion.objects.create(calificacion=cal, numero_columna=8, valor=D('1234.50'))
        detalle = self.client.get(reverse('detalle', args=[cal.pk])).content.decode()
        self.assertIn('1234.50', detalle)
        self.assertIn('0.10000000', detalle)

    def test_la_secuencia_se_muestra_sin_separador_de_miles(self):
        self.assertContains(self.get(), '>10001<')

    def test_boton_bitacora_solo_para_el_administrador(self):
        self.assertNotContains(self.get(), reverse('bitacora'))
        self.client.force_login(self.admin)
        self.assertContains(self.get(), reverse('bitacora'))


class Paso6BitacoraTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.corr_a = Corredora.objects.create(nombre='A', rut='76.111.111-1')
        cls.corr_b = Corredora.objects.create(nombre='B', rut='76.222.222-2')
        cls.op_a = Usuario.objects.create_user('op_a', password='x', rol=Usuario.ROL_OPERADOR, corredora=cls.corr_a)
        cls.op_b = Usuario.objects.create_user('op_b', password='x', rol=Usuario.ROL_OPERADOR, corredora=cls.corr_b)
        cls.admin = Usuario.objects.create_user('adm', password='x', rol=Usuario.ROL_ADMIN, is_staff=True)
        cls.mod = RegistroAuditoria.objects.create(
            usuario=cls.op_a, accion='modificar', id_calificacion=7, ip='10.0.0.5',
            detalle={'corredora_id': cls.corr_a.pk, 'corredora': 'A', 'instrumento': 'COPEC', 'ejercicio': 2025,
                     'via': 'manual',
                     'cambios': {'descripcion': {'antes': 'vieja', 'despues': 'nueva'},
                                 'factor_8': {'antes': '0.50000000', 'despues': '0.40000000'}}})
        cls.eli = RegistroAuditoria.objects.create(
            usuario=cls.op_b, accion='eliminar', id_calificacion=9, ip='10.0.0.6',
            detalle={'corredora_id': cls.corr_b.pk, 'corredora': 'B', 'instrumento': 'SQM-B', 'ejercicio': 2024,
                     'antes': {'mercado': 'ACN', 'instrumento': 'SQM-B', 'isfut': False}})
        cls.login = RegistroAuditoria.objects.create(usuario=cls.admin, accion='login', ip='127.0.0.1')

    def setUp(self):
        self.client.force_login(self.admin)

    def lista(self, **params):
        return self.client.get(reverse('bitacora'), params)

    def test_solo_el_administrador_ve_la_bitacora(self):
        self.assertEqual(self.lista().status_code, 200)
        for operador in (self.op_a, self.op_b):
            self.client.force_login(operador)
            self.assertEqual(self.lista().status_code, 403)
            self.assertEqual(self.client.get(reverse('bitacora_detalle', args=[self.mod.pk])).status_code, 403)
        self.client.logout()
        self.assertEqual(self.lista().status_code, 302)                  # sin sesión -> login

    def test_es_de_solo_lectura(self):
        self.assertEqual(self.client.post(reverse('bitacora'), {}).status_code, 405)
        self.assertEqual(self.client.post(reverse('bitacora_detalle', args=[self.mod.pk]), {}).status_code, 405)
        self.assertEqual(RegistroAuditoria.objects.filter(pk=self.mod.pk).count(), 1)

    def test_lista_los_registros_mas_recientes_primero_con_resumen(self):
        r = self.lista()
        ids = [f['obj'].pk for f in r.context['filas']]
        self.assertEqual(ids, sorted(ids, reverse=True))
        resumenes = {f['obj'].pk: f['resumen'] for f in r.context['filas']}
        self.assertEqual(resumenes[self.mod.pk], '2 campos modificados')
        self.assertEqual(resumenes[self.eli.pk], 'Eliminación lógica')

    def test_filtros_por_usuario_accion_corredora_y_fecha(self):
        ids = lambda **p: {f['obj'].pk for f in self.lista(**p).context['filas']}
        self.assertEqual(ids(usuario='op_a'), {self.mod.pk})
        self.assertEqual(ids(accion='eliminar'), {self.eli.pk})
        self.assertEqual(ids(corredora=self.corr_b.pk), {self.eli.pk})
        hoy = timezone.localdate().isoformat()
        self.assertEqual(len(ids(desde=hoy, hasta=hoy)), 3)
        self.assertEqual(ids(desde='2999-01-01'), set())
        self.assertEqual(len(ids(accion='inventada', corredora='x', desde='basura')), 3)   # filtros inválidos se ignoran

    def test_sin_resultados_muestra_el_texto(self):
        self.assertContains(self.lista(usuario='nadie'), 'No se encontraron registros para los filtros seleccionados')

    def test_paginacion(self):
        for i in range(30):
            RegistroAuditoria.objects.create(usuario=self.admin, accion='login', ip='127.0.0.1')
        r = self.lista()
        self.assertEqual(len(r.context['filas']), 25)
        self.assertContains(r, 'Mostrando 1–25 de 33')
        self.assertEqual(len(self.lista(page=2).context['filas']), 8)

    def test_detalle_muestra_antes_y_despues(self):
        r = self.client.get(reverse('bitacora_detalle', args=[self.mod.pk]))
        self.assertContains(r, 'Descripción')
        self.assertContains(r, 'vieja')
        self.assertContains(r, 'nueva')
        self.assertContains(r, 'Factor columna 8')
        self.assertContains(r, '10.0.0.5')

    def test_detalle_de_eliminacion_muestra_los_valores_previos(self):
        r = self.client.get(reverse('bitacora_detalle', args=[self.eli.pk]))
        self.assertContains(r, 'Valores antes de eliminar')
        self.assertContains(r, 'SQM-B')

    def test_detalle_de_registro_sin_detalle_y_de_id_inexistente(self):
        self.assertEqual(self.client.get(reverse('bitacora_detalle', args=[self.login.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('bitacora_detalle', args=[999999])).status_code, 404)

    def test_el_html_de_la_bitacora_escapa_el_contenido(self):
        RegistroAuditoria.objects.create(usuario=self.admin, accion='otro', ip='127.0.0.1',
                                         detalle={'evento': '<script>alert(1)</script>'})
        html = self.lista().content.decode() + self.client.get(
            reverse('bitacora_detalle', args=[RegistroAuditoria.objects.latest('id_registro').pk])).content.decode()
        self.assertNotIn('<script>alert(1)</script>', html)