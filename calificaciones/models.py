from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class Corredora(models.Model):
    id_corredora = models.AutoField(primary_key=True)
    nombre = models.CharField(max_length=150)
    rut = models.CharField(max_length=12, unique=True)
    activa = models.BooleanField(default=True)
    # Corredora especial «Bolsa»: dueña de las calificaciones oficiales (solo lectura para todos).
    es_bolsa = models.BooleanField(default=False)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'corredora'

    def __str__(self):
        return self.nombre


class Usuario(AbstractUser):
    """Tabla usuario. Hereda de AbstractUser: contraseña con hash PBKDF2,
    nombre, correo, is_active, last_login."""
    ROL_ADMIN = 'administrador'
    ROL_OPERADOR = 'operador'
    ROLES = [(ROL_ADMIN, 'Administrador'), (ROL_OPERADOR, 'Operador')]

    corredora = models.ForeignKey(
        Corredora, null=True, blank=True, on_delete=models.PROTECT,
        related_name='usuarios')  # null = administrador de Nuam
    rol = models.CharField(max_length=20, choices=ROLES, default=ROL_OPERADOR)
    intentos_fallidos = models.PositiveSmallIntegerField(default=0)
    bloqueado_hasta = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'usuario'

    def __str__(self):
        return f'{self.username} ({self.rol})'


class CargaMasiva(models.Model):
    ESTADOS = [('procesando', 'Procesando'), ('completada', 'Completada'),
               ('con_errores', 'Con errores'), ('fallida', 'Fallida')]

    id_carga = models.AutoField(primary_key=True)
    corredora = models.ForeignKey(Corredora, on_delete=models.PROTECT, related_name='cargas')
    usuario = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='cargas')
    nombre_archivo = models.CharField(max_length=255)
    fecha_carga = models.DateTimeField(auto_now_add=True)
    total_registros = models.PositiveIntegerField(default=0)
    registros_ok = models.PositiveIntegerField(default=0)
    registros_error = models.PositiveIntegerField(default=0)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='procesando')
    # Elemento "no estructurado": detalle de errores por fila (JSON)
    detalle_errores = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'carga_masiva'

    def __str__(self):
        return f'Carga {self.id_carga} - {self.nombre_archivo}'


class Calificacion(models.Model):
    ORIGENES = [('oficial_bolsa', 'Oficial bolsa'), ('local_corredora', 'Local corredora')]
    FUENTES = [('manual', 'Manual'), ('archivo', 'Archivo'), ('sistema', 'Sistema')]
    # Lista controlada de mercados (códigos de 3 letras del CSV). Confirmar lista final con el docente.
    MERCADOS = [('ACN', 'ACN - Acciones'), ('CFI', 'CFI - Cuotas de fondos de inversión'),
                ('FMU', 'FMU - Fondos mutuos')]
    TIPOS_SOCIEDAD = [('A', 'A - Abierta'), ('C', 'C - Cerrada')]

    id_calificacion = models.AutoField(primary_key=True)
    corredora = models.ForeignKey(Corredora, on_delete=models.PROTECT, related_name='calificaciones')
    carga = models.ForeignKey(CargaMasiva, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='calificaciones')
    ejercicio = models.PositiveSmallIntegerField()
    mercado = models.CharField(max_length=20, choices=MERCADOS)
    instrumento = models.CharField(max_length=30)
    secuencia_evento = models.PositiveIntegerField()
    dividendo = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    numero_dividendo = models.PositiveIntegerField(null=True, blank=True)
    tipo_sociedad = models.CharField(max_length=1, choices=TIPOS_SOCIEDAD, default='A')
    isfut = models.BooleanField(default=False)
    fecha_pago = models.DateField(null=True, blank=True)
    valor_historico = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    factor_actualizacion = models.DecimalField(max_digits=10, decimal_places=8, null=True, blank=True)
    descripcion = models.CharField(max_length=255, blank=True)
    origen = models.CharField(max_length=20, choices=ORIGENES, default='local_corredora')
    fuente_ingreso = models.CharField(max_length=10, choices=FUENTES, default='manual')
    eliminado = models.BooleanField(default=False)  # eliminación lógica
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'calificacion'
        constraints = [
            models.UniqueConstraint(
                fields=['corredora', 'mercado', 'instrumento', 'ejercicio',
                        'secuencia_evento', 'origen'],
                name='uq_calificacion_llave'),
        ]
        indexes = [models.Index(fields=['corredora', 'ejercicio'], name='ix_calif_corr_ejer')]

    def __str__(self):
        return f'{self.instrumento} {self.ejercicio}/{self.secuencia_evento}'


class MontoCalificacion(models.Model):
    """30 montos por calificación (columnas 8 a 37 del certificado SII)."""
    calificacion = models.ForeignKey(Calificacion, on_delete=models.CASCADE, related_name='montos')
    numero_columna = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(8), MaxValueValidator(37)])
    valor = models.DecimalField(max_digits=18, decimal_places=2, default=0)

    class Meta:
        db_table = 'monto_calificacion'
        constraints = [models.UniqueConstraint(fields=['calificacion', 'numero_columna'],
                                               name='uq_monto_calif_col')]


class FactorCalificacion(models.Model):
    """30 factores por calificación (columnas 8 a 37). Regla: suma de 8 a 19 <= 1."""
    calificacion = models.ForeignKey(Calificacion, on_delete=models.CASCADE, related_name='factores')
    numero_columna = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(8), MaxValueValidator(37)])
    valor = models.DecimalField(max_digits=10, decimal_places=8, default=0,
                                validators=[MinValueValidator(0)])

    class Meta:
        db_table = 'factor_calificacion'
        constraints = [models.UniqueConstraint(fields=['calificacion', 'numero_columna'],
                                               name='uq_factor_calif_col')]

    def clean(self):
        if self.numero_columna is not None and 8 <= self.numero_columna <= 19:
            otros = FactorCalificacion.objects.filter(
                calificacion_id=self.calificacion_id, numero_columna__gte=8,
                numero_columna__lte=19).exclude(pk=self.pk)
            suma = sum((f.valor for f in otros), Decimal('0')) + (self.valor or 0)
            if suma > 1:
                raise ValidationError('La suma de los factores 8 a 19 no puede superar 1.')

    def save(self, *args, **kwargs):
        self.full_clean(exclude=['calificacion'])
        super().save(*args, **kwargs)


class RegistroAuditoria(models.Model):
    """Bitácora append-only: no se edita ni se elimina."""
    ACCIONES = [('crear', 'Crear'), ('modificar', 'Modificar'), ('eliminar', 'Eliminar'),
                ('carga', 'Carga masiva'), ('login', 'Inicio de sesión'),
                ('login_fallido', 'Login fallido'), ('otro', 'Otro')]

    id_registro = models.BigAutoField(primary_key=True)
    usuario = models.ForeignKey(Usuario, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name='auditoria')
    id_calificacion = models.BigIntegerField(null=True, blank=True)  # sin FK a propósito
    accion = models.CharField(max_length=20, choices=ACCIONES)
    fecha = models.DateTimeField(auto_now_add=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    detalle = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = 'registro_auditoria'
        indexes = [models.Index(fields=['fecha'], name='ix_audit_fecha')]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError('La bitácora es de solo inserción.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('La bitácora no permite eliminar registros.')