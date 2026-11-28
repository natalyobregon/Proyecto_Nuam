from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from calificaciones.models import (Calificacion, CargaMasiva, Corredora,
                                   FactorCalificacion, MontoCalificacion,
                                   RegistroAuditoria, Usuario)

CLAVE = 'Ventana123$'  # clave de prueba para todos los usuarios creados por este comando


class Command(BaseCommand):
    help = 'Carga datos de ejemplo (corredoras, usuarios, calificaciones). Se puede repetir sin duplicar.'

    @transaction.atomic
    def handle(self, *args, **opts):
        bolsa, _ = Corredora.objects.get_or_create(
            rut='99.999.999-9', defaults={'nombre': 'Bolsa (oficial)', 'es_bolsa': True})
        corr_a, _ = Corredora.objects.get_or_create(rut='76.111.111-1', defaults={'nombre': 'Corredora Andes S.A.'})  
        corr_b, _ = Corredora.objects.get_or_create(rut='76.222.222-2', defaults={'nombre': 'Corredora Pacifico S.A.'})

        def usuario(username, rol, corredora, **extra):
            u, creado = Usuario.objects.get_or_create(
                username=username,
                defaults={'rol': rol, 'corredora': corredora, 'email': f'{username}@nuam.cl', **extra})
            if creado:
                u.set_password(CLAVE)
                u.save()
            return u

        admin = usuario('admin_nuam', Usuario.ROL_ADMIN, None, is_staff=True)
        op_a = usuario('operador_andes', Usuario.ROL_OPERADOR, corr_a)
        usuario('operador_pacifico', Usuario.ROL_OPERADOR, corr_b)

        carga, _ = CargaMasiva.objects.get_or_create(
            corredora=corr_a, nombre_archivo='calificaciones_2025.csv',
            defaults={'usuario': op_a, 'total_registros': 6, 'registros_ok': 5,
                      'registros_error': 1, 'estado': 'con_errores',
                      'detalle_errores': [{'fila': 4, 'columna': 12,
                                           'error': 'La suma de factores 8-16 supera 1'}]})

        # (corredora, ejercicio, mercado, instrumento, secuencia, origen, fuente, carga)
        # Evento COPEC 10001: la Bolsa y Andes lo tienen; para Andes prevalece el suyo.
        filas = [
            (bolsa, 2025, 'ACN', 'COPEC', 10001, 'oficial_bolsa', 'sistema', None),
            (bolsa, 2025, 'ACN', 'CENCOSUD', 10001, 'oficial_bolsa', 'sistema', None),
            (bolsa, 2024, 'CFI', 'CFIBCI', 10001, 'oficial_bolsa', 'sistema', None),
            (corr_a, 2025, 'ACN', 'COPEC', 10001, 'local_corredora', 'archivo', carga),
            (corr_a, 2025, 'ACN', 'SQM-B', 10002, 'local_corredora', 'manual', None),
            (corr_b, 2025, 'ACN', 'FALABELLA', 10001, 'local_corredora', 'archivo', None),
            (corr_b, 2025, 'ACN', 'ENELAM', 10003, 'local_corredora', 'manual', None),
        ]
        for i, (corr, ejer, merc, instr, sec, origen, fuente, c) in enumerate(filas, start=1):
            cal, creada = Calificacion.objects.get_or_create(
                corredora=corr, mercado=merc, instrumento=instr, ejercicio=ejer,
                secuencia_evento=sec, origen=origen,
                defaults={'carga': c, 'dividendo': Decimal('1250.50') * i,
                          'fecha_pago': date(ejer, 5, 15), 'valor_historico': Decimal('98000.00') * i,
                          'factor_actualizacion': Decimal('0'), 'tipo_sociedad': 'A', 'isfut': i == 3,
                          'numero_dividendo': i,
                          'descripcion': f'Calificacion de ejemplo {instr}',
                          'fuente_ingreso': fuente})
            if not creada:
                continue
            MontoCalificacion.objects.bulk_create([
                MontoCalificacion(calificacion=cal, numero_columna=n, valor=Decimal(n * 1000 * i))
                for n in range(8, 38)])                       # 30 montos
            for n in range(8, 38):                            # 30 factores
                v = Decimal('0.10000000') if n <= 16 else Decimal('0.01500000')
                FactorCalificacion(calificacion=cal, numero_columna=n, valor=v).save()
            RegistroAuditoria.objects.create(
                usuario=op_a if corr == corr_a else admin, id_calificacion=cal.id_calificacion,
                accion='crear', ip='127.0.0.1', detalle={'fuente_ingreso': fuente, 'origen': origen})

        self.stdout.write(self.style.SUCCESS(
            f'Listo: {Corredora.objects.count()} corredoras, {Usuario.objects.count()} usuarios, '
            f'{Calificacion.objects.count()} calificaciones, {MontoCalificacion.objects.count()} montos, '
            f'{FactorCalificacion.objects.count()} factores.'))
        self.stdout.write(f'Usuarios de prueba: admin_nuam / operador_andes / operador_pacifico  (clave: {CLAVE})')