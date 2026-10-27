"""
Índice vectorial FAISS por modelo de embeddings: IndexIDMap2(IndexFlatIP(dim)) cuyos IDs son FRAGMENTO_DOCUMENTO.id.
Con vectores de norma L2 = 1, el producto interno equivale a la similitud coseno.
"""
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import faiss
import numpy as np
from django.conf import settings
from django.utils.text import slugify

from apps.documents_rag.constants import FINALIDADES_ESTRATEGICAS, FINALIDADES_OPERATIVAS, ProcesamientoDocumento
from apps.documents_rag.embeddings import EmbeddingProviderService

try:  # Bloqueo entre procesos (backend y celery_worker comparten el volumen storage/).
    import fcntl
except ImportError:  # pragma: no cover - entornos Windows sin contenedor
    fcntl = None


@dataclass(frozen=True)
class RetrievedFragment:
    fragmento: object
    score: float


class FaissVectorStore:
    _cache: dict[str, tuple[int, faiss.Index]] = {}
    _thread_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------
    @staticmethod
    def index_path(modelo_embedding: str) -> Path:
        name = slugify(modelo_embedding.replace('/', '--')) or 'default'
        return Path(settings.FAISS_INDEX_ROOT) / f'{name}.index'

    @classmethod
    @contextmanager
    def _locked(cls, modelo_embedding: str):
        path = cls.index_path(modelo_embedding)
        path.parent.mkdir(parents=True, exist_ok=True)
        with cls._thread_lock, open(path.with_suffix('.lock'), 'a+') as lock_file:
            if fcntl:
                fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                yield path
            finally:
                if fcntl:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)

    @classmethod
    def load(cls, modelo_embedding: str) -> faiss.Index | None:
        path = cls.index_path(modelo_embedding)
        if not path.exists():
            return None
        mtime = path.stat().st_mtime_ns
        cached = cls._cache.get(str(path))
        if cached and cached[0] == mtime:
            return cached[1]
        index = faiss.read_index(str(path))
        cls._cache[str(path)] = (mtime, index)
        return index

    @classmethod
    def _persist(cls, path: Path, index: faiss.Index) -> None:
        tmp_path = path.with_suffix('.index.tmp')
        faiss.write_index(index, str(tmp_path))
        os.replace(tmp_path, path)
        cls._cache.pop(str(path), None)

    # ------------------------------------------------------------------
    # Escritura
    # ------------------------------------------------------------------
    @classmethod
    def add_vectors(cls, *, modelo_embedding: str, fragment_ids: list[int], vectors: np.ndarray) -> None:
        if len(fragment_ids) != len(vectors):
            raise ValueError('La cantidad de IDs y de vectores no coincide.')
        vectors = np.ascontiguousarray(vectors, dtype='float32')
        ids = np.asarray(fragment_ids, dtype='int64')
        with cls._locked(modelo_embedding) as path:
            index = faiss.read_index(str(path)) if path.exists() else faiss.IndexIDMap2(faiss.IndexFlatIP(vectors.shape[1]))
            if index.d != vectors.shape[1]:
                raise ValueError(
                    f'Dimensión incompatible con el índice {path.name}: índice={index.d}, vectores={vectors.shape[1]}.'
                )
            index.remove_ids(ids)  # Re-indexación idempotente de los mismos fragmentos.
            index.add_with_ids(vectors, ids)
            cls._persist(path, index)

    @classmethod
    def remove_vectors(cls, *, modelo_embedding: str, fragment_ids: list[int]) -> None:
        if not fragment_ids:
            return
        with cls._locked(modelo_embedding) as path:
            if not path.exists():
                return
            index = faiss.read_index(str(path))
            index.remove_ids(np.asarray(fragment_ids, dtype='int64'))
            cls._persist(path, index)

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------
    @classmethod
    def search(cls, *, modelo_embedding: str, query_vector: np.ndarray, k: int) -> list[tuple[int, float]]:
        index = cls.load(modelo_embedding)
        if index is None or index.ntotal == 0 or k <= 0:
            return []
        scores, ids = index.search(np.ascontiguousarray(query_vector, dtype='float32'), min(k, index.ntotal))
        return [(int(i), float(s)) for i, s in zip(ids[0], scores[0]) if i != -1]

    @classmethod
    def search_authorized_fragments(
        cls,
        query_text: str,
        finalidad_permitida: list[str] | tuple[str, ...],
        config=None,
    ) -> list[RetrievedFragment]:
        """
        Retriever filtrado: solo fragmentos de versiones activas, AUTORIZADAS, indexadas con el modelo de
        embeddings vigente y con finalidad permitida; score >= umbral_similitud; máximo top_k resultados.
        """
        from apps.ai_config.models import ConfiguracionIARAG
        from apps.documents_rag.models import FragmentoDocumento

        cfg = config or ConfiguracionIARAG.objects.filter(activa=True).order_by('-creado_en', '-id').first()
        if cfg is None:
            return []

        eligible_ids = set(
            FragmentoDocumento.objects.filter(
                version_documento__activa=True,
                version_documento__procesamiento=ProcesamientoDocumento.AUTORIZADO,
                version_documento__modelo_embedding=cfg.modelo_embedding,
                version_documento__finalidad__in=list(finalidad_permitida),
            ).values_list('id', flat=True)
        )
        index = cls.load(cfg.modelo_embedding)
        if not eligible_ids or index is None or index.ntotal == 0:
            return []

        query_vector = EmbeddingProviderService.embed_query(query_text, cfg)
        threshold = float(cfg.umbral_similitud)
        k = min(index.ntotal, max(cfg.top_k * 20, 100))
        while True:
            hits = [
                (fid, score)
                for fid, score in cls.search(modelo_embedding=cfg.modelo_embedding, query_vector=query_vector, k=k)
                if fid in eligible_ids and score >= threshold
            ]
            # Si el filtro descartó demasiados candidatos, amplía la búsqueda al índice completo.
            if len(hits) >= cfg.top_k or k >= index.ntotal:
                break
            k = index.ntotal
        hits = hits[:cfg.top_k]

        fragmentos = FragmentoDocumento.objects.select_related('version_documento__documento').in_bulk([fid for fid, _ in hits])
        return [RetrievedFragment(fragmento=fragmentos[fid], score=score) for fid, score in hits if fid in fragmentos]
