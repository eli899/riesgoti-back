import re
import zlib
from unittest import mock

import numpy as np
import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APIClient

from apps.accounts.models import Usuario

SEED_PASSWORD = 'RiesgoTI2026!'
ADMIN_EMAIL = 'carla.mendoza@empresa.pe'
ADMIN_2_EMAIL = 'diego.vargas@empresa.pe'
ANALISTA_EMAIL = 'andrea.quispe@empresa.pe'
REPORTANTE_EMAIL = 'lucia.ramirez@empresa.pe'


class FakeSentenceTransformer:
    """Embeddings deterministas (bolsa de palabras con hashing) para no descargar modelos en las pruebas."""

    dim = 64

    def encode(self, sentences, **kwargs):
        texts = [sentences] if isinstance(sentences, str) else list(sentences)
        vectors = np.zeros((len(texts), self.dim), dtype='float32')
        for row, text in enumerate(texts):
            for token in re.findall(r'\w+', text.lower()):
                vectors[row, zlib.crc32(token.encode()) % self.dim] += 1.0
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.where(norms == 0, 1, norms)


@pytest.fixture(scope='session')
def _isolated_storage(tmp_path_factory):
    root = tmp_path_factory.mktemp('storage')
    override = override_settings(
        PDF_STORAGE_ROOT=root / 'pdfs', FAISS_INDEX_ROOT=root / 'faiss_indices', EVIDENCE_STORAGE_ROOT=root / 'evidences',
    )
    override.enable()
    yield root
    override.disable()


@pytest.fixture(scope='session')
def _offline_ai_and_celery():
    patchers = [
        mock.patch('apps.documents_rag.embeddings._load_sentence_transformer', return_value=FakeSentenceTransformer()),
        # Las tareas se ejecutan explícitamente en cada prueba; nada se envía a Redis.
        mock.patch('apps.documents_rag.tasks.process_pdf_version_task.delay'),
        mock.patch('apps.documents_rag.tasks.reindex_version_task.delay'),
        mock.patch('apps.risks.tasks.run_operational_rag_task.delay'),
        mock.patch('apps.risks.tasks.run_strategic_risk_task.delay'),
    ]
    for patcher in patchers:
        patcher.start()
    yield
    for patcher in patchers:
        patcher.stop()


@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker, _isolated_storage, _offline_ai_and_celery):
    with django_db_blocker.unblock():
        call_command('seed_riesgoti', verbosity=0)


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


def _client_for(correo: str) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=Usuario.objects.get(correo=correo))
    return client


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def admin_client(db) -> APIClient:
    return _client_for(ADMIN_EMAIL)


@pytest.fixture
def analista_client(db) -> APIClient:
    return _client_for(ANALISTA_EMAIL)


@pytest.fixture
def reportante_client(db) -> APIClient:
    return _client_for(REPORTANTE_EMAIL)


@pytest.fixture
def admin_user(db) -> Usuario:
    return Usuario.objects.get(correo=ADMIN_EMAIL)
