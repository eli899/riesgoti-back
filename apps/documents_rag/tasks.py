from celery import shared_task

from apps.documents_rag.services import DocumentIngestionService


@shared_task(name='documents_rag.process_pdf_version')
def process_pdf_version_task(version_documento_id: int) -> dict:
    """PDF -> Markdown por página -> chunks con trazabilidad -> embeddings L2 -> FAISS. Errores quedan en la versión."""
    return DocumentIngestionService.process_version(version_documento_id)


@shared_task(name='documents_rag.reindex_version')
def reindex_version_task(version_documento_id: int) -> dict:
    """Re-vectoriza los fragmentos existentes con el modelo de embeddings vigente (IDs y citas intactos)."""
    return DocumentIngestionService.reindex_version(version_documento_id)
