from django.db import models
from django.db.models.functions import Now


class Incidencia(models.Model):
    id = models.AutoField(primary_key=True, db_column='id')
    reportante = models.ForeignKey('accounts.Usuario', on_delete=models.PROTECT, db_column='reportante_id', related_name='incidencias_reportadas')
    activo_reportado = models.ForeignKey('assets_matrix.Activo', on_delete=models.PROTECT, null=True, blank=True, db_column='activo_reportado_id', related_name='incidencias')
    activo_texto = models.CharField(max_length=255, null=True, blank=True, db_column='activo_texto')
    titulo = models.CharField(max_length=255, db_column='titulo')
    descripcion = models.TextField(db_column='descripcion')
    registrada_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='registrada_en')

    class Meta:
        db_table = 'INCIDENCIA'

    def __str__(self):
        return f'#{self.id} {self.titulo}'


class HistorialEstadoIncidencia(models.Model):
    id = models.AutoField(primary_key=True, db_column='id')
    incidencia = models.ForeignKey(Incidencia, on_delete=models.CASCADE, db_column='incidencia_id', related_name='historial_estados')
    estado = models.CharField(max_length=50, db_column='estado')
    actor = models.ForeignKey('accounts.Usuario', on_delete=models.PROTECT, db_column='actor_id', related_name='cambios_estado_incidencia')
    motivo = models.TextField(null=True, blank=True, db_column='motivo')
    ocurrido_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='ocurrido_en')

    class Meta:
        db_table = 'HISTORIAL_ESTADO_INCIDENCIA'
        ordering = ['ocurrido_en', 'id']


class AtencionIncidencia(models.Model):
    incidencia = models.OneToOneField(Incidencia, on_delete=models.CASCADE, primary_key=True, db_column='incidencia_id', related_name='atencion')
    analista = models.ForeignKey('accounts.Usuario', on_delete=models.PROTECT, db_column='analista_id', related_name='atenciones_asignadas')
    iniciada_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='iniciada_en')
    acciones = models.TextField(null=True, blank=True, db_column='acciones')
    nota_resolucion = models.TextField(null=True, blank=True, db_column='nota_resolucion')
    cerrada_en = models.DateTimeField(null=True, blank=True, db_column='cerrada_en')

    class Meta:
        db_table = 'ATENCION_INCIDENCIA'


class EvidenciaIncidencia(models.Model):
    id = models.AutoField(primary_key=True, db_column='id')
    incidencia = models.ForeignKey(Incidencia, on_delete=models.CASCADE, db_column='incidencia_id', related_name='evidencias')
    nombre_original = models.CharField(max_length=255, db_column='nombre_original')
    clave_archivo = models.CharField(max_length=255, db_column='clave_archivo')
    tipo_mime = models.CharField(max_length=100, db_column='tipo_mime')
    bytes = models.BigIntegerField(db_column='bytes')
    sha256 = models.CharField(max_length=64, db_column='sha256')
    creada_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creada_en')

    class Meta:
        db_table = 'EVIDENCIA_INCIDENCIA'
