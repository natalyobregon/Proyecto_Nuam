# Nuam – Sistema de Calificaciones Tributarias

Aplicación web en Django para ingresar, consultar, modificar y eliminar (lógicamente) calificaciones
tributarias de instrumentos, con cálculo de factores, carga masiva por CSV y bitácora de auditoría.
Proyecto Integrado TIHV43, Unidad 3.

## Requisitos

- Windows con **WAMP** (MySQL 8.x y phpMyAdmin). Probado con MySQL 8.4.7.
- **Python 3.12 o superior** (probado con 3.14).
- Git.

## Instalación en Windows con WAMP

### 1. Clonar el proyecto

```powershell
git clone https://github.com/natalyobregon/Proyecto_Nuam.git
cd Proyecto_Nuam
```

### 2. Entorno virtual y dependencias

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Si PowerShell bloquea la activación, ejecuta una vez:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

### 3. Crear la base de datos

Con WAMP en verde, abre phpMyAdmin (`http://localhost/phpmyadmin`), pestaña **SQL**, y ejecuta:

```sql
CREATE DATABASE nuam_calificaciones
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
```

### 4. Archivo `.env`

Copia `.env.example` a `.env` y complétalo. El archivo `.env` no se sube a git.

```
SECRET_KEY=<clave larga y aleatoria>
DEBUG=True
DB_NAME=nuam_calificaciones
DB_USER=nuam_app
DB_PASSWORD=
DB_ADMIN_USER=root
DB_ADMIN_PASSWORD=
DB_HOST=127.0.0.1
DB_PORT=3306
ALLOWED_HOSTS=localhost,127.0.0.1
```

- `DB_USER` / `DB_PASSWORD`: usuario con el que corre la aplicación (mínimo privilegio, se crea en el paso 5).
  `DB_PASSWORD` puede quedar vacío en desarrollo local; en el servidor de producción conviene ponerle una clave
  (y volver a ejecutar `permisos_db` para aplicarla).
- `DB_ADMIN_USER` / `DB_ADMIN_PASSWORD`: administrador de la base (el `root` de WAMP). Solo se usa para migrar
  y para crear el usuario de la aplicación. Si `root` tiene contraseña, escríbela en `DB_ADMIN_PASSWORD`.

Para generar una `SECRET_KEY`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Variables opcionales: `LOGIN_MAX_INTENTOS` (5), `LOGIN_BLOQUEO_MINUTOS` (15), `SESION_MINUTOS` (30),
`CONFIAR_X_FORWARDED_FOR` (False).

### 5. Crear las tablas y cargar datos de ejemplo

```powershell
python manage.py migrate --database=admin
python manage.py permisos_db
python manage.py cargar_datos
```

- `migrate --database=admin` crea las tablas con el administrador.
- `permisos_db` crea el usuario `nuam_app` con mínimo privilegio (ver "Seguridad de la base de datos").
- `cargar_datos` crea la Bolsa, dos corredoras y tres usuarios de prueba. Se puede repetir sin duplicar.

### 6. Ejecutar

```powershell
python manage.py runserver
```

Abre `http://127.0.0.1:8000`.

## Usuarios de prueba

Todos tienen la clave `Ventana123$` (solo para desarrollo; cámbiala fuera de él).

| Usuario             | Rol           | Corredora            |
|---------------------|---------------|----------------------|
| `admin_nuam`        | Administrador | (ninguna)            |
| `operador_andes`    | Operador      | Corredora Andes S.A. |
| `operador_pacifico` | Operador      | Corredora Pacífico S.A. |

## Roles y permisos

El acceso se controla siempre en el servidor, con mínimo privilegio.

| Funcionalidad                              | Operador | Administrador |
|--------------------------------------------|:--------:|:-------------:|
| Consultar calificaciones                   | Sí (las de su corredora y las de la Bolsa, solo lectura) | Sí |
| Ingresar, modificar y eliminar calificaciones | Sí (solo las de su corredora) | No |
| Editar factores                            | Sí       | No            |
| Carga masiva por CSV                       | Sí       | No            |
| Consultar la bitácora                      | No       | Sí            |
| Administrar usuarios                       | No       | Sí            |

Un intento de acceso sin permiso muestra "Acceso denegado" (403) y queda registrado en la bitácora.

## Seguridad de la base de datos (bitácora de solo inserción)

La aplicación no se conecta como `root`. Usa `nuam_app`, que:

- no puede crear, modificar ni borrar tablas (sin `CREATE`, `ALTER`, `DROP`);
- tiene `SELECT`, `INSERT`, `UPDATE` y `DELETE` sobre las tablas de datos;
- tiene **solo `SELECT` e `INSERT`** sobre `registro_auditoria` (la bitácora).

Así, aunque alguien lograra ejecutar SQL desde la aplicación, no podría editar ni borrar la bitácora.
Esto se suma a la protección del modelo en Django (`save`/`delete` de la bitácora lanzan error).

```powershell
python manage.py permisos_db              # crea o actualiza el usuario y sus permisos
python manage.py permisos_db --dry-run    # muestra el SQL sin ejecutarlo
python manage.py permisos_db --verificar  # prueba con nuam_app: SELECT/INSERT sí, UPDATE/DELETE no
```

