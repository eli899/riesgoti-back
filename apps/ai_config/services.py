"""Casos de uso de CONFIGURACION_IA_RAG: versionado inmutable, cifrado de API keys y prueba de conectividad."""
import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.ai_config.crypto import EnvelopeCryptoService
from apps.ai_config.models import ConfiguracionIARAG
from apps.audit.services import AuditService
from apps.documents_rag.models import VersionDocumento

PROVIDER_TIMEOUT_SECONDS = 20
PING_TEXT = 'ping'
# Nombre del modelo sentence-transformers que el servidor carga al arrancar (solo lo define el stack E2E).
PRELOAD_EMBEDDING_MODEL_ENV = 'RIESGOTI_PRELOAD_EMBEDDING_MODEL'

logger = logging.getLogger(__name__)


class AIConfigService:
    @staticmethod
    def get_active() -> ConfiguracionIARAG:
        config = ConfiguracionIARAG.objects.filter(activa=True).order_by('-creado_en', '-id').first()
        if config is None:
            raise NotFound('No existe una configuración IA/RAG activa. Ejecute seed_riesgoti o registre una.')
        return config

    @staticmethod
    def find_outdated_versions(modelo_embedding: str) -> list[VersionDocumento]:
        return list(
            VersionDocumento.objects.select_related('documento')
            .filter(activa=True, procesamiento='AUTORIZADO')
            .exclude(modelo_embedding=modelo_embedding)
            .order_by('documento__codigo', 'version')
        )

    @staticmethod
    def _next_version_label() -> str:
        total = ConfiguracionIARAG.objects.count()
        return f'v1.{total}-{timezone.localtime():%Y%m%d%H%M%S}'

    @classmethod
    @transaction.atomic
    def update(cls, actor, data: dict) -> ConfiguracionIARAG:
        """
        Publica una nueva versión de la configuración (la anterior queda inactiva como historial,
        referenciada por TAREA_IA.version_configuracion). Una API key vacía o nula conserva la cifrada anterior.
        """
        previous = ConfiguracionIARAG.objects.select_for_update().filter(activa=True).order_by('-creado_en', '-id').first()

        llm_cifrada, llm_mascara = cls._resolve_key(data.get('api_key_llm'), previous, 'llm')
        emb_cifrada, emb_mascara = cls._resolve_key(data.get('api_key_embedding'), previous, 'embedding')

        ConfiguracionIARAG.objects.filter(activa=True).update(activa=False)
        config = ConfiguracionIARAG.objects.create(
            version_configuracion=cls._next_version_label(),
            proveedor_llm=data['proveedor_llm'],
            modelo_llm=data['modelo_llm'],
            endpoint_base_llm=data.get('endpoint_base_llm'),
            api_key_llm_cifrada=llm_cifrada,
            api_key_llm_mascara=llm_mascara,
            proveedor_embedding=data['proveedor_embedding'],
            modelo_embedding=data['modelo_embedding'],
            api_key_embedding_cifrada=emb_cifrada,
            api_key_embedding_mascara=emb_mascara,
            chunk_size=data['chunk_size'],
            chunk_overlap=data['chunk_overlap'],
            top_k=data['top_k'],
            umbral_similitud=data['umbral_similitud'],
            activa=True,
            actualizada_por=actor,
        )

        llaves = [nombre for nombre, valor in (('api_key_llm', data.get('api_key_llm')), ('api_key_embedding', data.get('api_key_embedding'))) if valor and valor.strip()]
        AuditService.log(
            actor=actor,
            accion='ACTUALIZAR_CONFIG_IA_RAG',
            detalle=(
                f'version={config.version_configuracion} anterior={previous.version_configuracion if previous else "-"} '
                f'llm={config.proveedor_llm}/{config.modelo_llm} embedding={config.proveedor_embedding}/{config.modelo_embedding} '
                f'llaves_rotadas={",".join(llaves) or "ninguna"}'
            ),
        )
        return config

    @staticmethod
    def _resolve_key(raw_key: str | None, previous: ConfiguracionIARAG | None, kind: str) -> tuple[str | None, str | None]:
        if raw_key and raw_key.strip():
            return EnvelopeCryptoService.encrypt_api_key(raw_key)
        if previous is None:
            return None, None
        return getattr(previous, f'api_key_{kind}_cifrada'), getattr(previous, f'api_key_{kind}_mascara')


# ---------------------------------------------------------------------------
# Prueba de conectividad con proveedores LLM / Embeddings
# ---------------------------------------------------------------------------
@dataclass
class ProbeResult:
    status: str
    latency_ms: int | None = None
    dimensions: int | None = None
    error: str | None = None


@lru_cache(maxsize=2)
def _load_sentence_transformer(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name)


def preload_embedding_model(argv: Sequence[str], environ: Mapping[str, str]) -> bool:
    """
    Carga en memoria el modelo de embeddings del proceso que atiende peticiones, antes de abrir el puerto, para
    que la primera prueba de conectividad no pague la carga en frío (~40 s). Solo actúa si se define
    RIESGOTI_PRELOAD_EMBEDDING_MODEL y el proceso es el servidor (`runserver`; con autoreload, solo el hijo que
    sirve), nunca en `migrate` ni en `seed_riesgoti`. Un fallo no impide arrancar: la carga vuelve a ser perezosa.
    """
    model = environ.get(PRELOAD_EMBEDDING_MODEL_ENV, '').strip()
    if not model or 'runserver' not in argv:
        return False
    if '--noreload' not in argv and environ.get('RUN_MAIN') != 'true':
        return False  # Proceso vigilante del autoreload: no sirve peticiones.
    started = time.perf_counter()
    try:
        _load_sentence_transformer(model)
    except Exception:  # Red, caché o SDK: el servidor debe arrancar igualmente.
        logger.exception('No se pudo precargar el modelo de embeddings %s.', model)
        return False
    logger.info('Modelo de embeddings %s precargado en %.1f s.', model, time.perf_counter() - started)
    return True


