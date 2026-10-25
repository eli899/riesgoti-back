"""Precarga del modelo de embeddings al arrancar el servidor (hallazgo H-01, CHG-0023)."""
from unittest import mock

import pytest

from apps.ai_config import services
from apps.ai_config.services import PRELOAD_EMBEDDING_MODEL_ENV, preload_embedding_model

MODEL = 'sentence-transformers/paraphrase-multilingual-mpnet-base-v2'
RUNSERVER = ['manage.py', 'runserver', '0.0.0.0:8000']


@pytest.fixture
def loader():
    with mock.patch.object(services, '_load_sentence_transformer') as patched:
        yield patched


def test_sin_variable_no_precarga(loader):
    assert preload_embedding_model(RUNSERVER, {'RUN_MAIN': 'true'}) is False
    loader.assert_not_called()


@pytest.mark.parametrize('argv', [['manage.py', 'migrate', '--noinput'], ['manage.py', 'seed_riesgoti'], ['pytest']])
def test_solo_precarga_en_runserver(loader, argv):
    assert preload_embedding_model(argv, {PRELOAD_EMBEDDING_MODEL_ENV: MODEL, 'RUN_MAIN': 'true'}) is False
    loader.assert_not_called()


def test_no_precarga_en_el_proceso_vigilante_del_autoreload(loader):
    assert preload_embedding_model(RUNSERVER, {PRELOAD_EMBEDDING_MODEL_ENV: MODEL}) is False
    loader.assert_not_called()


def test_precarga_en_el_proceso_que_sirve(loader):
    assert preload_embedding_model(RUNSERVER, {PRELOAD_EMBEDDING_MODEL_ENV: MODEL, 'RUN_MAIN': 'true'}) is True
    loader.assert_called_once_with(MODEL)


def test_precarga_con_noreload(loader):
    assert preload_embedding_model([*RUNSERVER, '--noreload'], {PRELOAD_EMBEDDING_MODEL_ENV: f' {MODEL} '}) is True
    loader.assert_called_once_with(MODEL)


def test_un_fallo_de_carga_no_impide_arrancar(loader):
    loader.side_effect = OSError('sin red')
    assert preload_embedding_model(RUNSERVER, {PRELOAD_EMBEDDING_MODEL_ENV: MODEL, 'RUN_MAIN': 'true'}) is False
