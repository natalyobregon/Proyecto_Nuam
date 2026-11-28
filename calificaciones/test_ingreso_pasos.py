"""Ingreso de calificaciones en 3 pasos: qué paso abre la pantalla y que la plantilla cumpla la política CSP."""
import re

from django.contrib.staticfiles import finders
from django.test import TestCase
from django.urls import reverse

from calificaciones.models import Calificacion, Corredora, Usuario
from calificaciones.tests import MONTOS_HDU


class IngresoEnTresPasosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.corredora = Corredora.objects.create(nombre='Corredora A', rut='76.111.111-1')
        cls.operador = Usuario.objects.create_user(
            'operador_a', password='Ventana123$', rol=Usuario.ROL_OPERADOR, corredora=cls.corredora)

    def setUp(self):
        self.client.force_login(self.operador)

    def basicos(self, **extra):
        datos = {'mercado': 'ACN', 'instrumento': 'COPEC', 'secuencia_evento': '10001', 'dividendo': '0',
                 'tipo_sociedad': 'A', 'fecha_pago': '2025-05-15', 'valor_historico': '0',
                 'ejercicio': '2025', 'descripcion': 'Prueba'}
        datos.update(extra)
        return datos

    def montos(self, **extra):
        datos = {f'monto_{col}': str(MONTOS_HDU.get(col, 0)) for col in range(8, 38)}
        datos.update(extra)
        return datos

    def paso_inicial(self, respuesta):
        return int(re.search(r'data-paso-inicial="(\d)"', respuesta.content.decode()).group(1))

    # --- estructura de la pantalla ---
    def test_la_pantalla_tiene_tres_pasos_y_abre_en_el_primero(self):
        r = self.client.get(reverse('ingresar'))
        html = r.content.decode()
        self.assertEqual(re.findall(r'<section data-paso="(\d)"', html), ['1', '2', '3'])
        self.assertEqual(self.paso_inicial(r), 1)
        for titulo in ('Paso 1 de 3', 'Paso 2 de 3', 'Paso 3 de 3'):
            self.assertContains(r, titulo)

    def test_cada_paso_contiene_sus_campos(self):
        html = self.client.get(reverse('ingresar')).content.decode()
        secciones = re.split(r'<section data-paso="\d"', html)[1:]
        self.assertIn('name="instrumento"', secciones[0])
        self.assertIn('name="monto_8"', secciones[1])
        self.assertIn('name="monto_37"', secciones[1])
        self.assertIn('Calcular factores', secciones[2] + html[html.index('data-solo-paso'):])

    def test_los_botones_de_guardar_y_calcular_siguen_en_el_formulario(self):
        r = self.client.get(reverse('ingresar'))
        self.assertContains(r, 'name="accion" value="calcular"')
        self.assertContains(r, 'name="accion" value="guardar"')

    def test_respeta_la_politica_csp_sin_scripts_ni_estilos_en_linea(self):
        html = self.client.get(reverse('ingresar')).content.decode()
        self.assertNotRegex(html, r'<script(?![^>]*\bsrc=)[^>]*>')          # solo scripts con src
        self.assertNotRegex(html, r'\sstyle=')                              # sin atributos style
        self.assertNotRegex(html, r'\son(click|change|submit|load)=')       # sin manejadores en línea
        self.assertContains(self.client.get(reverse('ingresar')), 'js/ingreso_pasos.js')

    def test_el_archivo_javascript_existe(self):
        self.assertIsNotNone(finders.find('js/ingreso_pasos.js'))

    def test_modificar_tambien_usa_los_tres_pasos(self):
        self.client.post(reverse('ingresar'), {**self.basicos(), **self.montos(), 'accion': 'guardar'})
        cal = Calificacion.objects.get(instrumento='COPEC')
        r = self.client.get(reverse('editar', args=[cal.pk]))
        self.assertEqual(re.findall(r'<section data-paso="(\d)"', r.content.decode()), ['1', '2', '3'])
        self.assertEqual(self.paso_inicial(r), 1)

    # --- en qué paso reabre después de enviar ---
    def test_error_en_datos_basicos_reabre_en_el_paso_1(self):
        r = self.client.post(reverse('ingresar'), {**self.basicos(secuencia_evento='9999'), **self.montos(),
                                                   'accion': 'guardar'})
        self.assertEqual(self.paso_inicial(r), 1)
        self.assertFalse(Calificacion.objects.exists())

    def test_monto_invalido_reabre_en_el_paso_2(self):
        r = self.client.post(reverse('ingresar'), {**self.basicos(), **self.montos(monto_9='abc'),
                                                   'accion': 'guardar'})
        self.assertEqual(self.paso_inicial(r), 2)

    def test_montos_en_cero_reabre_en_el_paso_2(self):
        r = self.client.post(reverse('ingresar'), {**self.basicos(), 'accion': 'guardar',
                                                   **{f'monto_{c}': '0' for c in range(8, 38)}})
        self.assertEqual(self.paso_inicial(r), 2)

    def test_calcular_factores_reabre_en_el_paso_3_con_los_factores(self):
        r = self.client.post(reverse('ingresar'), {**self.basicos(), **self.montos(), 'accion': 'calcular'})
        self.assertEqual(self.paso_inicial(r), 3)
        self.assertContains(r, 'name="factor_8"')

    def test_suma_de_factores_mayor_a_1_reabre_en_el_paso_3(self):
        r = self.client.post(reverse('ingresar'), {**self.basicos(), **self.montos(), 'accion': 'guardar',
                                                   'factor_8': '0.60000000', 'factor_9': '0.50000000',
                                                   'factor_11': '0'})
        self.assertEqual(self.paso_inicial(r), 3)
        self.assertFalse(Calificacion.objects.exists())

    def test_guardar_en_los_tres_pasos_sigue_funcionando(self):
        r = self.client.post(reverse('ingresar'), {**self.basicos(), **self.montos(), 'accion': 'guardar'})
        self.assertRedirects(r, reverse('grilla'))
        self.assertEqual(Calificacion.objects.count(), 1)