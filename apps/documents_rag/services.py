"""
Casos de uso de gobernanza documental: carga de PDF, procesamiento (chunking + embeddings + FAISS),
autorización, activación/desactivación y re-indexación, con auditoría transversal.

INV-04: los FRAGMENTO_DOCUMENTO de una versión que fue autorizada o que está citada jamás se eliminan;
desactivar una versión solo la excluye de nuevas consultas RAG.
"""
import hashlib
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.text import get_valid_filename, slugify
from rest_framework.exceptions import ValidationError

from apps.ai_config.models import ConfiguracionIARAG
from apps.audit.constants import AccionAuditoria
from apps.audit.services import AuditService
from apps.documents_rag import messages as msg
from apps.documents_rag.chunking import StructuredMarkdownPDFChunker, build_segmentation_label
from apps.documents_rag.constants import PROCESAMIENTOS_INDEXADOS, ProcesamientoDocumento
from apps.documents_rag.embeddings import EmbeddingProviderService, resolve_embedding_settings
from apps.documents_rag.faiss_store import FaissVectorStore
from apps.documents_rag.models import Documento, FragmentoDocumento, VersionDocumento
from config.constants import IO_BLOCK_BYTES, MAX_ERROR_CHARS


def get_active_ai_config() -> ConfiguracionIARAG | None:
    return ConfiguracionIARAG.objects.filter(activa=True).order_by('-creado_en', '-id').first()


def pdf_absolute_path(clave_archivo: str) -> Path:
    return Path(settings.PDF_STORAGE_ROOT) / clave_archivo


