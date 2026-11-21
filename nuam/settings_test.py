"""Configuracion para ejecutar las pruebas sin MariaDB (usa SQLite en memoria).

    python manage.py test --settings=nuam.settings_test
"""
import os

os.environ.setdefault('SECRET_KEY', 'clave-solo-para-pruebas')
os.environ.setdefault('DEBUG', 'False')

from .settings import *  # noqa: E402,F401,F403

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']  # rapido; solo en pruebas
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
