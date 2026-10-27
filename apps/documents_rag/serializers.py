from django.conf import settings
from django.core.validators import RegexValidator
from rest_framework import serializers

from apps.documents_rag import messages as msg
from apps.documents_rag.constants import (
    CODIGO_MIN_LENGTH,
    PROCESAMIENTOS_INDEXADOS,
    TITULO_MIN_LENGTH,
    VERSION_MIN_LENGTH,
    FinalidadDocumento,
)
from apps.documents_rag.models import Documento, VersionDocumento
from config.constants import BYTES_PER_MB, column_max_length

FINALIDADES = [f.value for f in FinalidadDocumento]
PDF_MAGIC_BYTES = b'%PDF-'


class DocumentUploadInputSerializer(serializers.Serializer):
    """DTO de entrada multipart para la carga de una nueva VERSION_DOCUMENTO."""

    codigo = serializers.CharField(
        min_length=CODIGO_MIN_LENGTH, max_length=column_max_length(Documento, 'codigo'),
        validators=[RegexValidator(r'^[A-Za-z0-9][A-Za-z0-9._-]*$', msg.CODIGO_FORMATO)],
    )
    titulo = serializers.CharField(min_length=TITULO_MIN_LENGTH, max_length=column_max_length(Documento, 'titulo'))
    descripcion = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    version = serializers.CharField(min_length=VERSION_MIN_LENGTH, max_length=column_max_length(VersionDocumento, 'version'))
    finalidad = serializers.ChoiceField(choices=FINALIDADES)
    archivo = serializers.FileField()

    def validate_codigo(self, value: str) -> str:
        return value.strip().upper()

    def validate_version(self, value: str) -> str:
        return value.strip()

    def validate_archivo(self, archivo):
        if archivo.size > settings.MAX_PDF_UPLOAD_BYTES:
            raise serializers.ValidationError(msg.PDF_DEMASIADO_GRANDE.format(mb=settings.MAX_PDF_UPLOAD_BYTES // BYTES_PER_MB))
        if not archivo.name.lower().endswith('.pdf'):
            raise serializers.ValidationError(msg.SOLO_PDF)
        archivo.seek(0)
        header = archivo.read(len(PDF_MAGIC_BYTES))
        archivo.seek(0)
        if header != PDF_MAGIC_BYTES:
            raise serializers.ValidationError(msg.PDF_INVALIDO)
        return archivo


class VersionDocumentoOutputSerializer(serializers.Serializer):
    """
    Mapper de salida de VERSION_DOCUMENTO para `fromApiDocumentVersionToDomain`.
    `requiere_reindexacion` compara modelo_embedding con el modelo vigente inyectado en context['modelo_embedding_actual'].
    """

    id = serializers.IntegerField()
    documento_id = serializers.IntegerField()
    codigo = serializers.CharField(source='documento.codigo')
    titulo = serializers.CharField(source='documento.titulo')
    descripcion = serializers.CharField(source='documento.descripcion', allow_null=True)
    version = serializers.CharField()
    sha256 = serializers.CharField()
    procesamiento = serializers.CharField()
    finalidad = serializers.CharField()
    activa = serializers.BooleanField()
    modelo_embedding = serializers.CharField(allow_null=True)
    version_segmentacion = serializers.CharField(allow_null=True)
    error_procesamiento = serializers.CharField(allow_null=True)
    total_fragmentos = serializers.SerializerMethodField()
    requiere_reindexacion = serializers.SerializerMethodField()
    cargada_por_id = serializers.IntegerField()
    cargada_por_nombre = serializers.CharField(source='cargada_por.nombre_completo')
    cargada_en = serializers.DateTimeField()
    autorizada_por_id = serializers.IntegerField(allow_null=True)
    autorizada_por_nombre = serializers.SerializerMethodField()
    autorizada_en = serializers.DateTimeField(allow_null=True)
    ultima_modificacion = serializers.DateTimeField()

    def get_total_fragmentos(self, obj) -> int:
        total = getattr(obj, 'total_fragmentos', None)
        return total if total is not None else obj.fragmentos.count()

    def get_requiere_reindexacion(self, obj) -> bool:
        actual = self.context.get('modelo_embedding_actual')
        return bool(actual) and obj.procesamiento in PROCESAMIENTOS_INDEXADOS and obj.modelo_embedding != actual

    def get_autorizada_por_nombre(self, obj) -> str | None:
        return obj.autorizada_por.nombre_completo if obj.autorizada_por else None


class FragmentoOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    orden = serializers.IntegerField()
    pagina_inicio = serializers.IntegerField(allow_null=True)
    pagina_fin = serializers.IntegerField(allow_null=True)
    contenido = serializers.CharField()


class DocumentPreviewOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    codigo = serializers.CharField(source='documento.codigo')
    titulo = serializers.CharField(source='documento.titulo')
    version = serializers.CharField()
    procesamiento = serializers.CharField()
    activa = serializers.BooleanField()
    modelo_embedding = serializers.CharField(allow_null=True)
    version_segmentacion = serializers.CharField(allow_null=True)
    error_procesamiento = serializers.CharField(allow_null=True)
    total_fragmentos = serializers.SerializerMethodField()
    fragmentos = serializers.SerializerMethodField()

    def get_total_fragmentos(self, obj) -> int:
        return len(obj.fragmentos.all())

    def get_fragmentos(self, obj) -> list[dict]:
        return FragmentoOutputSerializer(obj.fragmentos.all(), many=True).data
