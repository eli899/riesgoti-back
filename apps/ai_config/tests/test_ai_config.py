from unittest import mock

import pytest

from apps.ai_config.crypto import EnvelopeCryptoService
from apps.ai_config.models import ConfiguracionIARAG
from apps.audit.models import EventoAuditoria
from apps.documents_rag.models import Documento, VersionDocumento

pytestmark = pytest.mark.django_db

VALID_PAYLOAD = {
    'proveedor_llm': 'GEMINI',
    'modelo_llm': 'gemini-2.5-flash',
    'endpoint_base_llm': '',
    'api_key_llm': 'AIzaSyDemoKey987654321',
    'proveedor_embedding': 'SENTENCE_TRANSFORMERS',
    'modelo_embedding': 'sentence-transformers/paraphrase-multilingual-mpnet-base-v2',
    'chunk_size': 800,
    'chunk_overlap': 120,
    'top_k': 4,
    'umbral_similitud': 0.72,
}


# ---------------------------------------------------------------------------
# AES-256-GCM
# ---------------------------------------------------------------------------
def test_aes_gcm_roundtrip_y_mascara():
    enc, mask = EnvelopeCryptoService.encrypt_api_key('sk-proj-1234567890abcdef')
    assert EnvelopeCryptoService.decrypt_api_key(enc) == 'sk-proj-1234567890abcdef'
    assert mask == 'sk-pro...cdef'
    assert 'sk-proj' not in enc


def test_aes_gcm_iv_aleatorio_y_formato_binario():
    import base64

    enc_1, _ = EnvelopeCryptoService.encrypt_api_key('misma-llave-123456')
    enc_2, _ = EnvelopeCryptoService.encrypt_api_key('misma-llave-123456')
    assert enc_1 != enc_2
    # IV(12) || AuthTag(16) || Ciphertext(len plaintext)
    assert len(base64.b64decode(enc_1)) == 12 + 16 + len('misma-llave-123456')


def test_aes_gcm_detecta_manipulacion():
    import base64

    from cryptography.exceptions import InvalidTag

    raw = bytearray(base64.b64decode(EnvelopeCryptoService.encrypt_api_key('sk-proj-1234567890abcdef')[0]))
    raw[-1] ^= 0x01
    with pytest.raises(InvalidTag):
        EnvelopeCryptoService.decrypt_api_key(base64.b64encode(bytes(raw)).decode())


# ---------------------------------------------------------------------------
# GET / PUT /api/v1/admin/ai-config/
# ---------------------------------------------------------------------------
def test_get_config_activa_no_expone_llaves_cifradas(admin_client):
    response = admin_client.get('/api/v1/admin/ai-config/')
    assert response.status_code == 200
    body = response.json()
    assert body['proveedor_llm'] == 'GEMINI'
    assert not any(key.endswith('_cifrada') for key in body)
    assert 'api_key_llm' not in body


def test_put_publica_nueva_version_cifrada_y_auditada(admin_client):
    previa = ConfiguracionIARAG.objects.get(activa=True)

    response = admin_client.put('/api/v1/admin/ai-config/', VALID_PAYLOAD, format='json')

    assert response.status_code == 200, response.json()
    body = response.json()
    assert body['api_key_llm_mascara'] == 'AIzaSy...4321'
    assert body['umbral_similitud'] == 0.72
    assert body['requiere_reindexacion_documentos'] is False
    assert 'api_key_llm' not in body and 'api_key_llm_cifrada' not in body

    nueva = ConfiguracionIARAG.objects.get(pk=body['id'])
    assert nueva.activa and nueva.pk != previa.pk
    assert EnvelopeCryptoService.decrypt_api_key(nueva.api_key_llm_cifrada) == 'AIzaSyDemoKey987654321'
    previa.refresh_from_db()
    assert previa.activa is False
    assert ConfiguracionIARAG.objects.filter(activa=True).count() == 1
    assert EventoAuditoria.objects.filter(accion='ACTUALIZAR_CONFIG_IA_RAG').exists()
    assert 'AIzaSyDemoKey987654321' not in EventoAuditoria.objects.filter(accion='ACTUALIZAR_CONFIG_IA_RAG').first().detalle


