from decimal import Decimal

from rest_framework import serializers

from apps.ai_config import messages as msg
from apps.ai_config.constants import (
    API_KEY_MAX_LENGTH,
    CHUNK_OVERLAP_MAX,
    CHUNK_OVERLAP_MIN,
    CHUNK_SIZE_MAX,
    CHUNK_SIZE_MIN,
    MODELO_MIN_LENGTH,
    TOP_K_MAX,
    TOP_K_MIN,
    ProveedorEmbedding,
    ProveedorLlm,
)
from apps.ai_config.models import ConfiguracionIARAG
from config.constants import column_max_length

LLM_PROVIDERS = [p.value for p in ProveedorLlm]
EMBEDDING_PROVIDERS = [p.value for p in ProveedorEmbedding]


def _max(field_name: str) -> int:
    return column_max_length(ConfiguracionIARAG, field_name)


def validate_chunk_overlap(chunk_size: int, chunk_overlap: int) -> None:
    if chunk_overlap * 2 >= chunk_size:
        raise serializers.ValidationError({'chunk_overlap': msg.SOLAPAMIENTO_INVALIDO})


class AIConfigInputSerializer(serializers.Serializer):
    """DTO de entrada de CONFIGURACION_IA_RAG. Las API keys son estrictamente write_only."""

    proveedor_llm = serializers.ChoiceField(choices=LLM_PROVIDERS)
    modelo_llm = serializers.CharField(min_length=MODELO_MIN_LENGTH, max_length=_max('modelo_llm'))
    endpoint_base_llm = serializers.URLField(max_length=_max('endpoint_base_llm'), required=False, allow_blank=True, allow_null=True)
    api_key_llm = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True, max_length=API_KEY_MAX_LENGTH)
    proveedor_embedding = serializers.ChoiceField(choices=EMBEDDING_PROVIDERS)
    modelo_embedding = serializers.CharField(min_length=MODELO_MIN_LENGTH, max_length=_max('modelo_embedding'))
    api_key_embedding = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True, max_length=API_KEY_MAX_LENGTH)
    chunk_size = serializers.IntegerField(min_value=CHUNK_SIZE_MIN, max_value=CHUNK_SIZE_MAX)
    chunk_overlap = serializers.IntegerField(min_value=CHUNK_OVERLAP_MIN, max_value=CHUNK_OVERLAP_MAX)
    top_k = serializers.IntegerField(min_value=TOP_K_MIN, max_value=TOP_K_MAX)
    umbral_similitud = serializers.DecimalField(
        max_digits=4, decimal_places=3, min_value=Decimal('0'), max_value=Decimal('1'),
    )

    def validate(self, attrs):
        validate_chunk_overlap(attrs['chunk_size'], attrs['chunk_overlap'])
        if not attrs.get('endpoint_base_llm'):
            attrs['endpoint_base_llm'] = None
        return attrs


class VersionDesfasadaOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    codigo = serializers.CharField(source='documento.codigo')
    version = serializers.CharField()
    modelo_embedding = serializers.CharField(allow_null=True)


class AIConfigOutputSerializer(serializers.Serializer):
    """
    Mapper de salida: jamás expone api_key_*_cifrada; solo sus máscaras.
    `versiones_desfasadas` se inyecta vía context (VERSION_DOCUMENTO activas y autorizadas
    indexadas con un modelo_embedding distinto al configurado).
    """

    id = serializers.IntegerField()
    version_configuracion = serializers.CharField()
    proveedor_llm = serializers.CharField()
    modelo_llm = serializers.CharField()
    endpoint_base_llm = serializers.CharField(allow_null=True)
    api_key_llm_mascara = serializers.CharField(allow_null=True)
    proveedor_embedding = serializers.CharField()
    modelo_embedding = serializers.CharField()
    api_key_embedding_mascara = serializers.CharField(allow_null=True)
    chunk_size = serializers.IntegerField()
    chunk_overlap = serializers.IntegerField()
    top_k = serializers.IntegerField()
    umbral_similitud = serializers.DecimalField(max_digits=4, decimal_places=3, coerce_to_string=False)
    activa = serializers.BooleanField()
    actualizada_por_id = serializers.IntegerField()
    creado_en = serializers.DateTimeField()
    requiere_reindexacion_documentos = serializers.SerializerMethodField()
    versiones_desfasadas = serializers.SerializerMethodField()

    def _desfasadas(self):
        return self.context.get('versiones_desfasadas', [])

    def get_requiere_reindexacion_documentos(self, obj) -> bool:
        return bool(self._desfasadas())

    def get_versiones_desfasadas(self, obj) -> list[dict]:
        return VersionDesfasadaOutputSerializer(self._desfasadas(), many=True).data


class TestConnectionInputSerializer(serializers.Serializer):
    """Parámetros opcionales para probar una configuración antes de guardarla; lo omitido se toma de la activa."""

    proveedor_llm = serializers.ChoiceField(choices=LLM_PROVIDERS, required=False)
    modelo_llm = serializers.CharField(max_length=_max('modelo_llm'), required=False)
    endpoint_base_llm = serializers.URLField(max_length=_max('endpoint_base_llm'), required=False, allow_blank=True, allow_null=True)
    api_key_llm = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True, max_length=API_KEY_MAX_LENGTH)
    proveedor_embedding = serializers.ChoiceField(choices=EMBEDDING_PROVIDERS, required=False)
    modelo_embedding = serializers.CharField(max_length=_max('modelo_embedding'), required=False)
    api_key_embedding = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True, max_length=API_KEY_MAX_LENGTH)


class TestConnectionOutputSerializer(serializers.Serializer):
    llm_status = serializers.ChoiceField(choices=['ok', 'error'])
    llm_provider = serializers.CharField()
    llm_model = serializers.CharField()
    llm_latency_ms = serializers.IntegerField(allow_null=True)
    llm_error = serializers.CharField(allow_null=True)
    embedding_status = serializers.ChoiceField(choices=['ok', 'error'])
    embedding_provider = serializers.CharField()
    embedding_model = serializers.CharField()
    embedding_dimensions = serializers.IntegerField(allow_null=True)
    embedding_latency_ms = serializers.IntegerField(allow_null=True)
    embedding_error = serializers.CharField(allow_null=True)
