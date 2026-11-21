# Si la maquina usa PyMySQL en vez de mysqlclient, lo registramos como driver de MySQL/MariaDB.
try:
    import pymysql

    pymysql.version_info = (2, 2, 1, 'final', 0)
    pymysql.install_as_MySQLdb()
except ImportError:  # mysqlclient instalado, o pruebas con SQLite
    pass
