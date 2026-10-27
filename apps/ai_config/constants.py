"""Proveedores admitidos en CONFIGURACION_IA_RAG. Espejo de front/src/constants/domain.constants.ts."""
from enum import StrEnum


class ProveedorLlm(StrEnum):
    OPENAI = 'OPENAI'
    GEMINI = 'GEMINI'
    HUGGINGFACE_LOCAL = 'HUGGINGFACE_LOCAL'


class ProveedorEmbedding(StrEnum):
    OPENAI = 'OPENAI'
    GEMINI = 'GEMINI'
    SENTENCE_TRANSFORMERS = 'SENTENCE_TRANSFORMERS'


# Rangos de CONFIGURACION_IA_RAG (espejo de FIELD_LIMITS.AI_* en front/src/constants/validation.constants.ts).
MODELO_MIN_LENGTH = 2
API_KEY_MAX_LENGTH = 512
CHUNK_SIZE_MIN, CHUNK_SIZE_MAX = 256, 2048
CHUNK_OVERLAP_MIN, CHUNK_OVERLAP_MAX = 0, 512
TOP_K_MIN, TOP_K_MAX = 1, 15
