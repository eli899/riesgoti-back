import pytest

from apps.assets_matrix.models import Activo, CeldaMatriz, ConfiguracionMatriz, TipoActivo
from apps.audit.models import EventoAuditoria

pytestmark = pytest.mark.django_db


def _nivel(p: int, i: int) -> str:
    score = p * i
    if score >= 15:
        return 'CRITICO'
    if score >= 9:
        return 'ALTO'
    if score >= 4:
        return 'MEDIO'
    return 'BAJO'


def _grilla(override: dict | None = None) -> list[dict]:
    override = override or {}
    return [
        {'probabilidad': p, 'impacto': i, 'nivel_codigo': override.get((p, i), _nivel(p, i))}
        for p in range(1, 6) for i in range(1, 6)
    ]


# ---------------------------------------------------------------------------
# Catálogo de activos
# ---------------------------------------------------------------------------
def test_reportante_solo_ve_activos_vigentes(reportante_client):
    response = reportante_client.get('/api/v1/assets/')
    assert response.status_code == 200
    codigos = {a['codigo'] for a in response.json()}
    assert 'ACT-007' not in codigos  # Intranet antigua (inactiva)
    assert 'ACT-001' in codigos
    assert all('tipo_nombre' in a for a in response.json())


def test_admin_ve_activos_inactivos(admin_client):
    codigos = {a['codigo'] for a in admin_client.get('/api/v1/assets/').json()}
    assert 'ACT-007' in codigos


def test_admin_crea_activo_y_audita(admin_client):
    tipo = TipoActivo.objects.get(nombre='Servidor')
    response = admin_client.post('/api/v1/assets/', {
        'tipo_id': tipo.id, 'codigo': 'act-100', 'nombre': 'Servidor de base de datos', 'criticidad': 4,
    }, format='json')

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body['codigo'] == 'ACT-100' and body['tipo_nombre'] == 'Servidor'
    assert EventoAuditoria.objects.filter(accion='CREAR_ACTIVO', activo_id=body['id']).exists()


@pytest.mark.parametrize('criticidad', [0, 5])
def test_criticidad_fuera_de_rango(admin_client, criticidad):
    tipo = TipoActivo.objects.first()
    response = admin_client.post('/api/v1/assets/', {
        'tipo_id': tipo.id, 'codigo': 'ACT-101', 'nombre': 'Activo X', 'criticidad': criticidad,
    }, format='json')
    assert response.status_code == 400


def test_desactivar_activo_registra_evento_especifico(admin_client):
    activo = Activo.objects.get(codigo='ACT-004')
    response = admin_client.patch(f'/api/v1/assets/{activo.id}/', {'activo': False}, format='json')

    assert response.status_code == 200
    assert response.json()['activo'] is False
    assert EventoAuditoria.objects.filter(accion='DESACTIVAR_ACTIVO', activo_id=activo.id).exists()


def test_reportante_no_puede_crear_ni_editar_activos(reportante_client):
    activo = Activo.objects.get(codigo='ACT-001')
    assert reportante_client.post('/api/v1/assets/', {}, format='json').status_code == 403
    assert reportante_client.patch(f'/api/v1/assets/{activo.id}/', {'nombre': 'X'}, format='json').status_code == 403


def test_activo_referenciado_no_se_elimina(admin_client, reportante_client):
    """CHG-0035: DELETE existe, pero un activo con referencias históricas responde 409 y debe desactivarse."""
    activo = Activo.objects.get(codigo='ACT-001')
    assert admin_client.delete(f'/api/v1/assets/{activo.id}/').status_code == 409
    assert reportante_client.delete(f'/api/v1/assets/{activo.id}/').status_code == 403
    assert Activo.objects.filter(pk=activo.pk).exists()


# ---------------------------------------------------------------------------
# Tipos de activo (CHG-0039)
# ---------------------------------------------------------------------------
TIPOS_URL = '/api/v1/asset-types/'


