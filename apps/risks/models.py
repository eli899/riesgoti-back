from django.db import models
from django.db.models.functions import Now


class Riesgo(models.Model):
    id = models.AutoField(primary_key=True, db_column='id')
    codigo = models.CharField(max_length=50, db_column='codigo')
    creado_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creado_en')
    ultima_modificacion = models.DateTimeField(auto_now=True, db_default=Now(), db_column='ultima_modificacion')

    class Meta:
        db_table = 'RIESGO'

    def __str__(self):
        return self.codigo


class VersionRiesgo(models.Model):
    id = models.AutoField(primary_key=True, db_column='id')
    riesgo = models.ForeignKey(Riesgo, on_delete=models.CASCADE, db_column='riesgo_id', related_name='versiones')
    numero = models.IntegerField(db_column='numero')
    origen = models.CharField(max_length=50, null=True, blank=True, db_column='origen')
    creada_por = models.ForeignKey('accounts.Usuario', on_delete=models.PROTECT, db_column='creada_por', related_name='versiones_riesgo_creadas')
    creada_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creada_en')
    titulo = models.CharField(max_length=255, db_column='titulo')
    descripcion = models.TextField(null=True, blank=True, db_column='descripcion')
    amenaza = models.TextField(null=True, blank=True, db_column='amenaza')
    vulnerabilidad = models.TextField(null=True, blank=True, db_column='vulnerabilidad')
    consecuencia = models.TextField(null=True, blank=True, db_column='consecuencia')
    recomendacion = models.TextField(null=True, blank=True, db_column='recomendacion')
    origen_recomendacion = models.CharField(max_length=50, null=True, blank=True, db_column='origen_recomendacion')
    activo_confirmado = models.ForeignKey('assets_matrix.Activo', on_delete=models.PROTECT, null=True, blank=True, db_column='activo_confirmado_id', related_name='versiones_riesgo_confirmadas')
    agrupacion_confirmada_por = models.ForeignKey('accounts.Usuario', on_delete=models.PROTECT, null=True, blank=True, db_column='agrupacion_confirmada_por', related_name='agrupaciones_confirmadas')
    agrupacion_confirmada_en = models.DateTimeField(null=True, blank=True, db_column='agrupacion_confirmada_en')

    class Meta:
        db_table = 'VERSION_RIESGO'
        ordering = ['-numero']

    def __str__(self):
        return f'{self.riesgo_id} v{self.numero}'


class EvaluacionRiesgo(models.Model):
    version = models.OneToOneField(VersionRiesgo, on_delete=models.CASCADE, primary_key=True, db_column='version_id', related_name='evaluacion')
    celda = models.ForeignKey('assets_matrix.CeldaMatriz', on_delete=models.PROTECT, db_column='celda_id', related_name='evaluaciones')
    evaluador = models.ForeignKey('accounts.Usuario', on_delete=models.PROTECT, db_column='evaluador_id', related_name='evaluaciones_realizadas')
    justificacion = models.TextField(null=True, blank=True, db_column='justificacion')
    evaluada_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='evaluada_en')

    class Meta:
        db_table = 'EVALUACION_RIESGO'


class DecisionRiesgo(models.Model):
    version = models.OneToOneField(VersionRiesgo, on_delete=models.CASCADE, primary_key=True, db_column='version_id', related_name='decision')
    accion = models.CharField(max_length=100, db_column='accion')
    analista = models.ForeignKey('accounts.Usuario', on_delete=models.PROTECT, db_column='analista_id', related_name='decisiones_riesgo')
    observacion = models.TextField(null=True, blank=True, db_column='observacion')
    justificacion_sin_fuentes = models.TextField(null=True, blank=True, db_column='justificacion_sin_fuentes')
    decidida_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='decidida_en')

    class Meta:
        db_table = 'DECISION_RIESGO'


class CitaVersionRiesgo(models.Model):
    pk = models.CompositePrimaryKey('version_id', 'numero')
    version = models.ForeignKey(VersionRiesgo, on_delete=models.CASCADE, db_column='version_id', related_name='citas')
    numero = models.IntegerField(db_column='numero')
    fragmento = models.ForeignKey('documents_rag.FragmentoDocumento', on_delete=models.PROTECT, db_column='fragmento_id', related_name='citas_riesgo')

    class Meta:
        db_table = 'CITA_VERSION_RIESGO'
        ordering = ['numero']


