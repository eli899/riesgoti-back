from decimal import Decimal

import numpy as np
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.ai_config.models import ConfiguracionIARAG
from apps.audit.models import EventoAuditoria
from apps.documents_rag.chunking import StructuredMarkdownPDFChunker
from apps.documents_rag.embeddings import EmbeddingProviderService
from apps.documents_rag.faiss_store import FINALIDADES_OPERATIVAS, FaissVectorStore
from apps.documents_rag.models import FragmentoDocumento, VersionDocumento
from apps.documents_rag.seed_documents import build_pdf_bytes
from apps.documents_rag.services import DocumentIngestionService
from apps.documents_rag.tasks import process_pdf_version_task
from apps.risks.models import CitaVersionRiesgo, Riesgo, VersionRiesgo

pytestmark = pytest.mark.django_db

BASE_URL = '/api/v1/admin/document-versions/'
MFA_TEXT = 'Toda conexión VPN exige autenticación multifactor con token físico para el personal externo.'


def _pdf(pages: dict, total: int, name: str = 'politica.pdf') -> SimpleUploadedFile:
    return SimpleUploadedFile(name, build_pdf_bytes(pages, total), content_type='application/pdf')


def _vpn_pdf(extra: str = '') -> SimpleUploadedFile:
    return _pdf({
        1: [('h1', 'Política de acceso remoto'), ('p', 'Documento de prueba para la red privada virtual.' + extra)],
        2: [('h2', '2. Autenticación'), ('p', MFA_TEXT)],
        3: [('h2', '3. Registro'), ('p', 'Los accesos deben quedar registrados en la bitácora central.')],
    }, 3)


def _upload(client, *, codigo='POL-VPN-01', version='v1.0', finalidad='AMBAS', archivo=None):
    return client.post(BASE_URL + 'upload/', {
        'codigo': codigo, 'titulo': 'Política de acceso remoto VPN', 'version': version,
        'finalidad': finalidad, 'archivo': archivo or _vpn_pdf(),
    }, format='multipart')


def _uploaded_and_processed(client, **kwargs) -> VersionDocumento:
    response = _upload(client, **kwargs)
    assert response.status_code == 201, response.json()
    result = process_pdf_version_task(response.json()['id'])
    assert result['status'] == 'ok', result
    return VersionDocumento.objects.get(pk=response.json()['id'])


# ---------------------------------------------------------------------------
# Chunking con trazabilidad de páginas
# ---------------------------------------------------------------------------
def test_chunker_conserva_jerarquia_prefijo_y_paginas():
    pages = [
        (1, '# Política de continuidad\n\nIntroducción general del documento normativo.'),
        (2, '## 2. Monitoreo\n\nLos servicios críticos deben tener umbrales de alerta.'),
        (3, 'Continuación del monitoreo en la página siguiente.'),
    ]
    chunks = StructuredMarkdownPDFChunker.chunk_pages(pages, doc_codigo='POL-CONT-01', doc_version='v2.2')

    assert [c.orden for c in chunks] == list(range(1, len(chunks) + 1))
    assert chunks[0].contenido.startswith('[Documento: POL-CONT-01 v2.2 | Sección: Política de continuidad]')
    monitoreo = next(c for c in chunks if 'umbrales de alerta' in c.contenido)
    assert 'Sección: Política de continuidad > 2. Monitoreo]' in monitoreo.contenido
    # La sección cruza de la página 2 a la 3: el fragmento refleja el rango real.
    assert (monitoreo.pagina_inicio, monitoreo.pagina_fin) == (2, 3)
    assert 'RIESGOTI_PAGE' not in ''.join(c.contenido for c in chunks)


def test_chunker_divide_secciones_largas_y_calcula_rangos_por_offset():
    long_page_2 = '## Sección larga\n\n' + ' '.join(['palabra'] * 400)
    long_page_3 = ' '.join(['continuacion'] * 400)
    chunks = StructuredMarkdownPDFChunker.chunk_pages(
        [(2, long_page_2), (3, long_page_3)], doc_codigo='X', doc_version='1.0', chunk_size=256, chunk_overlap=32,
    )
    assert len(chunks) > 2
    assert chunks[0].contenido.startswith('[Documento: X v1.0 | Sección: Sección larga]')
    assert chunks[0].pagina_inicio == 2 and chunks[-1].pagina_fin == 3
    assert all(c.pagina_inicio <= c.pagina_fin for c in chunks)


def test_chunker_rechaza_pdf_sin_capa_de_texto():
    with pytest.raises(ValueError, match='capa de texto'):
        StructuredMarkdownPDFChunker.chunk_pages([(1, ''), (2, ' ')], doc_codigo='X', doc_version='v1')