def test_admin_crea_edita_y_desactiva_tipo_de_activo_con_auditoria(admin_client, reportante_client):
    creado = admin_client.post(TIPOS_URL, {'nombre': '  Base de   datos '}, format='json')
    assert creado.status_code == 201, creado.json()
    body = creado.json()
    assert body['nombre'] == 'Base de datos' and body['activo'] is True and body['total_activos'] == 0

    editado = admin_client.patch(f"{TIPOS_URL}{body['id']}/", {'nombre': 'Base de datos corporativa'}, format='json')
    assert editado.status_code == 200 and editado.json()['nombre'] == 'Base de datos corporativa'
    assert admin_client.patch(f"{TIPOS_URL}{body['id']}/", {'activo': False}, format='json').json()['activo'] is False

    acciones = set(EventoAuditoria.objects.values_list('accion', flat=True))
    assert {'CREAR_TIPO_ACTIVO', 'ACTUALIZAR_TIPO_ACTIVO', 'DESACTIVAR_TIPO_ACTIVO'} <= acciones
    # Los usuarios sin activo.administrar solo ven tipos vigentes; el administrador ve todos.
    assert body['id'] not in [t['id'] for t in reportante_client.get(TIPOS_URL).json()]
    assert body['id'] in [t['id'] for t in admin_client.get(TIPOS_URL).json()]


def test_tipo_de_activo_rechaza_nombre_duplicado(admin_client):
    existente = TipoActivo.objects.first()
    response = admin_client.post(TIPOS_URL, {'nombre': existente.nombre.upper()}, format='json')
    assert response.status_code == 400 and 'nombre' in response.json()


def test_tipo_de_activo_en_uso_no_se_elimina_y_uno_libre_si(admin_client):
    en_uso = Activo.objects.select_related('tipo').first().tipo
    assert admin_client.delete(f'{TIPOS_URL}{en_uso.id}/').status_code == 409
    libre = admin_client.post(TIPOS_URL, {'nombre': 'Tipo temporal'}, format='json').json()
    assert admin_client.delete(f"{TIPOS_URL}{libre['id']}/").status_code == 204
    assert not TipoActivo.objects.filter(pk=libre['id']).exists()
    assert EventoAuditoria.objects.filter(accion='ELIMINAR_TIPO_ACTIVO').exists()


def test_reportante_no_administra_tipos_de_activo(reportante_client):
    tipo = TipoActivo.objects.first()
    assert reportante_client.post(TIPOS_URL, {'nombre': 'X'}, format='json').status_code == 403
    assert reportante_client.patch(f'{TIPOS_URL}{tipo.id}/', {'nombre': 'X'}, format='json').status_code == 403
    assert reportante_client.delete(f'{TIPOS_URL}{tipo.id}/').status_code == 403


# ---------------------------------------------------------------------------
# Matriz 5x5
# ---------------------------------------------------------------------------
def test_matriz_activa_completa(analista_client):
    response = analista_client.get('/api/v1/matrices/active/')
    assert response.status_code == 200
    body = response.json()
    assert len(body['celdas']) == 25
    assert len(body['criterios_probabilidad']) == 5 and len(body['criterios_impacto']) == 5
    assert [n['codigo'] for n in body['niveles']] == ['BAJO', 'MEDIO', 'ALTO', 'CRITICO']
    celda = next(c for c in body['celdas'] if c['probabilidad'] == 4 and c['impacto'] == 3)
    assert celda['nivel_codigo'] == 'ALTO'


