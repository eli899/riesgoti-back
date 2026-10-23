from django.db import models
from django.db.models.functions import Now


class EventoAuditoria(models.Model):
    id = models.AutoField(primary_key=True, db_column='id')
    actor = models.ForeignKey('accounts.Usuario', on_delete=models.SET_NULL, null=True, blank=True, db_column='actor_id', related_name='eventos_ejecutados')
    incidencia = models.ForeignKey('incidents.Incidencia', on_delete=models.SET_NULL, null=True, blank=True, db_column='incidencia_id', related_name='eventos_auditoria')
    version_riesgo = models.ForeignKey('risks.VersionRiesgo', on_delete=models.SET_NULL, null=True, blank=True, db_column='version_riesgo_id', related_name='eventos_auditoria')
    version_documento = models.ForeignKey('documents_rag.VersionDocumento', on_delete=models.SET_NULL, null=True, blank=True, db_column='version_documento_id', related_name='eventos_auditoria')
    matriz = models.ForeignKey('assets_matrix.ConfiguracionMatriz', on_delete=models.SET_NULL, null=True, blank=True, db_column='matriz_id', related_name='eventos_auditoria')
    activo = models.ForeignKey('assets_matrix.Activo', on_delete=models.SET_NULL, null=True, blank=True, db_column='activo_id', related_name='eventos_auditoria')
    usuario_objeto = models.ForeignKey('accounts.Usuario', on_delete=models.SET_NULL, null=True, blank=True, db_column='usuario_objeto_id', related_name='eventos_recibidos')
    rol = models.ForeignKey('accounts.Rol', on_delete=models.SET_NULL, null=True, blank=True, db_column='rol_id', related_name='eventos_auditoria')
    accion = models.CharField(max_length=100, db_column='accion')
    detalle = models.TextField(null=True, blank=True, db_column='detalle')
    ocurrido_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='ocurrido_en')

    class Meta:
        db_table = 'EVENTO_AUDITORIA'
        ordering = ['-ocurrido_en']
