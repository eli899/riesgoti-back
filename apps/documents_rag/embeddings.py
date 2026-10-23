"""Adaptador multi-proveedor de embeddings (SentenceTransformers / OpenAI / Gemini) con normalización L2."""
from functools import lru_cache

import faiss
import numpy as np

from apps.ai_config.crypto import EnvelopeCryptoService

DEFAULT_EMBEDDING_PROVIDER = 'SENTENCE_TRANSFORMERS'
DEFAULT_EMBEDDING_MODEL = 'sentence-transformers/paraphrase-multilingual-mpnet-base-v2'
PROVIDER_TIMEOUT_SECONDS = 60


@lru_cache(maxsize=2)
def _load_sentence_transformer(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def resolve_embedding_settings(config) -> tuple[str, str, str | None]:
    """(proveedor, modelo, api_key en claro) a partir de CONFIGURACION_IA_RAG (o valores por defecto)."""
    if config is None:
        return DEFAULT_EMBEDDING_PROVIDER, DEFAULT_EMBEDDING_MODEL, None
    cifrada = config.api_key_embedding_cifrada
    # Si el proveedor de embeddings coincide con el LLM y no tiene llave propia, reutiliza la del LLM.
    if not cifrada and config.proveedor_embedding == config.proveedor_llm:
        cifrada = config.api_key_llm_cifrada
    api_key = EnvelopeCryptoService.decrypt_api_key(cifrada) if cifrada else None
    return config.proveedor_embedding, config.modelo_embedding, api_key


class EmbeddingProviderService:
    BATCH_SIZE = 64

    @classmethod
    def embed_texts(cls, texts: list[str], config=None) -> np.ndarray:
        """Devuelve una matriz float32 (n, dim) con filas de norma L2 = 1 (producto interno == coseno)."""
        if not texts:
            raise ValueError('No hay textos para vectorizar.')
        provider, model, api_key = resolve_embedding_settings(config)

        if provider == 'SENTENCE_TRANSFORMERS':
            raw = _load_sentence_transformer(model).encode(
                list(texts), batch_size=32, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False,
            )
        elif provider == 'OPENAI':
            raw = cls._embed_openai(texts, model, cls._require_key(api_key, provider))
        elif provider == 'GEMINI':
            raw = cls._embed_gemini(texts, model, cls._require_key(api_key, provider))
        else:
            raise ValueError(f'Proveedor de embeddings no soportado: {provider}.')

        vectors = np.ascontiguousarray(np.asarray(raw, dtype='float32').reshape(len(texts), -1))
        faiss.normalize_L2(vectors)
        return vectors

    @classmethod
    def embed_query(cls, text: str, config=None) -> np.ndarray:
        return cls.embed_texts([text], config)

    @staticmethod
    def _require_key(key: str | None, provider: str) -> str:
        if not key:
            raise ValueError(f'No hay API key configurada para el proveedor de embeddings {provider}.')
        return key

    @classmethod
    def _batches(cls, texts: list[str]):
        for start in range(0, len(texts), cls.BATCH_SIZE):
            yield list(texts[start:start + cls.BATCH_SIZE])

    @classmethod
    def _embed_openai(cls, texts: list[str], model: str, api_key: str) -> list[list[float]]:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, timeout=PROVIDER_TIMEOUT_SECONDS)
        vectors = []
        for batch in cls._batches(texts):
            response = client.embeddings.create(model=model, input=batch)
            vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
        return vectors

    @classmethod
    def _embed_gemini(cls, texts: list[str], model: str, api_key: str) -> list[list[float]]:
        from google import genai

        client = genai.Client(api_key=api_key)
        vectors = []
        for batch in cls._batches(texts):
            response = client.models.embed_content(model=model, contents=batch)
            vectors.extend(embedding.values for embedding in response.embeddings)
        return vectors
