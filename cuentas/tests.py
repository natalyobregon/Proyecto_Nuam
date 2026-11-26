"""Pruebas de seguridad y login (plan de pruebas del informe: S01 a S08).

Ejecutar:  python manage.py test cuentas --settings=nuam.settings_test
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from calificaciones.models import Calificacion, Corredora, RegistroAuditoria, Usuario

from .alcance import calificaciones_visibles, obtener_calificacion
from .permisos import (BITACORA, ELIMINAR, INGRESAR, MODIFICAR, CARGA_MASIVA, CONSULTAR,
                       permiso_requerido, tiene_permiso)

CLAVE = 'Ventana123$'


def crear_calificacion(corredora, instrumento, descripcion=''):
    return Calificacion.objects.create(
        corredora=corredora, ejercicio=2025, mercado='ACCIONES', instrumento=instrumento,
        secuencia_evento=1, descripcion=descripcion)


class BaseTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.corr_a = Corredora.objects.create(nombre='Corredora A', rut='76.111.111-1')
        cls.corr_b = Corredora.objects.create(nombre='Corredora B', rut='76.222.222-2')
        cls.op_a = Usuario.objects.create_user('operador_a', password=CLAVE, rol=Usuario.ROL_OPERADOR,
                                               corredora=cls.corr_a)
        cls.op_b = Usuario.objects.create_user('operador_b', password=CLAVE, rol=Usuario.ROL_OPERADOR,
                                               corredora=cls.corr_b)
        cls.admin = Usuario.objects.create_user('admin_nuam', password=CLAVE, rol=Usuario.ROL_ADMIN,
                                                is_staff=True)
        cls.cal_a = crear_calificacion(cls.corr_a, 'COPEC')
        cls.cal_b = crear_calificacion(cls.corr_b, 'FALABELLA')

    def entrar(self, username, password=CLAVE):
        return self.client.post(reverse('cuentas:login'), {'username': username, 'password': password})


class LoginTests(BaseTest):
    def test_pantalla_de_login_muestra_campos_del_prototipo(self):
        r = self.client.get(reverse('cuentas:login'))
        self.assertContains(r, 'Inicio de sesión')
        self.assertContains(r, 'name="username"')
        self.assertContains(r, 'name="password"')
        self.assertContains(r, 'csrfmiddlewaretoken')

    def test_login_correcto_va_a_la_grilla_y_queda_en_bitacora(self):
        r = self.entrar('operador_a')
        self.assertRedirects(r, reverse('grilla'))
        self.assertTrue(RegistroAuditoria.objects.filter(usuario=self.op_a, accion='login').exists())

    def test_login_rota_la_sesion(self):
        self.client.get(reverse('cuentas:login'))
        antes = self.client.session.session_key
        self.entrar('operador_a')
        self.assertNotEqual(antes, self.client.session.session_key)

    def test_error_muestra_mensaje_del_prototipo_y_registra_intento(self):
        r = self.entrar('operador_a', 'incorrecta')
        self.assertContains(r, 'Usuario o contraseña incorrectos.')
        self.assertContains(r, 'is-invalid')
        self.op_a.refresh_from_db()
        self.assertEqual(self.op_a.intentos_fallidos, 1)
        self.assertTrue(RegistroAuditoria.objects.filter(usuario=self.op_a, accion='login_fallido').exists())

    def test_usuario_inexistente_recibe_el_mismo_mensaje(self):
        r = self.entrar('no_existe', 'cualquiera')
        self.assertContains(r, 'Usuario o contraseña incorrectos.')
        self.assertTrue(RegistroAuditoria.objects.filter(usuario=None, accion='login_fallido').exists())

    def test_la_contrasena_nunca_vuelve_en_el_html(self):
        r = self.entrar('operador_a', 'secreta-no-debe-verse')
        self.assertNotContains(r, 'secreta-no-debe-verse')

    def test_usuario_inactivo_no_entra(self):
        self.op_a.is_active = False
        self.op_a.save()
        self.assertContains(self.entrar('operador_a'), 'Usuario o contraseña incorrectos.')

    def test_corredora_desactivada_no_entra(self):
        self.corr_a.activa = False
        self.corr_a.save()
        r = self.entrar('operador_a')
        self.assertContains(r, 'Usuario o contraseña incorrectos.')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_no_hay_redireccion_abierta(self):
        url = reverse('cuentas:login') + '?next=https://sitio-malo.example/robo'
        r = self.client.post(url, {'username': 'operador_a', 'password': CLAVE})
        self.assertRedirects(r, reverse('grilla'))

    def test_next_interno_se_respeta(self):
        url = reverse('cuentas:login') + '?next=/calificaciones/'
        r = self.client.post(url, {'username': 'operador_a', 'password': CLAVE})
        self.assertRedirects(r, '/calificaciones/')

    def test_logout_solo_por_post(self):
        self.entrar('operador_a')
        self.assertEqual(self.client.get(reverse('cuentas:logout')).status_code, 405)
        r = self.client.post(reverse('cuentas:logout'))
        self.assertRedirects(r, reverse('cuentas:login'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_cookie_de_sesion_es_httponly(self):
        r = self.entrar('operador_a')
        self.assertTrue(r.cookies[settings.SESSION_COOKIE_NAME]['httponly'])

    def test_login_con_inyeccion_sql_se_trata_como_texto_S03(self):
        r = self.entrar("' OR '1'='1", "' OR '1'='1")
        self.assertContains(r, 'Usuario o contraseña incorrectos.')
        self.assertNotIn('_auth_user_id', self.client.session)


class BloqueoTests(BaseTest):  # S06
    def test_bloqueo_tras_el_maximo_de_intentos(self):
        for _ in range(settings.LOGIN_MAX_INTENTOS):
            r = self.entrar('operador_a', 'mala')
        self.assertContains(r, 'Demasiados intentos fallidos')
        self.op_a.refresh_from_db()
        self.assertIsNotNone(self.op_a.bloqueado_hasta)

    def test_cuenta_bloqueada_rechaza_hasta_la_clave_correcta(self):
        self.op_a.bloqueado_hasta = timezone.now() + timedelta(minutes=10)
        self.op_a.save()
        r = self.entrar('operador_a', CLAVE)
        self.assertContains(r, 'Demasiados intentos fallidos')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_pasado_el_plazo_puede_entrar_y_se_limpia_el_contador(self):
        self.op_a.bloqueado_hasta = timezone.now() - timedelta(minutes=1)
        self.op_a.intentos_fallidos = 3
        self.op_a.save()
        self.assertRedirects(self.entrar('operador_a'), reverse('grilla'))
        self.op_a.refresh_from_db()
        self.assertEqual(self.op_a.intentos_fallidos, 0)
        self.assertIsNone(self.op_a.bloqueado_hasta)

    def test_contrasenas_debiles_se_rechazan(self):
        for debil in ['12345678', 'password', 'corta1', 'operador_a1']:
            with self.assertRaises(ValidationError, msg=debil):
                validate_password(debil, self.op_a)
        validate_password(CLAVE, self.op_a)  # una buena pasa

    def test_la_sesion_vence_por_inactividad(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 30 * 60)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)

    def test_sesion_expirada_vuelve_al_login(self):
        self.entrar('operador_a')
        sesion = self.client.session
        sesion.set_expiry(-1)  # ya vencida
        sesion.save()
        r = self.client.get(reverse('grilla'))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('cuentas:login'), r['Location'])


class AccesoTests(BaseTest):
    def test_sin_sesion_la_grilla_redirige_al_login(self):
        r = self.client.get(reverse('grilla'))
        self.assertRedirects(r, reverse('cuentas:login') + '?next=/calificaciones/')

    def test_S01_operador_solo_ve_su_corredora(self):
        self.client.force_login(self.op_a)
        r = self.client.get(reverse('grilla'))
        self.assertContains(r, 'COPEC')
        self.assertNotContains(r, 'FALABELLA')

    def test_S01_cambiar_el_id_a_otra_corredora_da_acceso_denegado(self):
        with self.assertRaises(PermissionDenied):
            obtener_calificacion(self.op_a, self.cal_b.pk)
        self.assertEqual(obtener_calificacion(self.op_a, self.cal_a.pk), self.cal_a)

    def test_id_inexistente_se_trata_igual_que_el_de_otra_corredora(self):
        with self.assertRaises(PermissionDenied):
            obtener_calificacion(self.op_a, 999999)

    def test_administrador_de_nuam_ve_todas(self):
        self.assertEqual(calificaciones_visibles(self.admin).count(), 2)

    def test_operador_sin_corredora_no_ve_nada(self):
        huerfano = Usuario.objects.create_user('huerfano', password=CLAVE, rol=Usuario.ROL_OPERADOR)
        self.assertEqual(calificaciones_visibles(huerfano).count(), 0)

    def test_calificaciones_eliminadas_no_se_listan(self):
        self.cal_a.eliminado = True
        self.cal_a.save()
        self.assertEqual(calificaciones_visibles(self.op_a).count(), 0)

    def test_S02_operador_en_admin_recibe_acceso_denegado(self):
        self.client.force_login(self.op_a)
        for ruta in ['/admin/', '/admin/login/']:
            r = self.client.get(ruta, follow=True)
            self.assertIn(r.status_code, (403,))
            self.assertContains(r, 'Acceso denegado', status_code=403)

    def test_S02_anonimo_en_admin_va_al_login_del_sistema(self):
        r = self.client.get('/admin/', follow=True)
        self.assertContains(r, 'Inicio de sesión')

    def test_admin_login_es_el_mismo_del_sistema_y_bloquea(self):
        r = self.client.get('/admin/login/')
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r['Location'].startswith('/?next='))


class PermisosTests(BaseTest):
    def test_matriz_de_permisos(self):
        # Operador: consulta, ingresa, modifica, elimina y carga lo de su corredora (HDU 05).
        for p in (CONSULTAR, INGRESAR, MODIFICAR, ELIMINAR, CARGA_MASIVA):
            self.assertTrue(tiene_permiso(self.op_a, p), p)
        self.assertFalse(tiene_permiso(self.op_a, BITACORA))
        # Administrador: consulta y controla accesos; no modifica calificaciones.
        for p in (CONSULTAR, BITACORA):
            self.assertTrue(tiene_permiso(self.admin, p), p)
        for p in (INGRESAR, MODIFICAR, ELIMINAR, CARGA_MASIVA):
            self.assertFalse(tiene_permiso(self.admin, p), p)

    def test_decorador_deniega_y_registra_el_intento(self):
        @permiso_requerido(BITACORA)
        def vista(request):
            return None

        req = RequestFactory().get('/eliminar/')
        req.user = self.op_a
        req.META['REMOTE_ADDR'] = '10.0.0.5'
        with self.assertRaises(PermissionDenied):
            vista(req)
        reg = RegistroAuditoria.objects.get(accion='otro')
        self.assertEqual(reg.detalle['evento'], 'acceso_denegado')
        self.assertEqual(reg.ip, '10.0.0.5')

    def test_decorador_deja_pasar_al_rol_correcto(self):
        @permiso_requerido(BITACORA)
        def vista(request):
            return 'ok'

        req = RequestFactory().get('/eliminar/')
        req.user = self.admin
        self.assertEqual(vista(req), 'ok')

    def test_decorador_sin_sesion_redirige_al_login(self):
        from django.contrib.auth.models import AnonymousUser

        @permiso_requerido(BITACORA)
        def vista(request):
            return 'ok'

        req = RequestFactory().get('/eliminar/')
        req.user = AnonymousUser()
        self.assertEqual(vista(req).status_code, 302)

    def test_boton_ingresar_solo_para_quien_tiene_permiso(self):
        self.client.force_login(self.op_a)
        self.assertContains(self.client.get(reverse('grilla')), 'Carga masiva')
        self.client.force_login(self.admin)
        self.assertNotContains(self.client.get(reverse('grilla')), 'Carga masiva')


class EntradasTests(BaseTest):
    def test_S04_script_en_la_descripcion_se_muestra_como_texto(self):
        crear_calificacion(self.corr_a, 'XSS', '<script>alert(1)</script>')
        self.client.force_login(self.op_a)
        r = self.client.get(reverse('grilla'))
        self.assertNotContains(r, '<script>alert(1)</script>')
        self.assertContains(r, '&lt;script&gt;alert(1)&lt;/script&gt;')

    def test_S05_post_sin_token_csrf_es_rechazado(self):
        c = Client(enforce_csrf_checks=True)
        r = c.post(reverse('cuentas:login'), {'username': 'operador_a', 'password': CLAVE})
        self.assertEqual(r.status_code, 403)

    def test_S05_logout_sin_token_es_rechazado(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.op_a)
        self.assertEqual(c.post(reverse('cuentas:logout')).status_code, 403)

    def test_S08_cabeceras_de_seguridad(self):
        r = self.client.get(reverse('cuentas:login'))
        self.assertEqual(r['X-Frame-Options'], 'DENY')
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        self.assertIn("frame-ancestors 'none'", r['Content-Security-Policy'])
        self.assertIn("script-src 'self'", r['Content-Security-Policy'])

    def test_S08_pagina_de_login_no_carga_recursos_externos(self):
        html = self.client.get(reverse('cuentas:login')).content.decode()
        self.assertNotIn('http://', html)
        self.assertNotIn('https://', html)

    def test_S08_en_produccion_las_cookies_y_https_estan_activos(self):
        """Se verifica con la configuracion real (DEBUG=False): se carga en un proceso aparte."""
        import os
        import subprocess
        import sys
        env = {**os.environ, 'SECRET_KEY': 'x', 'DEBUG': 'False', 'DJANGO_SETTINGS_MODULE': 'nuam.settings'}
        codigo = ('from django.conf import settings as s;'
                  'print(s.SECURE_SSL_REDIRECT, s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, '
                  's.SESSION_COOKIE_HTTPONLY, s.SECURE_HSTS_SECONDS > 0)')
        salida = subprocess.run([sys.executable, '-c', codigo], env=env, capture_output=True,
                                text=True, cwd=settings.BASE_DIR, check=True).stdout.strip()
        self.assertEqual(salida, 'True True True True True')

    def test_pagina_404_no_muestra_detalles_tecnicos(self):
        self.client.force_login(self.op_a)
        r = self.client.get('/ruta-que-no-existe/')
        self.assertEqual(r.status_code, 404)
        self.assertNotContains(r, 'Traceback', status_code=404)
        self.assertNotContains(r, 'urlpatterns', status_code=404)