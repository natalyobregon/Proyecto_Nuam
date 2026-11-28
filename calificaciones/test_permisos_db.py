"""Pruebas del comando permisos_db (Paso 7). No necesitan MySQL: validan el SQL que se genera."""
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.conf import settings
from django.test import SimpleTestCase

from calificaciones.management.commands.permisos_db import (PRIVILEGIOS_BITACORA, TABLA_BITACORA,
                                                            construir_sentencias)

TABLAS = ['corredora', 'usuario', 'calificacion', TABLA_BITACORA, 'django_session']


class SentenciasTests(SimpleTestCase):
    def sentencias(self, **extra):
        return construir_sentencias('nuam_db', TABLAS, 'nuam_app', 'localhost', 'Secreta#1', **extra)

    def grants(self):
        return [(sql, p) for sql, p in self.sentencias() if sql.startswith('GRANT')]

    def test_bitacora_solo_select_e_insert(self):
        sql = next(s for s, _ in self.grants() if f'`{TABLA_BITACORA}`' in s)
        self.assertEqual(sql.split(' ON ')[0], 'GRANT SELECT, INSERT')
        self.assertEqual(PRIVILEGIOS_BITACORA, ('SELECT', 'INSERT'))
        self.assertNotIn('UPDATE', sql)
        self.assertNotIn('DELETE', sql)

    def test_las_demas_tablas_tienen_permisos_de_datos(self):
        otras = [s for s, _ in self.grants() if f'`{TABLA_BITACORA}`' not in s]
        self.assertEqual(len(otras), len(TABLAS) - 1)
        for sql in otras:
            self.assertEqual(sql.split(' ON ')[0], 'GRANT SELECT, INSERT, UPDATE, DELETE')

    def test_nunca_otorga_estructura_ni_privilegios_globales(self):
        for sql, _ in self.grants():
            privilegios, destino = sql[len('GRANT '):].split(' ON ')
            self.assertEqual(destino.split(' TO ')[0].count('`'), 4)        # siempre `base`.`tabla`
            for prohibido in ('ALL', 'CREATE', 'ALTER', 'DROP', 'INDEX', 'GRANT OPTION'):
                self.assertNotIn(prohibido, privilegios)

    def test_revoca_antes_de_otorgar(self):
        sqls = [s for s, _ in self.sentencias()]
        self.assertTrue(sqls[2].startswith('REVOKE ALL PRIVILEGES'))
        self.assertTrue(all(s.startswith('GRANT') for s in sqls[3:]))

    def test_la_clave_va_como_parametro_no_en_el_texto_sql(self):
        for sql, params in self.sentencias():
            self.assertNotIn('Secreta#1', sql)
        crear = self.sentencias()[0]
        self.assertEqual(crear[1], ('nuam_app', 'localhost', 'Secreta#1'))


class ComandoTests(SimpleTestCase):
    def test_rechaza_motores_que_no_son_mysql(self):
        sqlite = {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}
        with patch.dict(settings.DATABASES, {'default': sqlite}, clear=True):
            with self.assertRaisesMessage(CommandError, 'solo aplica a MySQL/MariaDB'):
                call_command('permisos_db', stdout=StringIO())

    def _mysql(self, **user):
        base = {'ENGINE': 'django.db.backends.mysql', 'NAME': 'nuam_db', 'USER': 'nuam_app', 'PASSWORD': 'x'}
        base.update(user)
        return patch.dict(settings.DATABASES, {'default': base}, clear=True)

    def test_rechaza_usuario_con_caracteres_peligrosos(self):
        with self._mysql(USER="a'; DROP USER x; --"):
            with self.assertRaisesMessage(CommandError, 'DB_USER'):
                call_command('permisos_db', stdout=StringIO())

    def test_rechaza_host_invalido(self):
        with self._mysql():
            with self.assertRaisesMessage(CommandError, '--host'):
                call_command('permisos_db', host="x'; --", stdout=StringIO())

    def test_exige_conexion_de_administrador(self):
        with self._mysql():
            with self.assertRaisesMessage(CommandError, 'DB_ADMIN_USER'):
                call_command('permisos_db', stdout=StringIO())

    def test_la_clave_vacia_se_permite_y_no_se_exige(self):
        # sin DB_PASSWORD el comando no falla por eso: sigue y se detiene recien en la conexion de administrador
        with self._mysql(PASSWORD=''):
            with self.assertRaisesMessage(CommandError, 'DB_ADMIN_USER'):
                call_command('permisos_db', stdout=StringIO())

    def test_sentencias_con_clave_vacia(self):
        crear = construir_sentencias('nuam_db', TABLAS, 'nuam_app', 'localhost', '')[0]
        self.assertEqual(crear[0], 'CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s')
        self.assertEqual(crear[1], ('nuam_app', 'localhost', ''))