def test_extraccion_real_pymupdf4llm_por_pagina(tmp_path):
    path = tmp_path / 'doc.pdf'
    path.write_bytes(_vpn_pdf().read())
    chunks = StructuredMarkdownPDFChunker.extract_and_chunk(pdf_path=str(path), doc_codigo='POL-VPN-01', doc_version='v1.0')
    mfa = next(c for c in chunks if 'multifactor' in c.contenido)
    assert (mfa.pagina_inicio, mfa.pagina_fin) == (2, 2)
    assert '2. Autenticación' in mfa.contenido


# ---------------------------------------------------------------------------
# Embeddings y FAISS
# ---------------------------------------------------------------------------
def test_embeddings_normalizados_l2():
    vectors = EmbeddingProviderService.embed_texts(['uno dos tres', 'cuatro'], None)
    assert vectors.dtype == np.float32
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)


def test_faiss_store_add_search_remove():
    modelo = 'pruebas/modelo-unitario'
    vectors = EmbeddingProviderService.embed_texts(['respaldo diario', 'antivirus actualizado'], None)
    FaissVectorStore.add_vectors(modelo_embedding=modelo, fragment_ids=[900001, 900002], vectors=vectors)
    FaissVectorStore.add_vectors(modelo_embedding=modelo, fragment_ids=[900001], vectors=vectors[:1])  # idempotente

    hits = FaissVectorStore.search(modelo_embedding=modelo, query_vector=vectors[1:2], k=5)
    assert hits[0][0] == 900002 and hits[0][1] == pytest.approx(1.0, abs=1e-5)
    assert FaissVectorStore.load(modelo).ntotal == 2

    FaissVectorStore.remove_vectors(modelo_embedding=modelo, fragment_ids=[900002])
    assert FaissVectorStore.load(modelo).ntotal == 1


def test_faiss_rechaza_dimension_incompatible():
    modelo = 'pruebas/dimension'
    FaissVectorStore.add_vectors(modelo_embedding=modelo, fragment_ids=[1], vectors=np.ones((1, 8), dtype='float32'))
    with pytest.raises(ValueError, match='Dimensión incompatible'):
        FaissVectorStore.add_vectors(modelo_embedding=modelo, fragment_ids=[2], vectors=np.ones((1, 4), dtype='float32'))


