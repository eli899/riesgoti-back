from decimal import Decimal

from django.db import models


class ConfiguracionIARAG(models.Model):
    """Tabla técnica aditiva (no forma parte de bd.sql). Las API keys se guardan cifradas con AES-256-GCM."""

    id = models.AutoField(primary_key=True, db_column='id')
    version_configuracion = models.CharField(max_length=50, unique=True, db_column='version_configuracion')
    proveedor_llm = models.CharField(max_length=50, db_column='proveedor_llm')
    modelo_llm = models.CharField(max_length=100, db_column='modelo_llm')
    endpoint_base_llm = models.URLField(max_length=255, null=True, blank=True, db_column='endpoint_base_llm')
    api_key_llm_cifrada = models.TextField(null=True, blank=True, db_column='api_key_llm_cifrada')
    api_key_llm_mascara = models.CharField(max_length=50, null=True, blank=True, db_column='api_key_llm_mascara')
    proveedor_embedding = models.CharField(max_length=50, db_column='proveedor_embedding')
    modelo_embedding = models.CharField(max_length=100, db_column='modelo_embedding')
    api_key_embedding_cifrada = models.TextField(null=True, blank=True, db_column='api_key_embedding_cifrada')
    api_key_embedding_mascara = models.CharField(max_length=50, null=True, blank=True, db_column='api_key_embedding_mascara')
    chunk_size = models.PositiveIntegerField(default=800, db_column='chunk_size')
    chunk_overlap = models.PositiveIntegerField(default=120, db_column='chunk_overlap')
    top_k = models.PositiveIntegerField(default=4, db_column='top_k')
    umbral_similitud = models.DecimalField(max_digits=4, decimal_places=3, default=Decimal('0.400'), db_column='umbral_similitud')
    activa = models.BooleanField(default=True, db_column='activa')
    actualizada_por = models.ForeignKey('accounts.Usuario', on_delete=models.PROTECT, db_column='actualizada_por', related_name='configuraciones_ia')
    creado_en = models.DateTimeField(auto_now_add=True, db_column='creado_en')

    class Meta:
        db_table = 'CONFIGURACION_IA_RAG'

    def __str__(self):
        return self.version_configuracion