def test_publicar_matriz_es_inmutable_y_preserva_celdas_historicas(admin_client):
    anterior = ConfiguracionMatriz.objects.get(activa=True)
    celdas_previas = dict(CeldaMatriz.objects.filter(matriz=anterior).values_list('id', 'nivel__codigo'))

    response = admin_client.post('/api/v1/admin/matrices/publish/', {
        'nombre': 'Matriz corporativa ISO 27005', 'celdas': _grilla({(1, 1): 'MEDIO'}),
    }, format='json')

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body['activa'] is True and body['estado'] == 'PUBLICADA'
    assert body['version'] == f'v{ConfiguracionMatriz.objects.count()}.0'
    assert len(body['celdas']) == 25
    assert next(c for c in body['celdas'] if c['probabilidad'] == 1 and c['impacto'] == 1)['nivel_codigo'] == 'MEDIO'
    # Criterios clonados de la matriz anterior.
    assert [c['nombre'] for c in body['criterios_probabilidad']][0] == 'Rara'

    anterior.refresh_from_db()
    assert anterior.activa is False
    assert ConfiguracionMatriz.objects.filter(activa=True).count() == 1
    # INV-04: las celdas de la matriz anterior (referenciadas por EVALUACION_RIESGO) no cambian.
    assert dict(CeldaMatriz.objects.filter(matriz=anterior).values_list('id', 'nivel__codigo')) == celdas_previas
    assert not set(c['id'] for c in body['celdas']) & set(celdas_previas)
    assert EventoAuditoria.objects.filter(accion='PUBLICAR_CONFIGURACION_MATRIZ', matriz_id=body['id']).exists()


def test_publicar_matriz_con_criterios_explicitos(admin_client):
    criterios = [{'valor': v, 'nombre': f'Nivel {v}'} for v in range(1, 6)]
    response = admin_client.post('/api/v1/admin/matrices/publish/', {
        'criterios_probabilidad': criterios, 'criterios_impacto': criterios, 'celdas': _grilla(),
    }, format='json')
    assert response.status_code == 201
    assert response.json()['criterios_impacto'][4]['nombre'] == 'Nivel 5'


@pytest.mark.parametrize('celdas', [
    _grilla()[:24],
    _grilla()[:24] + [{'probabilidad': 1, 'impacto': 1, 'nivel_codigo': 'BAJO'}],
    _grilla()[:24] + [{'probabilidad': 6, 'impacto': 5, 'nivel_codigo': 'BAJO'}],
    _grilla()[:24] + [{'probabilidad': 5, 'impacto': 5, 'nivel_codigo': 'EXTREMO'}],
])
def test_publicar_matriz_rechaza_grillas_invalidas(admin_client, celdas):
    total_antes = ConfiguracionMatriz.objects.count()
    response = admin_client.post('/api/v1/admin/matrices/publish/', {'celdas': celdas}, format='json')
    assert response.status_code == 400
    assert ConfiguracionMatriz.objects.count() == total_antes


def test_solo_matriz_administrar_puede_publicar(analista_client):
    response = analista_client.post('/api/v1/admin/matrices/publish/', {'celdas': _grilla()}, format='json')
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Auditoría
# ---------------------------------------------------------------------------
def test_bitacora_de_auditoria_filtrable(admin_client):
    admin_client.post('/api/v1/admin/matrices/publish/', {'celdas': _grilla()}, format='json')

    response = admin_client.get('/api/v1/admin/audit-events/', {'accion': 'PUBLICAR_CONFIGURACION_MATRIZ'})

    assert response.status_code == 200
    body = response.json()
    assert body['count'] >= 1
    assert all(e['accion'] == 'PUBLICAR_CONFIGURACION_MATRIZ' for e in body['results'])
    assert body['results'][0]['actor_correo'] == 'carla.mendoza@empresa.pe'


def test_primera_matriz_se_publica_con_criterios_cuando_no_hay_activa(admin_client, analista_client):
    """CHG-0039: con la semilla base no existe matriz; el administrador publica la inicial desde la aplicación."""
    ConfiguracionMatriz.objects.update(activa=False)
    assert analista_client.get('/api/v1/matrices/active/').status_code == 404
    criterios = [{'valor': v, 'nombre': f'Nivel {v}'} for v in range(1, 6)]
    sin_criterios = admin_client.post('/api/v1/admin/matrices/publish/', {'celdas': _grilla()}, format='json')
    assert sin_criterios.status_code == 400

    response = admin_client.post('/api/v1/admin/matrices/publish/', {
        'nombre': 'Matriz inicial', 'criterios_probabilidad': criterios, 'criterios_impacto': criterios, 'celdas': _grilla(),
    }, format='json')

    assert response.status_code == 201, response.json()
    activa = analista_client.get('/api/v1/matrices/active/').json()
    assert activa['nombre'] == 'Matriz inicial' and len(activa['celdas']) == 25