class AIConnectionTester:
    @classmethod
    def run(cls, actor, overrides: dict) -> dict:
        active = ConfiguracionIARAG.objects.filter(activa=True).order_by('-creado_en', '-id').first()

        llm_provider = overrides.get('proveedor_llm') or getattr(active, 'proveedor_llm', '')
        llm_model = overrides.get('modelo_llm') or getattr(active, 'modelo_llm', '')
        endpoint = overrides.get('endpoint_base_llm') or getattr(active, 'endpoint_base_llm', None)
        llm_key = cls._resolve_plain_key(overrides.get('api_key_llm'), active, 'llm')

        emb_provider = overrides.get('proveedor_embedding') or getattr(active, 'proveedor_embedding', '')
        emb_model = overrides.get('modelo_embedding') or getattr(active, 'modelo_embedding', '')
        emb_key = cls._resolve_plain_key(overrides.get('api_key_embedding'), active, 'embedding')
        if not emb_key and emb_provider == llm_provider:
            emb_key = llm_key

        llm = cls._measure(lambda: cls._ping_llm(llm_provider, llm_model, endpoint, llm_key), secrets=(llm_key,))
        embedding = cls._measure(lambda: cls._ping_embedding(emb_provider, emb_model, emb_key), secrets=(emb_key,))

        AuditService.log(
            actor=actor,
            accion='PROBAR_CONEXION_IA',
            detalle=f'llm={llm_provider}/{llm_model}:{llm.status} embedding={emb_provider}/{emb_model}:{embedding.status}',
        )
        return {
            'llm_status': llm.status,
            'llm_provider': llm_provider,
            'llm_model': llm_model,
            'llm_latency_ms': llm.latency_ms,
            'llm_error': llm.error,
            'embedding_status': embedding.status,
            'embedding_provider': emb_provider,
            'embedding_model': emb_model,
            'embedding_dimensions': embedding.dimensions,
            'embedding_latency_ms': embedding.latency_ms,
            'embedding_error': embedding.error,
        }

    @staticmethod
    def _resolve_plain_key(raw_key: str | None, active: ConfiguracionIARAG | None, kind: str) -> str | None:
        if raw_key and raw_key.strip():
            return raw_key.strip()
        cifrada = getattr(active, f'api_key_{kind}_cifrada', None)
        return EnvelopeCryptoService.decrypt_api_key(cifrada) if cifrada else None

    @staticmethod
    def _measure(probe, secrets: tuple) -> ProbeResult:
        started = time.perf_counter()
        try:
            dimensions = probe()
        except Exception as exc:  # El proveedor puede lanzar cualquier error de red/SDK.
            message = f'{type(exc).__name__}: {exc}'
            for secret in secrets:
                if secret:
                    message = message.replace(secret, EnvelopeCryptoService.mask_api_key(secret))
            return ProbeResult(status='error', error=message[:500])
        latency_ms = round((time.perf_counter() - started) * 1000)
        return ProbeResult(status='ok', latency_ms=latency_ms, dimensions=dimensions)

    @staticmethod
    def _require_key(key: str | None, provider: str) -> str:
        if not key:
            raise ValueError(f'No hay API key configurada para el proveedor {provider}.')
        return key

    @classmethod
    def _ping_llm(cls, provider: str, model: str, endpoint: str | None, key: str | None) -> None:
        if provider == 'GEMINI':
            from google import genai

            client = genai.Client(api_key=cls._require_key(key, provider))
            client.models.generate_content(model=model, contents=PING_TEXT)
        elif provider in ('OPENAI', 'HUGGINGFACE_LOCAL'):
            from openai import OpenAI

            if provider == 'HUGGINGFACE_LOCAL' and not endpoint:
                raise ValueError('HUGGINGFACE_LOCAL requiere endpoint_base_llm (servidor compatible con la API de OpenAI).')
            api_key = cls._require_key(key, provider) if provider == 'OPENAI' else (key or 'no-key')
            client = OpenAI(api_key=api_key, base_url=endpoint or None, timeout=PROVIDER_TIMEOUT_SECONDS)
            client.chat.completions.create(model=model, messages=[{'role': 'user', 'content': PING_TEXT}], max_tokens=1)
        else:
            raise ValueError(f'Proveedor LLM no soportado: {provider}.')

    @classmethod
    def _ping_embedding(cls, provider: str, model: str, key: str | None) -> int:
        if provider == 'SENTENCE_TRANSFORMERS':
            vector = _load_sentence_transformer(model).encode(PING_TEXT, normalize_embeddings=True)
            return int(len(vector))
        if provider == 'OPENAI':
            from openai import OpenAI

            client = OpenAI(api_key=cls._require_key(key, provider), timeout=PROVIDER_TIMEOUT_SECONDS)
            return len(client.embeddings.create(model=model, input=PING_TEXT).data[0].embedding)
        if provider == 'GEMINI':
            from google import genai

            client = genai.Client(api_key=cls._require_key(key, provider))
            return len(client.models.embed_content(model=model, contents=PING_TEXT).embeddings[0].values)
        raise ValueError(f'Proveedor de embeddings no soportado: {provider}.')