def test_put_sin_api_key_conserva_la_llave_anterior(admin_client):
    admin_client.put('/api/v1/admin/ai-config/', VALID_PAYLOAD, format='json')
    response = admin_client.put('/api/v1/admin/ai-config/', {**VALID_PAYLOAD, 'api_key_llm': '', 'top_k': 6}, format='json')

    assert response.status_code == 200
    assert response.json()['api_key_llm_mascara'] == 'AIzaSy...4321'
    nueva = ConfiguracionIARAG.objects.get(activa=True)
    assert nueva.top_k == 6
    assert EnvelopeCryptoService.decrypt_api_key(nueva.api_key_llm_cifrada) == 'AIzaSyDemoKey987654321'


@pytest.mark.parametrize('size,overlap', [(800, 400), (800, 500), (256, 128)])
def test_put_rechaza_overlap_mayor_o_igual_a_la_mitad(admin_client, size, overlap):
    response = admin_client.put('/api/v1/admin/ai-config/', {**VALID_PAYLOAD, 'chunk_size': size, 'chunk_overlap': overlap}, format='json')
    assert response.status_code == 400
    assert 'chunk_overlap' in response.json()


def test_put_detecta_versiones_documentales_desfasadas(admin_client, admin_user):
    documento = Documento.objects.create(codigo='POL-SGSI-01', titulo='Política SGSI')
    version = VersionDocumento.objects.create(
        documento=documento, version='v1.0', clave_archivo='pdfs/pol.pdf', sha256='a' * 64, cargada_por=admin_user,
        procesamiento='AUTORIZADO', activa=True, modelo_embedding='sentence-transformers/paraphrase-multilingual-mpnet-base-v2',
    )

    response = admin_client.put('/api/v1/admin/ai-config/', {
        **VALID_PAYLOAD, 'proveedor_embedding': 'OPENAI', 'modelo_embedding': 'text-embedding-3-small',
    }, format='json')

    body = response.json()
    assert body['requiere_reindexacion_documentos'] is True
    # Incluye también las versiones semilla autorizadas (d1, d2) indexadas con el modelo anterior.
    assert {
        'id': version.id, 'codigo': 'POL-SGSI-01', 'version': 'v1.0',
        'modelo_embedding': 'sentence-transformers/paraphrase-multilingual-mpnet-base-v2',
    } in body['versiones_desfasadas']


def test_ai_config_requiere_documento_administrar(analista_client, reportante_client):
    assert analista_client.get('/api/v1/admin/ai-config/').status_code == 403
    assert reportante_client.put('/api/v1/admin/ai-config/', VALID_PAYLOAD, format='json').status_code == 403


# ---------------------------------------------------------------------------
# POST /api/v1/admin/ai-config/test-connection/
# ---------------------------------------------------------------------------
def test_test_connection_reporta_estado_por_componente(admin_client):
    from apps.ai_config.services import AIConnectionTester

    with mock.patch.object(AIConnectionTester, '_ping_llm', return_value=None), \
            mock.patch.object(AIConnectionTester, '_ping_embedding', return_value=768):
        response = admin_client.post('/api/v1/admin/ai-config/test-connection/', {'api_key_llm': 'AIzaSyTemporal1234'}, format='json')

    assert response.status_code == 200
    body = response.json()
    assert body['llm_status'] == 'ok' and body['llm_provider'] == 'GEMINI'
    assert body['embedding_status'] == 'ok' and body['embedding_dimensions'] == 768
    assert EventoAuditoria.objects.filter(accion='PROBAR_CONEXION_IA').exists()


def test_test_connection_error_de_proveedor_no_filtra_secretos(admin_client):
    from apps.ai_config.services import AIConnectionTester

    def falla(*args, **kwargs):
        raise RuntimeError('401 invalid key AIzaSyTemporal1234')

    with mock.patch.object(AIConnectionTester, '_ping_llm', side_effect=falla), \
            mock.patch.object(AIConnectionTester, '_ping_embedding', return_value=768):
        response = admin_client.post('/api/v1/admin/ai-config/test-connection/', {'api_key_llm': 'AIzaSyTemporal1234'}, format='json')

    body = response.json()
    assert body['llm_status'] == 'error'
    assert 'AIzaSyTemporal1234' not in body['llm_error']
    assert 'AIzaSy...1234' in body['llm_error']
