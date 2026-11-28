"""Permisos de base de datos de minimo privilegio (Paso 7, RNF04).

La aplicacion se conecta con un usuario (por defecto `nuam_app`, el DB_USER del .env) que NO puede
cambiar la estructura de la base y que, sobre la bitacora (`registro_auditoria`), solo tiene
SELECT e INSERT: aunque alguien vulnere la aplicacion, la bitacora no se puede editar ni borrar.

    python manage.py permisos_db               # crea/actualiza el usuario y sus permisos
    python manage.py permisos_db --dry-run     # muestra las sentencias SQL sin ejecutarlas
    python manage.py permisos_db --verificar   # prueba con el usuario real: SELECT/INSERT si, UPDATE/DELETE no

El comando se conecta con un usuario administrador (DB_ADMIN_USER / DB_ADMIN_PASSWORD en el .env,
alias `admin` en settings.py). Se puede repetir sin problema; conviene correrlo de nuevo despues de
cada `migrate --database=admin` que cree tablas nuevas.
"""
import re

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from calificaciones.models import RegistroAuditoria

TABLA_BITACORA = RegistroAuditoria._meta.db_table
PRIVILEGIOS_BITACORA = ('SELECT', 'INSERT')
PRIVILEGIOS_NORMALES = ('SELECT', 'INSERT', 'UPDATE', 'DELETE')
RE_USUARIO = re.compile(r'^[A-Za-z0-9_]{1,32}$')
RE_HOST = re.compile(r'^[A-Za-z0-9_.%:-]{1,60}$')


def construir_sentencias(base, tablas, usuario, host, clave, quote=lambda nombre: f'`{nombre}`'):
    """Lista de (sql, parametros) que deja al usuario con minimo privilegio.

    Orden: crear usuario, fijar clave, quitar todo lo anterior y otorgar tabla por tabla.
    Sin permisos de estructura (CREATE/ALTER/DROP) y con la bitacora solo en SELECT e INSERT.
    """
    cuenta = (usuario, host)
    sentencias = [
        ('CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s', (*cuenta, clave)),
        ('ALTER USER %s@%s IDENTIFIED BY %s', (*cuenta, clave)),
        ('REVOKE ALL PRIVILEGES, GRANT OPTION FROM %s@%s', cuenta),
    ]
    for tabla in sorted(tablas):
        privilegios = PRIVILEGIOS_BITACORA if tabla == TABLA_BITACORA else PRIVILEGIOS_NORMALES
        sentencias.append((f'GRANT {", ".join(privilegios)} ON {quote(base)}.{quote(tabla)} TO %s@%s', cuenta))
    return sentencias


