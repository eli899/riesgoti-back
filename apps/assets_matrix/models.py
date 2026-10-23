from django.db import models
from django.db.models.functions import Now


class TipoActivo(models.Model):
    id = models.AutoField(primary_key=True, db_column='id')
    nombre = models.CharField(max_length=100, db_column='nombre')
    activo = models.BooleanField(default=True, db_default=True, db_column='activo')
    creado_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creado_en')
    ultima_modificacion = models.DateTimeField(auto_now=True, db_default=Now(), db_column='ultima_modificacion')

    class Meta:
        db_table = 'TIPO_ACTIVO'

    def __str__(self):
        return self.nombre


class Activo(models.Model):
    id = models.AutoField(primary_key=True, db_column='id')
    tipo = models.ForeignKey(TipoActivo, on_delete=models.PROTECT, db_column='tipo_id', related_name='activos')
    codigo = models.CharField(max_length=50, db_column='codigo')
    nombre = models.CharField(max_length=150, db_column='nombre')
    descripcion = models.TextField(null=True, blank=True, db_column='descripcion')
    criticidad = models.IntegerField(null=True, blank=True, db_column='criticidad')
    activo = models.BooleanField(default=True, db_default=True, db_column='activo')
    creado_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creado_en')
    ultima_modificacion = models.DateTimeField(auto_now=True, db_default=Now(), db_column='ultima_modificacion')

    class Meta:
        db_table = 'ACTIVO'

    def __str__(self):
        return f'{self.codigo} - {self.nombre}'


class NivelRiesgo(models.Model):
    id = models.AutoField(primary_key=True, db_column='id')
    codigo = models.CharField(max_length=50, db_column='codigo')
    orden = models.IntegerField(db_column='orden')
    creado_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creado_en')
    ultima_modificacion = models.DateTimeField(auto_now=True, db_default=Now(), db_column='ultima_modificacion')

    class Meta:
        db_table = 'NIVEL_RIESGO'
        ordering = ['orden']

    def __str__(self):
        return self.codigo


class ConfiguracionMatriz(models.Model):
    id = models.AutoField(primary_key=True, db_column='id')
    nombre = models.CharField(max_length=100, db_column='nombre')
    version = models.CharField(max_length=50, db_column='version')
    estado = models.CharField(max_length=50, db_column='estado')
    activa = models.BooleanField(default=False, db_default=False, db_column='activa')
    creada_por = models.ForeignKey('accounts.Usuario', on_delete=models.PROTECT, db_column='creada_por', related_name='matrices_creadas')
    creada_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creada_en')
    ultima_modificacion = models.DateTimeField(auto_now=True, db_default=Now(), db_column='ultima_modificacion')

    class Meta:
        db_table = 'CONFIGURACION_MATRIZ'

    def __str__(self):
        return f'{self.nombre} {self.version}'


class CriterioProbabilidad(models.Model):
    pk = models.CompositePrimaryKey('matriz_id', 'valor')
    matriz = models.ForeignKey(ConfiguracionMatriz, on_delete=models.CASCADE, db_column='matriz_id', related_name='criterios_probabilidad')
    valor = models.IntegerField(db_column='valor')
    nombre = models.CharField(max_length=100, db_column='nombre')
    descripcion = models.TextField(null=True, blank=True, db_column='descripcion')
    creado_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creado_en')
    ultima_modificacion = models.DateTimeField(auto_now=True, db_default=Now(), db_column='ultima_modificacion')

    class Meta:
        db_table = 'CRITERIO_PROBABILIDAD'
        ordering = ['valor']


class CriterioImpacto(models.Model):
    pk = models.CompositePrimaryKey('matriz_id', 'valor')
    matriz = models.ForeignKey(ConfiguracionMatriz, on_delete=models.CASCADE, db_column='matriz_id', related_name='criterios_impacto')
    valor = models.IntegerField(db_column='valor')
    nombre = models.CharField(max_length=100, db_column='nombre')
    descripcion = models.TextField(null=True, blank=True, db_column='descripcion')
    creado_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creado_en')
    ultima_modificacion = models.DateTimeField(auto_now=True, db_default=Now(), db_column='ultima_modificacion')

    class Meta:
        db_table = 'CRITERIO_IMPACTO'
        ordering = ['valor']


class CeldaMatriz(models.Model):
    # Las FKs compuestas (matriz_id, probabilidad) y (matriz_id, impacto) hacia los criterios
    # no son representables en el ORM; se crean con RunSQL en la migración assets_matrix.0002.
    id = models.AutoField(primary_key=True, db_column='id')
    matriz = models.ForeignKey(ConfiguracionMatriz, on_delete=models.CASCADE, db_column='matriz_id', related_name='celdas')
    probabilidad = models.IntegerField(db_column='probabilidad')
    impacto = models.IntegerField(db_column='impacto')
    nivel = models.ForeignKey(NivelRiesgo, on_delete=models.PROTECT, db_column='nivel_id', related_name='celdas')
    creada_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creada_en')
    ultima_modificacion = models.DateTimeField(auto_now=True, db_default=Now(), db_column='ultima_modificacion')

    class Meta:
        db_table = 'CELDA_MATRIZ'
        constraints = [
            models.UniqueConstraint(fields=['matriz', 'probabilidad', 'impacto'], name='UQ_CELDA_MATRIZ_COORD')
        ]

    def __str__(self):
        return f'P{self.probabilidad} x I{self.impacto}'
