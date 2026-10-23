import pytest
from django.core.management import call_command

from apps.ai_config.models import ConfiguracionIARAG
from apps.assets_matrix.models import CeldaMatriz, ConfiguracionMatriz

pytestmark = pytest.mark.django_db


def _grilla(nivel: str = 'ALTO') -> list[dict]:
    return [{'probabilidad': p, 'impacto': i, 'nivel_codigo': nivel} for p in range(1, 6) for i in range(1, 6)]


def test_reejecutar_seed_conserva_la_matriz_publicada_y_sus_celdas_historicas(admin_client):
    semilla = ConfiguracionMatriz.objects.get(version='v1.0')
    publicada = admin_client.post('/api/v1/admin/matrices/publish/', {'celdas': _grilla()}, format='json').json()
    # Simula una celda histórica divergente de la fórmula semilla: el seed no debe reescribirla.
    CeldaMatriz.objects.filter(matriz=semilla, probabilidad=1, impacto=1).update(nivel_id=publicada['celdas'][0]['nivel_id'])
    celdas_semilla = dict(CeldaMatriz.objects.filter(matriz=semilla).values_list('id', 'nivel__codigo'))

    call_command('seed_riesgoti', verbosity=0)

    activas = list(ConfiguracionMatriz.objects.filter(activa=True))
    assert [m.id for m in activas] == [publicada['id']]
    semilla.refresh_from_db()
    assert semilla.activa is False
    assert dict(CeldaMatriz.objects.filter(matriz=semilla).values_list('id', 'nivel__codigo')) == celdas_semilla


def test_reejecutar_seed_conserva_la_configuracion_ia_vigente(admin_client):
    admin_client.put('/api/v1/admin/ai-config/', {
        'proveedor_llm': 'OPENAI', 'modelo_llm': 'gpt-4o-mini', 'api_key_llm': 'sk-proj-1234567890abcdef',
        'proveedor_embedding': 'OPENAI', 'modelo_embedding': 'text-embedding-3-small',
        'chunk_size': 1000, 'chunk_overlap': 100, 'top_k': 5, 'umbral_similitud': 0.75,
    }, format='json')
    vigente = ConfiguracionIARAG.objects.get(activa=True)

    call_command('seed_riesgoti', verbosity=0)

    assert list(ConfiguracionIARAG.objects.filter(activa=True)) == [vigente]
    default = ConfiguracionIARAG.objects.get(version_configuracion='v1.0-default')
    assert default.activa is False and default.proveedor_llm == 'GEMINI'