class Command(BaseCommand):
    help = 'Crea el usuario de la aplicacion con minimo privilegio (bitacora solo SELECT e INSERT).'
    # La revision del sistema abre la conexion normal (DB_USER), que aun no existe la primera vez.
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('--host', default='localhost',
                            help="Desde donde se conecta el usuario (por defecto 'localhost').")
        parser.add_argument('--dry-run', action='store_true', help='Muestra el SQL sin ejecutarlo.')
        parser.add_argument('--verificar', action='store_true',
                            help='No cambia permisos: prueba con el usuario de la aplicacion.')

    def handle(self, *args, **opts):
        app = settings.DATABASES['default']
        usuario, clave, base = app.get('USER') or '', app.get('PASSWORD') or '', app.get('NAME')
        host = opts['host']
        if 'mysql' not in app['ENGINE']:
            raise CommandError('Este comando solo aplica a MySQL/MariaDB.')
        if not RE_USUARIO.match(usuario):
            raise CommandError('DB_USER del .env debe tener solo letras, numeros o guion bajo (max. 32).')
        if not RE_HOST.match(host):
            raise CommandError('Valor de --host no valido.')

        if opts['verificar']:
            return self.verificar(app, usuario, clave, base, host)

        if 'admin' not in settings.DATABASES:
            raise CommandError('Falta la conexion de administrador. Agrega al .env DB_ADMIN_USER y '
                               'DB_ADMIN_PASSWORD (ver .env.example).')
        admin = connections['admin']
        if admin.settings_dict['USER'] == usuario:
            raise CommandError(f'DB_ADMIN_USER y DB_USER son el mismo ({usuario}). El usuario de la aplicacion '
                               'debe ser distinto del administrador.')
        if not clave:
            self.stderr.write(self.style.WARNING(
                f"Aviso: DB_PASSWORD esta vacio, '{usuario}' se crea SIN clave. Sus permisos siguen siendo minimos "
                'y solo entra desde ese equipo, pero en el servidor de produccion conviene ponerle una.'))

        with admin.cursor() as cursor:
            tablas = admin.introspection.table_names(cursor)
            sentencias = construir_sentencias(base, tablas, usuario, host, clave, admin.ops.quote_name)
            if opts['dry_run']:
                for sql, params in sentencias:
                    self.stdout.write(self._mostrar(sql, params, clave))
                return
            if TABLA_BITACORA not in tablas:
                raise CommandError(f'No existe la tabla {TABLA_BITACORA}. Ejecuta primero: '
                                   'python manage.py migrate --database=admin')
            for sql, params in sentencias:
                cursor.execute(sql, params)
            cursor.execute('SHOW GRANTS FOR %s@%s', (usuario, host))
            grants = [fila[0] for fila in cursor.fetchall()]

        self.stdout.write(self.style.SUCCESS(
            f"Usuario '{usuario}'@'{host}' listo en la base '{base}': {len(tablas)} tablas con permisos de datos; "
            f"{TABLA_BITACORA} solo con {' e '.join(PRIVILEGIOS_BITACORA)}."))
        for g in grants:
            if TABLA_BITACORA in g:
                self.stdout.write(f'  {self._sin_clave(g)}')
        self.stdout.write('Compruebalo con: python manage.py permisos_db --verificar')

    @staticmethod
    def _sin_clave(texto):
        return re.sub(r"IDENTIFIED BY (PASSWORD )?'[^']*'", 'IDENTIFIED BY <oculta>', texto)

    def _mostrar(self, sql, params, clave):
        texto = sql
        for p in params:
            texto = texto.replace('%s', '<clave>' if p == clave else f"'{p}'", 1)
        return texto + ';'

    def verificar(self, app, usuario, clave, base, host):
        """Se conecta como el usuario de la aplicacion y comprueba lo permitido y lo prohibido."""
        import pymysql
        from pymysql.err import OperationalError

        try:
            conexion = pymysql.connect(
                host=app.get('HOST') or '127.0.0.1', port=int(app.get('PORT') or 3306),
                user=usuario, password=clave, database=base, charset='utf8mb4', autocommit=True)
        except OperationalError as exc:
            raise CommandError(f'No se pudo conectar como {usuario}: {exc}. Ejecuta antes permisos_db.')

        pruebas = [
            ('SELECT', f'SELECT COUNT(*) FROM {TABLA_BITACORA}', True),
            ('INSERT', f"INSERT INTO {TABLA_BITACORA} (accion, fecha, detalle) "
                       f"VALUES ('otro', NOW(6), '{{\"evento\": \"verificacion_permisos_db\"}}')", True),
            ('UPDATE', f"UPDATE {TABLA_BITACORA} SET accion = 'otro' WHERE id_registro = -1", False),
            ('DELETE', f'DELETE FROM {TABLA_BITACORA} WHERE id_registro = -1', False),
        ]
        fallos = 0
        with conexion.cursor() as cursor:
            for nombre, sql, debe_funcionar in pruebas:
                try:
                    cursor.execute(sql)
                    resultado = 'permitido'
                    ok = debe_funcionar
                except OperationalError as exc:
                    resultado = f'rechazado ({exc.args[0]})'
                    ok = not debe_funcionar and exc.args[0] == 1142      # 1142 = comando denegado
                fallos += 0 if ok else 1
                esperado = 'debe funcionar' if debe_funcionar else 'debe ser rechazado'
                linea = f'{nombre:<7} sobre {TABLA_BITACORA}: {resultado} -> {esperado}: {"OK" if ok else "FALLO"}'
                self.stdout.write(self.style.SUCCESS(linea) if ok else self.style.ERROR(linea))
        conexion.close()
        if fallos:
            raise CommandError(f'{fallos} comprobacion(es) fallaron. Ejecuta de nuevo permisos_db.')
        self.stdout.write(self.style.SUCCESS('Bitacora protegida: solo lectura e insercion.'))
        self.stdout.write('(La prueba INSERT deja un registro "verificacion_permisos_db" en la bitacora; es normal.)')