# ---------------------------------------------------------------------------
# Carga, procesamiento y gobernanza vía API
# ---------------------------------------------------------------------------
def test_upload_crea_version_procesando_y_encola_tarea(admin_client, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = _upload(admin_client)

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body['procesamiento'] == 'PROCESANDO' and body['activa'] is False
    assert body['codigo'] == 'POL-VPN-01' and len(body['sha256']) == 64
    process_pdf_version_task.delay.assert_called_with(body['id'])
    assert EventoAuditoria.objects.filter(accion='CARGAR_VERSION_DOCUMENTO', version_documento_id=body['id']).exists()


@pytest.mark.parametrize('archivo,campo', [
    (SimpleUploadedFile('falso.pdf', b'MZ\x90\x00 no soy un pdf', content_type='application/pdf'), 'archivo'),
    (SimpleUploadedFile('notas.txt', b'%PDF-1.7 texto', content_type='text/plain'), 'archivo'),
])
def test_upload_rechaza_archivos_no_pdf(admin_client, archivo, campo):
    response = _upload(admin_client, archivo=archivo)
    assert response.status_code == 400
    assert campo in response.json()


def test_upload_rechaza_version_o_archivo_duplicado(admin_client):
    contenido = _vpn_pdf().read()  # PyMuPDF incrusta ID/fecha: se reutilizan los mismos bytes.

    def mismo_pdf():
        return SimpleUploadedFile('politica.pdf', contenido, content_type='application/pdf')

    assert _upload(admin_client, archivo=mismo_pdf()).status_code == 201
    assert 'version' in _upload(admin_client, archivo=_vpn_pdf(' otra')).json()
    assert 'archivo' in _upload(admin_client, version='v2.0', archivo=mismo_pdf()).json()


def test_pipeline_completo_fragmentos_faiss_y_preview(admin_client):
    version = _uploaded_and_processed(admin_client)

    assert version.procesamiento == 'PENDIENTE_AUTORIZACION'
    assert version.version_segmentacion == 'md-v1-cs800-co120'
    assert version.modelo_embedding == ConfiguracionIARAG.objects.get(activa=True).modelo_embedding
    ids = list(version.fragmentos.values_list('id', flat=True))
    index = FaissVectorStore.load(version.modelo_embedding)
    assert all(index.reconstruct(int(i)) is not None for i in ids)

    preview = admin_client.get(f'{BASE_URL}{version.id}/preview/').json()
    assert preview['total_fragmentos'] == len(ids)
    mfa = next(f for f in preview['fragmentos'] if 'multifactor' in f['contenido'])
    assert mfa['pagina_inicio'] == 2 and mfa['contenido'].startswith('[Documento: POL-VPN-01 v1.0 | Sección:')


def test_pdf_sin_texto_queda_en_error_con_mensaje(admin_client):
    response = _upload(admin_client, archivo=_pdf({}, 2, 'escaneado.pdf'))
    result = process_pdf_version_task(response.json()['id'])

    assert result['status'] == 'error'
    version = VersionDocumento.objects.get(pk=response.json()['id'])
    assert version.procesamiento == 'ERROR' and version.activa is False
    assert 'capa de texto' in version.error_procesamiento
    assert admin_client.get(f'{BASE_URL}{version.id}/').json()['error_procesamiento']


def test_retry_reprocesa_version_en_error(admin_client, django_capture_on_commit_callbacks):
    response = _upload(admin_client)
    VersionDocumento.objects.filter(pk=response.json()['id']).update(procesamiento='ERROR', error_procesamiento='timeout')

    with django_capture_on_commit_callbacks(execute=True):
        retry = admin_client.post(f"{BASE_URL}{response.json()['id']}/retry/")

    assert retry.status_code == 202 and retry.json()['procesamiento'] == 'PROCESANDO'
    assert process_pdf_version_task(response.json()['id'])['status'] == 'ok'


def test_autorizar_activa_y_reemplaza_version_anterior(admin_client):
    v1 = _uploaded_and_processed(admin_client)
    assert admin_client.post(f'{BASE_URL}{v1.id}/authorize/').json()['activa'] is True
    v2 = _uploaded_and_processed(admin_client, version='v2.0', archivo=_vpn_pdf(' Revisión 2026.'))

    body = admin_client.post(f'{BASE_URL}{v2.id}/authorize/').json()

    assert body['procesamiento'] == 'AUTORIZADO' and body['activa'] is True
    assert body['autorizada_por_nombre'] == 'Carla Mendoza'
    v1.refresh_from_db()
    assert v1.activa is False and v1.procesamiento == 'AUTORIZADO'
    assert EventoAuditoria.objects.filter(accion='AUTORIZAR_ACTIVAR_VERSION_DOCUMENTO', version_documento_id=v2.id).exists()


def test_no_se_autoriza_una_version_en_procesamiento(admin_client):
    response = _upload(admin_client)
    assert admin_client.post(f"{BASE_URL}{response.json()['id']}/authorize/").status_code == 400


def test_retry_prohibido_en_version_autorizada(admin_client):
    version = _uploaded_and_processed(admin_client)
    admin_client.post(f'{BASE_URL}{version.id}/authorize/')
    assert admin_client.post(f'{BASE_URL}{version.id}/retry/').status_code == 400


# ---------------------------------------------------------------------------
# Retriever filtrado e INV-04
# ---------------------------------------------------------------------------
def _relaxed_threshold():
    ConfiguracionIARAG.objects.filter(activa=True).update(umbral_similitud=Decimal('0.300'))


def test_retriever_solo_devuelve_fragmentos_autorizados_activos(admin_client):
    _relaxed_threshold()
    version = _uploaded_and_processed(admin_client)

    antes = FaissVectorStore.search_authorized_fragments(MFA_TEXT, FINALIDADES_OPERATIVAS)
    assert all(h.fragmento.version_documento_id != version.id for h in antes)  # aún no autorizada

    admin_client.post(f'{BASE_URL}{version.id}/authorize/')
    hits = FaissVectorStore.search_authorized_fragments(MFA_TEXT, FINALIDADES_OPERATIVAS)
    assert hits and 'multifactor' in hits[0].fragmento.contenido
    assert hits[0].fragmento.version_documento_id == version.id
    assert hits[0].score >= 0.3
    assert len(hits) <= ConfiguracionIARAG.objects.get(activa=True).top_k


def test_retriever_respeta_finalidad_y_umbral(admin_client):
    _relaxed_threshold()
    version = _uploaded_and_processed(admin_client, finalidad='ESTRATEGICA')
    admin_client.post(f'{BASE_URL}{version.id}/authorize/')

    hits = FaissVectorStore.search_authorized_fragments(MFA_TEXT, FINALIDADES_OPERATIVAS)
    assert all(h.fragmento.version_documento_id != version.id for h in hits)

    ConfiguracionIARAG.objects.filter(activa=True).update(umbral_similitud=Decimal('0.999'))
    assert FaissVectorStore.search_authorized_fragments('consulta sin relación alguna', ('ESTRATEGICA',)) == []


def test_desactivar_preserva_fragmentos_y_citas_inv04(admin_client, admin_user):
    _relaxed_threshold()
    version = _uploaded_and_processed(admin_client)
    admin_client.post(f'{BASE_URL}{version.id}/authorize/')
    fragmento = version.fragmentos.first()
    riesgo_version = VersionRiesgo.objects.create(
        riesgo=Riesgo.objects.create(codigo='R-TEST'), numero=1, creada_por=admin_user, titulo='Riesgo de prueba',
    )
    CitaVersionRiesgo.objects.create(version=riesgo_version, numero=1, fragmento=fragmento)
    total_fragmentos = version.fragmentos.count()

    response = admin_client.post(f'{BASE_URL}{version.id}/deactivate/')

    assert response.status_code == 200 and response.json()['activa'] is False
    assert version.fragmentos.count() == total_fragmentos
    assert CitaVersionRiesgo.objects.filter(fragmento=fragmento).exists()
    assert all(h.fragmento.version_documento_id != version.id
               for h in FaissVectorStore.search_authorized_fragments(MFA_TEXT, FINALIDADES_OPERATIVAS))
    assert EventoAuditoria.objects.filter(accion='DESACTIVAR_VERSION_DOCUMENTO', version_documento_id=version.id).exists()

    assert admin_client.post(f'{BASE_URL}{version.id}/activate/').json()['activa'] is True


def test_reprocesar_version_con_fragmentos_citados_falla_sin_borrarlos(admin_client, admin_user):
    version = _uploaded_and_processed(admin_client)
    fragmento = version.fragmentos.first()
    riesgo_version = VersionRiesgo.objects.create(
        riesgo=Riesgo.objects.create(codigo='R-TEST-2'), numero=1, creada_por=admin_user, titulo='Riesgo',
    )
    CitaVersionRiesgo.objects.create(version=riesgo_version, numero=1, fragmento=fragmento)
    VersionDocumento.objects.filter(pk=version.pk).update(procesamiento='PROCESANDO')

    result = DocumentIngestionService.process_version(version.id)

    assert result['status'] == 'error' and 'INV-04' in result['error']
    assert FragmentoDocumento.objects.filter(pk=fragmento.pk).exists()


def test_cambio_de_modelo_marca_reindexacion_y_reindex_conserva_ids(admin_client):
    version = _uploaded_and_processed(admin_client)
    admin_client.post(f'{BASE_URL}{version.id}/authorize/')
    ids_antes = sorted(version.fragmentos.values_list('id', flat=True))
    ConfiguracionIARAG.objects.filter(activa=True).update(modelo_embedding='pruebas/otro-modelo')

    listado = {v['id']: v for v in admin_client.get(BASE_URL).json()}
    assert listado[version.id]['requiere_reindexacion'] is True

    assert admin_client.post(f'{BASE_URL}{version.id}/reindex/').status_code == 202
    result = DocumentIngestionService.reindex_version(version.id)

    assert result['status'] == 'ok'
    version.refresh_from_db()
    assert version.modelo_embedding == 'pruebas/otro-modelo'
    assert sorted(version.fragmentos.values_list('id', flat=True)) == ids_antes
    assert FaissVectorStore.load('pruebas/otro-modelo').ntotal >= len(ids_antes)


def test_endpoints_documentales_requieren_documento_administrar(analista_client):
    assert analista_client.get(BASE_URL).status_code == 403
    assert _upload(analista_client).status_code == 403


# ---------------------------------------------------------------------------
# Semilla d1..d6
# ---------------------------------------------------------------------------
def test_seed_documental_refleja_estados_del_prototipo():
    estados = {
        v.documento.codigo: (v.procesamiento, v.activa)
        for v in VersionDocumento.objects.select_related('documento').filter(documento__codigo__in=[
            'POL-CONT-01', 'PRO-ACC-01', 'LIN-RESP-01', 'MAN-EST-01', 'GUI-CLAS-01', 'PLN-INC-01',
        ])
    }
    assert estados == {
        'POL-CONT-01': ('AUTORIZADO', True),
        'PRO-ACC-01': ('AUTORIZADO', True),
        'LIN-RESP-01': ('PENDIENTE_AUTORIZACION', False),
        'MAN-EST-01': ('AUTORIZADO', False),
        'GUI-CLAS-01': ('PROCESANDO', False),
        'PLN-INC-01': ('ERROR', False),
    }


def test_seed_documental_cita_paginas_del_prototipo():
    fragmentos = FragmentoDocumento.objects.filter(version_documento__documento__codigo='POL-CONT-01')
    capacidad = next(f for f in fragmentos if 'monitoreo de capacidad' in f.contenido)
    degradacion = next(f for f in fragmentos if 'causa raíz' in f.contenido)
    assert (capacidad.pagina_inicio, capacidad.pagina_fin) == (12, 12)
    assert (degradacion.pagina_inicio, degradacion.pagina_fin) == (14, 15)