class DocumentIngestionService:
    # ------------------------------------------------------------------
    # Carga
    # ------------------------------------------------------------------
    @staticmethod
    def _sha256(archivo) -> str:
        digest = hashlib.sha256()
        archivo.seek(0)
        for block in archivo.chunks(IO_BLOCK_BYTES):
            digest.update(block)
        archivo.seek(0)
        return digest.hexdigest()

    @staticmethod
    def _store_file(archivo, sha256: str) -> tuple[str, bool]:
        stem = slugify(Path(archivo.name).stem)[:80] or 'documento'
        clave = f'{sha256[:12]}_{get_valid_filename(stem)}.pdf'
        destino = pdf_absolute_path(clave)
        if destino.exists():
            return clave, False
        destino.parent.mkdir(parents=True, exist_ok=True)
        archivo.seek(0)
        with open(destino, 'wb') as handle:
            for block in archivo.chunks(IO_BLOCK_BYTES):
                handle.write(block)
        return clave, True

    @classmethod
    def upload(cls, actor, data: dict, *, enqueue: bool = True) -> VersionDocumento:
        archivo = data['archivo']
        sha256 = cls._sha256(archivo)
        clave, created_file = cls._store_file(archivo, sha256)
        try:
            with transaction.atomic():
                documento = Documento.objects.select_for_update().filter(codigo=data['codigo']).first()
                if documento is None:
                    documento = Documento.objects.create(
                        codigo=data['codigo'], titulo=data['titulo'], descripcion=data.get('descripcion') or None,
                    )
                else:
                    documento.titulo = data['titulo']
                    if data.get('descripcion'):
                        documento.descripcion = data['descripcion']
                    documento.save()

                if documento.versiones.filter(version=data['version']).exists():
                    raise ValidationError({'version': msg.VERSION_DUPLICADA.format(codigo=documento.codigo, version=data['version'])})
                duplicada = documento.versiones.filter(sha256=sha256).first()
                if duplicada:
                    raise ValidationError({'archivo': msg.PDF_DUPLICADO.format(version=duplicada.version)})

                version = VersionDocumento.objects.create(
                    documento=documento,
                    version=data['version'],
                    clave_archivo=clave,
                    sha256=sha256,
                    cargada_por=actor,
                    procesamiento=ProcesamientoDocumento.PROCESANDO,
                    finalidad=data['finalidad'],
                    activa=False,
                )
                AuditService.log(
                    actor=actor, accion=AccionAuditoria.CARGAR_VERSION_DOCUMENTO, version_documento=version,
                    detalle=f'codigo={documento.codigo} version={version.version} sha256={sha256} finalidad={version.finalidad}',
                )
                if enqueue:
                    cls.enqueue_processing(version)
        except Exception:
            if created_file:
                pdf_absolute_path(clave).unlink(missing_ok=True)
            raise
        return version

    @staticmethod
    def enqueue_processing(version: VersionDocumento) -> None:
        from apps.documents_rag.tasks import process_pdf_version_task

        version_id = version.id
        transaction.on_commit(lambda: process_pdf_version_task.delay(version_id))

    # ------------------------------------------------------------------
    # Procesamiento (ejecutado por Celery)
    # ------------------------------------------------------------------
    @staticmethod
    def _has_citations(fragment_ids) -> bool:
        return FragmentoDocumento.objects.filter(id__in=fragment_ids).filter(
            citas_orientacion__isnull=False,
        ).exists() or FragmentoDocumento.objects.filter(id__in=fragment_ids, citas_riesgo__isnull=False).exists()

    @classmethod
    def process_version(cls, version_documento_id: int) -> dict:
        version = VersionDocumento.objects.select_related('documento').get(id=version_documento_id)
        if version.procesamiento != ProcesamientoDocumento.PROCESANDO:
            return {'status': 'skipped', 'version_id': version.id, 'procesamiento': version.procesamiento}

        cfg = get_active_ai_config()
        chunk_size = cfg.chunk_size if cfg else 800
        chunk_overlap = cfg.chunk_overlap if cfg else 120
        _, modelo_embedding, _ = resolve_embedding_settings(cfg)
        try:
            chunks = StructuredMarkdownPDFChunker.extract_and_chunk(
                pdf_path=str(pdf_absolute_path(version.clave_archivo)),
                doc_codigo=version.documento.codigo,
                doc_version=version.version,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            vectors = EmbeddingProviderService.embed_texts([c.contenido for c in chunks], cfg)

            with transaction.atomic():
                locked = VersionDocumento.objects.select_for_update().get(pk=version.pk)
                if locked.procesamiento != ProcesamientoDocumento.PROCESANDO:
                    return {'status': 'skipped', 'version_id': version.id, 'procesamiento': locked.procesamiento}
                previous = list(locked.fragmentos.values_list('id', flat=True))
                if previous and cls._has_citations(previous):
                    raise RuntimeError('La versión tiene fragmentos citados; no puede re-segmentarse (INV-04).')
                FragmentoDocumento.objects.filter(id__in=previous).delete()
                created = FragmentoDocumento.objects.bulk_create([
                    FragmentoDocumento(
                        version_documento=locked, orden=c.orden, pagina_inicio=c.pagina_inicio,
                        pagina_fin=c.pagina_fin, contenido=c.contenido,
                    )
                    for c in chunks
                ])
                FaissVectorStore.add_vectors(
                    modelo_embedding=modelo_embedding, fragment_ids=[f.id for f in created], vectors=vectors,
                )
                previous_model = locked.modelo_embedding
                locked.procesamiento = ProcesamientoDocumento.PENDIENTE_AUTORIZACION
                locked.modelo_embedding = modelo_embedding
                locked.version_segmentacion = build_segmentation_label(chunk_size, chunk_overlap)
                locked.error_procesamiento = None
                locked.save(update_fields=[
                    'procesamiento', 'modelo_embedding', 'version_segmentacion', 'error_procesamiento', 'ultima_modificacion',
                ])
            if previous:
                FaissVectorStore.remove_vectors(modelo_embedding=previous_model or modelo_embedding, fragment_ids=previous)
            return {'status': 'ok', 'version_id': version.id, 'chunks': len(created)}

        except Exception as exc:
            message = f'{type(exc).__name__}: {exc}'[:MAX_ERROR_CHARS]
            VersionDocumento.objects.filter(pk=version.pk).update(
                procesamiento=ProcesamientoDocumento.ERROR, activa=False, error_procesamiento=message, ultima_modificacion=timezone.now(),
            )
            return {'status': 'error', 'version_id': version.id, 'error': message}

    @classmethod
    def reindex_version(cls, version_documento_id: int) -> dict:
        """Re-vectoriza los fragmentos existentes con el modelo vigente conservando sus IDs (citas intactas)."""
        version = VersionDocumento.objects.get(id=version_documento_id)
        cfg = get_active_ai_config()
        _, modelo_embedding, _ = resolve_embedding_settings(cfg)
        fragmentos = list(version.fragmentos.order_by('orden').values_list('id', 'contenido'))
        try:
            if not fragmentos:
                raise ValueError('La versión no tiene fragmentos para re-indexar.')
            vectors = EmbeddingProviderService.embed_texts([contenido for _, contenido in fragmentos], cfg)
            FaissVectorStore.add_vectors(
                modelo_embedding=modelo_embedding, fragment_ids=[fid for fid, _ in fragmentos], vectors=vectors,
            )
            VersionDocumento.objects.filter(pk=version.pk).update(
                modelo_embedding=modelo_embedding, error_procesamiento=None, ultima_modificacion=timezone.now(),
            )
            return {'status': 'ok', 'version_id': version.id, 'chunks': len(fragmentos), 'modelo_embedding': modelo_embedding}
        except Exception as exc:
            message = f'Re-indexación fallida: {type(exc).__name__}: {exc}'[:MAX_ERROR_CHARS]
            VersionDocumento.objects.filter(pk=version.pk).update(error_procesamiento=message, ultima_modificacion=timezone.now())
            return {'status': 'error', 'version_id': version.id, 'error': message}

    # ------------------------------------------------------------------
    # Gobernanza (acciones del Administrador)
    # ------------------------------------------------------------------
    @staticmethod
    def _lock(version: VersionDocumento) -> VersionDocumento:
        return VersionDocumento.objects.select_for_update().select_related('documento').get(pk=version.pk)

    @staticmethod
    def _deactivate_siblings(version: VersionDocumento) -> list[str]:
        siblings = VersionDocumento.objects.filter(documento_id=version.documento_id, activa=True).exclude(pk=version.pk)
        labels = list(siblings.values_list('version', flat=True))
        siblings.update(activa=False, ultima_modificacion=timezone.now())
        return labels

    @classmethod
    @transaction.atomic
    def authorize(cls, actor, version: VersionDocumento) -> VersionDocumento:
        version = cls._lock(version)
        if version.procesamiento not in PROCESAMIENTOS_INDEXADOS:
            raise ValidationError({'procesamiento': msg.AUTORIZAR_NO_PROCESADA.format(estado=version.procesamiento)})
        reemplazadas = cls._deactivate_siblings(version)
        version.procesamiento = ProcesamientoDocumento.AUTORIZADO
        version.autorizada_por = actor
        version.autorizada_en = timezone.now()
        version.activa = True
        version.save(update_fields=['procesamiento', 'autorizada_por', 'autorizada_en', 'activa', 'ultima_modificacion'])
        AuditService.log(
            actor=actor, accion=AccionAuditoria.AUTORIZAR_ACTIVAR_VERSION_DOCUMENTO, version_documento=version,
            detalle=f'codigo={version.documento.codigo} version={version.version} reemplaza={",".join(reemplazadas) or "-"}',
        )
        return version

    @classmethod
    @transaction.atomic
    def activate(cls, actor, version: VersionDocumento) -> VersionDocumento:
        version = cls._lock(version)
        if version.procesamiento != ProcesamientoDocumento.AUTORIZADO:
            raise ValidationError({'procesamiento': msg.REACTIVAR_NO_AUTORIZADA})
        if version.activa:
            return version
        reemplazadas = cls._deactivate_siblings(version)
        version.activa = True
        version.save(update_fields=['activa', 'ultima_modificacion'])
        AuditService.log(
            actor=actor, accion=AccionAuditoria.ACTIVAR_VERSION_DOCUMENTO, version_documento=version,
            detalle=f'codigo={version.documento.codigo} version={version.version} reemplaza={",".join(reemplazadas) or "-"}',
        )
        return version

    @classmethod
    @transaction.atomic
    def deactivate(cls, actor, version: VersionDocumento) -> VersionDocumento:
        version = cls._lock(version)
        if not version.activa:
            return version
        version.activa = False
        version.save(update_fields=['activa', 'ultima_modificacion'])
        AuditService.log(
            actor=actor, accion=AccionAuditoria.DESACTIVAR_VERSION_DOCUMENTO, version_documento=version,
            detalle=f'codigo={version.documento.codigo} version={version.version} (fragmentos y citas preservados)',
        )
        return version

    @classmethod
    @transaction.atomic
    def retry(cls, actor, version: VersionDocumento) -> VersionDocumento:
        version = cls._lock(version)
        if version.procesamiento not in (ProcesamientoDocumento.ERROR, ProcesamientoDocumento.PENDIENTE_AUTORIZACION):
            raise ValidationError({'procesamiento': msg.REPROCESAR_ESTADO_INVALIDO})
        if version.autorizada_en is not None:
            raise ValidationError({'procesamiento': msg.REPROCESAR_AUTORIZADA})
        version.procesamiento = ProcesamientoDocumento.PROCESANDO
        version.error_procesamiento = None
        version.save(update_fields=['procesamiento', 'error_procesamiento', 'ultima_modificacion'])
        AuditService.log(
            actor=actor, accion=AccionAuditoria.REPROCESAR_VERSION_DOCUMENTO, version_documento=version,
            detalle=f'codigo={version.documento.codigo} version={version.version}',
        )
        cls.enqueue_processing(version)
        return version

    @classmethod
    @transaction.atomic
    def request_reindex(cls, actor, version: VersionDocumento) -> VersionDocumento:
        from apps.documents_rag.tasks import reindex_version_task

        version = cls._lock(version)
        if version.procesamiento not in PROCESAMIENTOS_INDEXADOS:
            raise ValidationError({'procesamiento': msg.REINDEXAR_NO_PROCESADA})
        _, modelo_actual, _ = resolve_embedding_settings(get_active_ai_config())
        AuditService.log(
            actor=actor, accion=AccionAuditoria.REINDEXAR_VERSION_DOCUMENTO, version_documento=version,
            detalle=f'codigo={version.documento.codigo} version={version.version} '
                    f'modelo_anterior={version.modelo_embedding} modelo_nuevo={modelo_actual}',
        )
        version_id = version.id
        transaction.on_commit(lambda: reindex_version_task.delay(version_id))
        return version