La verificación debe mostrar `SELECT` e `INSERT` permitidos y `UPDATE` y `DELETE` rechazados (error 1142).
Deja un registro `verificacion_permisos_db` en la bitácora; es normal, porque esa tabla no se puede borrar.

**Cuándo repetir `permisos_db`:** después de cada migración que cree tablas nuevas, para que `nuam_app`
tenga permisos sobre ellas. Las migraciones siempre se ejecutan con el administrador:

```powershell
python manage.py migrate --database=admin
python manage.py permisos_db
```

**Limitación conocida:** como la bitácora no se puede modificar, no se puede borrar un usuario que tenga
registros en ella (Django intentaría poner su referencia en `NULL`). Los usuarios se desactivan, no se eliminan.

## Carga masiva por CSV

Menú **Carga masiva**. Ahí se puede descargar una plantilla. Archivos de ejemplo en
`calificaciones/fixtures_csv/`:

- `carga_masiva_prueba_nuam.csv`: filas válidas, incluye el ejemplo del HDU.
- `carga_masiva_errores_nuam.csv`: mezcla filas válidas y con error, para probar el reporte de errores.

**Formato**

- Separador `;`, codificación UTF-8, con encabezado. Máximo 5 MB y 2.000 filas.
- Decimales con coma (`48,50`), sin separador de miles. Fechas `DD-MM-AAAA`.
- Columnas: `tipo_carga;ejercicio;mercado;instrumento;fecha_pago;secuencia;numero_dividendo;valor_historico;descripcion;c8;...;c37`.
- `tipo_carga` es `MONTOS` (el sistema calcula los factores) o `FACTORES` (se usan tal cual). Un archivo puede mezclar ambos.
- `c8` a `c37` son los 30 valores y no pueden ir vacíos: se informa `0` si no aplica.
- La llave única es (corredora, mercado, instrumento, ejercicio, secuencia): si ya existe, se actualiza.

**Flujo**

1. Se sube el archivo y se muestra una vista previa con la validación.
2. Si no hay errores, se confirma y se carga todo.
3. Si hay errores, se informa cada fila y columna con problema. Se puede cargar solo las filas válidas.
4. Cada carga guarda el hash SHA-256 del archivo y queda registrada en la bitácora.

No edites los CSV con Excel: puede cambiar el separador o los decimales y la carga los rechazará.
Usa el Bloc de notas o VS Code.

## Pruebas

```powershell
python manage.py test
```

Las pruebas crean y borran una base temporal `test_...`, algo que `nuam_app` no puede hacer (a propósito).
Para correrlas contra MySQL usa el administrador solo en esa ventana de PowerShell:

```powershell
$env:DB_USER='root'; $env:DB_PASSWORD=''
python manage.py test
Remove-Item Env:DB_USER, Env:DB_PASSWORD
```

Para correrlas sin MySQL, con SQLite en memoria:

```powershell
python manage.py test --settings=nuam.settings_test
```

## Solución de problemas

**`Plugin 'mysql_native_password' is not loaded` (error 1524)**
MySQL 8.4 o superior trae ese método de autenticación desactivado y el usuario `root` de WAMP lo usa.
Abre `my.ini` (menú de WAMP → MySQL → my.ini), agrega bajo `[mysqld]` la línea
`mysql_native_password=ON`, guarda y usa **Reiniciar todos los servicios**.

**`Access denied for user 'nuam_app'`**
El usuario todavía no existe o la clave del `.env` no coincide. Ejecuta `python manage.py permisos_db`
(vuelve a fijar la clave con la de `DB_PASSWORD`).

**`Access denied for user 'root'`**
Revisa `DB_ADMIN_USER` y `DB_ADMIN_PASSWORD` en `.env`. Si cambiaste la clave de `root` en WAMP, debe coincidir.

**`Falta la conexión de administrador`** (al ejecutar `permisos_db`)
Agrega `DB_ADMIN_USER` y `DB_ADMIN_PASSWORD` al `.env`.

**`'cryptography' package is required for sha256_password or caching_sha2_password`**
Falta la librería. Ejecuta `pip install -r requirements.txt`.

**`CREATE command denied` o `Access denied ... to database 'test_...'` al correr las pruebas**
Es lo esperado con `nuam_app`. Corre las pruebas como indica la sección "Pruebas".

**`Unknown database 'nuam_calificaciones'`**
Falta crear la base (paso 3) o `DB_NAME` en `.env` no coincide con el nombre creado.

**`Falta SECRET_KEY en el archivo .env`**
No existe `.env` o `SECRET_KEY` está vacía (paso 4).

**`Can't connect to MySQL server on '127.0.0.1'`**
WAMP no está en verde, o MySQL usa otro puerto. Revisa `DB_PORT`.

**El filtro de fechas de la Bitácora no devuelve resultados**
Ya está resuelto: el filtro compara rangos de fecha y no depende de las tablas de zona horaria de MySQL.

**La carga masiva rechaza un CSV que antes funcionaba**
Probablemente se guardó con Excel. Vuelve a descargar la plantilla o usa los archivos de `fixtures_csv/`.

## Estructura

```
nuam/             configuración (settings.py, settings_test.py, urls.py)
cuentas/          login, bloqueo por intentos, permisos por rol, alcance por corredora
calificaciones/   modelos, cálculo de factores, carga masiva, bitácora, plantillas
static/           CSS propio y Bootstrap local (sin CDN)
templates/        plantilla base y páginas de error
```
