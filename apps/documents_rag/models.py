from django.db import models
from django.db.models.functions import Now


class Documento(models.Model):
    id = models.AutoField(primary_key=True, db_column='id')
    codigo = models.CharField(max_length=50, db_column='codigo')
    titulo = models.CharField(max_length=255, db_column='titulo')
    descripcion = models.TextField(null=True, blank=True, db_column='descripcion')
    creado_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creado_en')
    ultima_modificacion = models.DateTimeField(auto_now=True, db_default=Now(), db_column='ultima_modificacion')

    class Meta:
        db_table = 'DOCUMENTO'

    def __str__(self):
        return f'{self.codigo} - {self.titulo}'


class VersionDocumento(models.Model):
    id = models.AutoField(primary_key=True, db_column='id')
    documento = models.ForeignKey(Documento, on_delete=models.PROTECT, db_column='documento_id', related_name='versiones')
    version = models.CharField(max_length=50, db_column='version')
    clave_archivo = models.CharField(max_length=255, db_column='clave_archivo')
    sha256 = models.CharField(max_length=64, db_column='sha256')
    cargada_por = models.ForeignKey('accounts.Usuario', on_delete=models.PROTECT, db_column='cargada_por', related_name='documentos_cargados')
    cargada_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='cargada_en')
    procesamiento = models.CharField(max_length=50, null=True, blank=True, db_column='procesamiento')
    finalidad = models.CharField(max_length=100, null=True, blank=True, db_column='finalidad')
    modelo_embedding = models.CharField(max_length=100, null=True, blank=True, db_column='modelo_embedding')
    version_segmentacion = models.CharField(max_length=50, null=True, blank=True, db_column='version_segmentacion')
    autorizada_por = models.ForeignKey('accounts.Usuario', on_delete=models.PROTECT, null=True, blank=True, db_column='autorizada_por', related_name='documentos_autorizados')
    autorizada_en = models.DateTimeField(null=True, blank=True, db_column='autorizada_en')
    activa = models.BooleanField(default=False, db_default=False, db_column='activa')
    error_procesamiento = models.TextField(null=True, blank=True, db_column='error_procesamiento')
    creado_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creado_en')
    ultima_modificacion = models.DateTimeField(auto_now=True, db_default=Now(), db_column='ultima_modificacion')

    class Meta:
        db_table = 'VERSION_DOCUMENTO'

    def __str__(self):
        return f'{self.documento_id} v{self.version}'


class FragmentoDocumento(models.Model):
    id = models.AutoField(primary_key=True, db_column='id')
    version_documento = models.ForeignKey(VersionDocumento, on_delete=models.CASCADE, db_column='version_documento_id', related_name='fragmentos')
    orden = models.IntegerField(db_column='orden')
    pagina_inicio = models.IntegerField(null=True, blank=True, db_column='pagina_inicio')
    pagina_fin = models.IntegerField(null=True, blank=True, db_column='pagina_fin')
    creado_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creado_en')
    ultima_modificacion = models.DateTimeField(auto_now=True, db_default=Now(), db_column='ultima_modificacion')
    contenido = models.TextField(db_column='contenido')

    class Meta:
        db_table = 'FRAGMENTO_DOCUMENTO'
        ordering = ['orden']
