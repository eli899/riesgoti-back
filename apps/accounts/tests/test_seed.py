from unittest import mock

import pytest
from django.core.management import call_command

from apps.accounts.models import Rol, Usuario
from apps.ai_config.models import ConfiguracionIARAG
from apps.assets_matrix.models import CeldaMatriz, ConfiguracionMatriz, NivelRiesgo

pytestmark = pytest.mark.django_db


def _grilla(nivel: str = 'ALTO') -> list[dict]:
    return [{'probabilidad': p, 'impacto': i, 'nivel_codigo': nivel} for p in range(1, 6) for i in range(1, 6)]


def test_reejecutar_seed_conserva_la_matriz_publicada_y_sus_celdas_historicas(admin_client):
    semilla = ConfiguracionMatriz.objects.get(version='v1.0')
    publicada = admin_client.post('/api/v1/admin/matrices/publish/', {'celdas': _grilla()}, format='json').json()
    # Simula una celda histórica divergente de la fórmula semilla: el seed no debe reescribirla.
    CeldaMatriz.objects.filter(matriz=semilla, probabilidad=1, impacto=1).update(nivel_id=publicada['celdas'][0]['nivel_id'])
    celdas_semilla = dict(CeldaMatriz.objects.filter(matriz=semilla).values_list('id', 'nivel__codigo'))

    call_command('seed_riesgoti', '--demo', verbosity=0)

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

    call_command('seed_riesgoti', '--demo', verbosity=0)

    assert list(ConfiguracionIARAG.objects.filter(activa=True)) == [vigente]
    default = ConfiguracionIARAG.objects.get(version_configuracion='v1.0-default')
    assert default.activa is False and default.proveedor_llm == 'GEMINI'


def test_seed_base_solo_carga_roles_permisos_usuarios_y_niveles():
    """CHG-0039: sin --demo no se crean catálogos ni datos de negocio; se registran desde la aplicación."""
    modulo = 'apps.accounts.management.commands.seed_riesgoti'
    with (
        mock.patch(f'{modulo}.seed_documents') as documentos,
        mock.patch(f'{modulo}.seed_incidents') as incidencias,
        mock.patch(f'{modulo}.seed_risks') as riesgos,
        mock.patch(f'{modulo}.Command._seed_activos') as activos,
        mock.patch(f'{modulo}.Command._seed_matriz') as matriz,
        mock.patch(f'{modulo}.Command._seed_configuracion_ia') as configuracion_ia,
    ):
        call_command('seed_riesgoti', verbosity=0)

    for llamada in (documentos, incidencias, riesgos, activos, matriz, configuracion_ia):
        llamada.assert_not_called()
    assert set(NivelRiesgo.objects.values_list('codigo', flat=True)) == {'BAJO', 'MEDIO', 'ALTO', 'CRITICO'}
    assert Rol.objects.filter(codigo__in=['REPORTANTE', 'ANALISTA', 'ADMIN']).count() == 3
    assert Usuario.objects.filter(correo='carla.mendoza@empresa.pe', activo=True).exists()