class TareaIA(models.Model):
    id = models.AutoField(primary_key=True, db_column='id')
    incidencia = models.ForeignKey('incidents.Incidencia', on_delete=models.CASCADE, db_column='incidencia_id', related_name='tareas_ia')
    rama = models.CharField(max_length=50, null=True, blank=True, db_column='rama')
    intento = models.IntegerField(default=1, db_default=1, db_column='intento')
    clave_idempotencia = models.CharField(max_length=100, null=True, blank=True, db_column='clave_idempotencia')
    estado = models.CharField(max_length=50, db_column='estado')
    proveedor = models.CharField(max_length=50, null=True, blank=True, db_column='proveedor')
    modelo = models.CharField(max_length=100, null=True, blank=True, db_column='modelo')
    version_configuracion = models.CharField(max_length=50, null=True, blank=True, db_column='version_configuracion')
    solicitada_por = models.ForeignKey('accounts.Usuario', on_delete=models.PROTECT, db_column='solicitada_por', related_name='tareas_ia_solicitadas')
    creada_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creada_en')
    iniciada_en = models.DateTimeField(null=True, blank=True, db_column='iniciada_en')
    terminada_en = models.DateTimeField(null=True, blank=True, db_column='terminada_en')
    error_codigo = models.CharField(max_length=100, null=True, blank=True, db_column='error_codigo')
    error_detalle = models.TextField(null=True, blank=True, db_column='error_detalle')

    class Meta:
        db_table = 'TAREA_IA'


class AnalisisIncidencia(models.Model):
    tarea = models.OneToOneField(TareaIA, on_delete=models.CASCADE, primary_key=True, db_column='tarea_id', related_name='analisis_estrategico')
    activo_identificado = models.CharField(max_length=255, null=True, blank=True, db_column='activo_identificado')
    amenaza = models.TextField(null=True, blank=True, db_column='amenaza')
    vulnerabilidad = models.TextField(null=True, blank=True, db_column='vulnerabilidad')
    consecuencia = models.TextField(null=True, blank=True, db_column='consecuencia')
    riesgo_candidato = models.TextField(null=True, blank=True, db_column='riesgo_candidato')
    creado_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creado_en')

    class Meta:
        db_table = 'ANALISIS_INCIDENCIA'


class VersionIncidencia(models.Model):
    pk = models.CompositePrimaryKey('version_id', 'analisis_id')
    version = models.ForeignKey(VersionRiesgo, on_delete=models.CASCADE, db_column='version_id', related_name='incidencias_vinculadas')
    analisis = models.ForeignKey(AnalisisIncidencia, on_delete=models.CASCADE, db_column='analisis_id', related_name='versiones_vinculadas')
    estado = models.CharField(max_length=50, db_column='estado')
    similitud = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True, db_column='similitud')
    motivo_similitud = models.TextField(null=True, blank=True, db_column='motivo_similitud')
    extracto_reporte = models.TextField(null=True, blank=True, db_column='extracto_reporte')
    revisada_por = models.ForeignKey('accounts.Usuario', on_delete=models.PROTECT, null=True, blank=True, db_column='revisada_por', related_name='vinculos_revisados')
    revisada_en = models.DateTimeField(null=True, blank=True, db_column='revisada_en')
    motivo_retiro = models.TextField(null=True, blank=True, db_column='motivo_retiro')

    class Meta:
        db_table = 'VERSION_INCIDENCIA'


class OrientacionOperativa(models.Model):
    tarea = models.OneToOneField(TareaIA, on_delete=models.CASCADE, primary_key=True, db_column='tarea_id', related_name='orientacion_operativa')
    tipo = models.CharField(max_length=50, null=True, blank=True, db_column='tipo')
    resumen = models.TextField(null=True, blank=True, db_column='resumen')
    advertencia = models.TextField(null=True, blank=True, db_column='advertencia')
    creada_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creada_en')

    class Meta:
        db_table = 'ORIENTACION_OPERATIVA'


class PasoOrientacion(models.Model):
    pk = models.CompositePrimaryKey('orientacion_id', 'orden')
    orientacion = models.ForeignKey(OrientacionOperativa, on_delete=models.CASCADE, db_column='tarea_id', related_name='pasos')
    orden = models.IntegerField(db_column='orden')
    instruccion = models.TextField(db_column='instruccion')

    class Meta:
        db_table = 'PASO_ORIENTACION'
        ordering = ['orden']


class RespuestaOrientacion(models.Model):
    orientacion = models.OneToOneField(OrientacionOperativa, on_delete=models.CASCADE, primary_key=True, db_column='tarea_id', related_name='respuesta')
    resultado = models.CharField(max_length=100, null=True, blank=True, db_column='resultado')
    respondida_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='respondida_en')

    class Meta:
        db_table = 'RESPUESTA_ORIENTACION'


class CitaOrientacion(models.Model):
    pk = models.CompositePrimaryKey('orientacion_id', 'numero')
    orientacion = models.ForeignKey(OrientacionOperativa, on_delete=models.CASCADE, db_column='tarea_id', related_name='citas')
    numero = models.IntegerField(db_column='numero')
    fragmento = models.ForeignKey('documents_rag.FragmentoDocumento', on_delete=models.PROTECT, db_column='fragmento_id', related_name='citas_orientacion')

    class Meta:
        db_table = 'CITA_ORIENTACION'
        ordering = ['numero']
