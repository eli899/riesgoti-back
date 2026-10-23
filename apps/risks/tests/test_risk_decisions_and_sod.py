import pytest

from apps.assets_matrix.models import Activo, ConfiguracionMatriz
from apps.audit.models import EventoAuditoria
from apps.incidents.models import Incidencia
from apps.risks.models import CitaVersionRiesgo, DecisionRiesgo, EvaluacionRiesgo, VersionIncidencia, VersionRiesgo

pytestmark = pytest.mark.django_db

BASE = '/api/v1/risk-versions/'
ERP_TITLE = 'Degradación del servicio del ERP Contable'
PHISHING_V2 = 'Suplantación de identidad por correo con adjuntos maliciosos'
BACKUP_TITLE = 'Pérdida de información por falla en copias de respaldo'


def _version(titulo: str) -> VersionRiesgo:
    return VersionRiesgo.objects.get(titulo=titulo)


def _analisis_id(version: VersionRiesgo, titulo_incidencia: str) -> int:
    return VersionIncidencia.objects.get(version=version, analisis__tarea__incidencia__titulo=titulo_incidencia).analisis_id


def _grilla(nivel='ALTO'):
    return [{'probabilidad': p, 'impacto': i, 'nivel_codigo': nivel} for p in range(1, 6) for i in range(1, 6)]


def _confirm_and_evaluate(client, version, *, p=4, i=3, activo='ACT-001'):
    activo_id = Activo.objects.get(codigo=activo).id
    assert client.post(f'{BASE}{version.id}/confirm-grouping/', {'activo_confirmado_id': activo_id}, format='json').status_code == 200
    response = client.post(f'{BASE}{version.id}/evaluate/', {
        'probabilidad': p, 'impacto': i,
        'justificacion': 'Ocurrencia recurrente durante el cierre contable afectando la disponibilidad del ERP.',
    }, format='json')
    assert response.status_code == 200, response.json()
    return response.json()


# ---------------------------------------------------------------------------
# DoD 1: Segregación de Funciones (INV-05)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('method,suffix,payload', [
    ('post', 'decision/', {'accion': 'RECHAZADA', 'observacion': 'Intento de decisión del administrador.'}),
    ('post', 'evaluate/', {'probabilidad': 4, 'impacto': 3, 'justificacion': 'Intento de evaluación del administrador.'}),
    ('post', 'confirm-grouping/', {'activo_confirmado_id': 1}),
])
def test_admin_recibe_403_en_evaluacion_y_decision(admin_client, method, suffix, payload):
    version = _version(ERP_TITLE)
    response = getattr(admin_client, method)(f'{BASE}{version.id}/{suffix}', payload, format='json')
    assert response.status_code == 403
    assert not DecisionRiesgo.objects.filter(version=version).exists()


def test_admin_puede_consultar_en_modo_lectura_y_reportante_no(admin_client, reportante_client):
    assert admin_client.get(BASE).status_code == 200
    assert admin_client.get('/api/v1/risks/dashboard/').status_code == 200
    assert reportante_client.get(BASE).status_code == 403
    assert reportante_client.get('/api/v1/risks/dashboard/').status_code == 403


def test_admin_no_puede_retirar_falsos_positivos(admin_client):
    version = _version(ERP_TITLE)
    analisis = _analisis_id(version, 'Impresora lenta al imprimir reportes')
    response = admin_client.patch(f'{BASE}{version.id}/incidents/{analisis}/remove/', {'motivo_retiro': 'Motivo suficiente.'}, format='json')
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Depuración de la agrupación
# ---------------------------------------------------------------------------
def test_retiro_de_falso_positivo_conserva_la_fila(analista_client):
    version = _version(ERP_TITLE)
    analisis = _analisis_id(version, 'Impresora lenta al imprimir reportes')
    url = f'{BASE}{version.id}/incidents/{analisis}/remove/'

    assert analista_client.patch(url, {'motivo_retiro': 'corto'}, format='json').status_code == 400
    response = analista_client.patch(url, {
        'motivo_retiro': 'Falso positivo: coincidencia por lentitud, pero el activo afectado es una impresora.',
    }, format='json')

    assert response.status_code == 200
    fila = next(i for i in response.json()['incidencias'] if i['analisis_id'] == analisis)
    assert fila['estado'] == 'RETIRADA' and fila['revisada_por_nombre'] == 'Andrea Quispe' and 'impresora' in fila['motivo_retiro']
    assert VersionIncidencia.objects.filter(version=version, analisis_id=analisis).exists()
    assert response.json()['total_incidencias_incluidas'] == 8
    assert EventoAuditoria.objects.filter(accion='RETIRAR_INCIDENCIA_AGRUPACION', version_riesgo=version).exists()
    assert analista_client.patch(url, {'motivo_retiro': 'Segundo intento de retiro.'}, format='json').status_code == 400

    restaurada = analista_client.patch(f'{BASE}{version.id}/incidents/{analisis}/restore/', {}, format='json').json()
    assert next(i for i in restaurada['incidencias'] if i['analisis_id'] == analisis)['estado'] == 'SUGERIDA'


def test_confirmar_agrupacion_exige_justificar_cambio_de_activo(analista_client):
    version = _version(ERP_TITLE)
    vpn = Activo.objects.get(codigo='ACT-003')
    url = f'{BASE}{version.id}/confirm-grouping/'

    assert analista_client.post(url, {'activo_confirmado_id': vpn.id}, format='json').status_code == 400
    inactivo = Activo.objects.get(codigo='ACT-007')
    assert analista_client.post(url, {'activo_confirmado_id': inactivo.id}, format='json').status_code == 400

    body = analista_client.post(url, {'activo_confirmado_id': Activo.objects.get(codigo='ACT-001').id}, format='json').json()
    assert body['agrupacion_confirmada'] is True and body['activo_confirmado_nombre'] == 'ERP Contable'
    assert {i['estado'] for i in body['incidencias']} == {'CONFIRMADA'}
    assert body['agrupacion_confirmada_por_nombre'] == 'Andrea Quispe'


def test_retirar_tras_confirmar_reinicia_la_confirmacion(analista_client):
    version = _version(ERP_TITLE)
    analista_client.post(f'{BASE}{version.id}/confirm-grouping/', {'activo_confirmado_id': Activo.objects.get(codigo='ACT-001').id}, format='json')
    analisis = _analisis_id(version, 'Impresora lenta al imprimir reportes')
    body = analista_client.patch(f'{BASE}{version.id}/incidents/{analisis}/remove/',
                                 {'motivo_retiro': 'El activo afectado es una impresora.'}, format='json').json()
    assert body['agrupacion_confirmada'] is False


# ---------------------------------------------------------------------------
# Evaluación 5x5 y DoD 3 (INV-04)
# ---------------------------------------------------------------------------
def test_evaluacion_resuelve_la_celda_de_la_matriz_activa(analista_client):
    body = _confirm_and_evaluate(analista_client, _version(ERP_TITLE), p=4, i=3)
    assert body['nivel_codigo'] == 'ALTO' and body['probabilidad'] == 4 and body['impacto'] == 3
    assert body['matriz_version'] == ConfiguracionMatriz.objects.get(activa=True).version
    assert body['evaluador_nombre'] == 'Andrea Quispe'


def test_publicar_nueva_matriz_no_altera_celda_historica(analista_client, admin_client):
    version = _version(ERP_TITLE)
    celda_original = _confirm_and_evaluate(analista_client, version, p=4, i=3)['celda_id']

    admin_client.post('/api/v1/admin/matrices/publish/', {'celdas': _grilla('CRITICO')}, format='json')

    evaluacion = EvaluacionRiesgo.objects.select_related('celda__nivel', 'celda__matriz').get(version=version)
    assert evaluacion.celda_id == celda_original and evaluacion.celda.nivel.codigo == 'ALTO'
    assert evaluacion.celda.matriz.activa is False
    seed_eval = EvaluacionRiesgo.objects.get(version__titulo='Acceso remoto no autorizado a la VPN')
    assert seed_eval.celda.matriz.activa is False  # Las evaluaciones semilla también conservan su celda.

    reevaluada = analista_client.post(f'{BASE}{version.id}/evaluate/', {
        'probabilidad': 4, 'impacto': 3, 'justificacion': 'Reevaluación con la nueva matriz corporativa publicada.',
    }, format='json').json()
    assert reevaluada['celda_id'] != celda_original and reevaluada['nivel_codigo'] == 'CRITICO'


# ---------------------------------------------------------------------------
# Decisiones ISO/IEC 27005 (DoD 2)
# ---------------------------------------------------------------------------
def test_validar_exige_agrupacion_y_evaluacion(analista_client):
    version = _version(ERP_TITLE)
    response = analista_client.post(f'{BASE}{version.id}/decision/', {'accion': 'VALIDADA'}, format='json')
    assert response.status_code == 400 and 'agrupacion' in response.json()

    analista_client.post(f'{BASE}{version.id}/confirm-grouping/', {'activo_confirmado_id': Activo.objects.get(codigo='ACT-001').id}, format='json')
    response = analista_client.post(f'{BASE}{version.id}/decision/', {'accion': 'VALIDADA'}, format='json')
    assert response.status_code == 400 and 'evaluacion' in response.json()


def test_validar_sin_citas_exige_justificacion_sin_fuentes(analista_client):
    version = _version(BACKUP_TITLE)
    assert not CitaVersionRiesgo.objects.filter(version=version).exists()
    _confirm_and_evaluate(analista_client, version, p=3, i=4, activo='ACT-005')
    url = f'{BASE}{version.id}/decision/'

    response = analista_client.post(url, {'accion': 'VALIDADA', 'justificacion_sin_fuentes': ''}, format='json')
    assert response.status_code == 400 and 'justificacion_sin_fuentes' in response.json()

    response = analista_client.post(url, {
        'accion': 'VALIDADA', 'justificacion_sin_fuentes': 'No existe aún una política de respaldo publicada; se valida por evidencia operativa.',
    }, format='json')
    assert response.status_code == 200
    assert response.json()['estado'] == 'VALIDADA' and response.json()['decision']['analista_nombre'] == 'Andrea Quispe'


def test_validar_con_citas_y_version_inmutable(analista_client):
    version = _version(ERP_TITLE)
    _confirm_and_evaluate(analista_client, version)
    url = f'{BASE}{version.id}/decision/'

    response = analista_client.post(url, {'accion': 'VALIDADA', 'observacion': 'Coherente con POL-CONT-01.'}, format='json')
    assert response.status_code == 200 and response.json()['estado'] == 'VALIDADA'
    assert EventoAuditoria.objects.filter(accion='DECIDIR_VERSION_RIESGO', version_riesgo=version).exists()

    assert analista_client.post(url, {'accion': 'RECHAZADA', 'observacion': 'Cambio de opinión posterior.'}, format='json').status_code == 400
    assert analista_client.post(f'{BASE}{version.id}/evaluate/', {
        'probabilidad': 1, 'impacto': 1, 'justificacion': 'Intento de reevaluar una versión decidida.',
    }, format='json').status_code == 400


def test_rechazar_exige_observacion(analista_client):
    version = _version(BACKUP_TITLE)
    url = f'{BASE}{version.id}/decision/'
    assert analista_client.post(url, {'accion': 'RECHAZADA', 'observacion': 'corta'}, format='json').status_code == 400
    response = analista_client.post(url, {'accion': 'RECHAZADA', 'observacion': 'No constituye un riesgo de seguridad.'}, format='json')
    assert response.status_code == 200 and response.json()['estado'] == 'RECHAZADA'


def test_corregir_crea_nueva_version_del_analista(analista_client):
    version = _version(ERP_TITLE)
    analista_client.post(f'{BASE}{version.id}/confirm-grouping/', {'activo_confirmado_id': Activo.objects.get(codigo='ACT-001').id}, format='json')

    response = analista_client.post(f'{BASE}{version.id}/decision/', {
        'accion': 'CORREGIDA', 'observacion': 'La vulnerabilidad real es la falta de monitoreo de capacidad.',
        'vulnerabilidad': 'Ausencia de monitoreo de capacidad con umbrales de alerta',
    }, format='json')

    assert response.status_code == 201
    nueva = response.json()
    assert nueva['numero'] == version.numero + 1 and nueva['origen'] == 'ANALISTA' and nueva['estado'] == 'PENDIENTE'
    assert nueva['vulnerabilidad'] == 'Ausencia de monitoreo de capacidad con umbrales de alerta'
    assert nueva['titulo'] == version.titulo and nueva['version_anterior_id'] == version.id
    assert nueva['agrupacion_confirmada'] is True and nueva['activo_confirmado_nombre'] == 'ERP Contable'
    assert len(nueva['incidencias']) == version.incidencias_vinculadas.count()
    assert len(nueva['citas']) == 2 and nueva['tiene_citas_estrategicas'] is True
    assert DecisionRiesgo.objects.get(version=version).accion == 'CORREGIDA'

    _confirm_and_evaluate(analista_client, VersionRiesgo.objects.get(pk=nueva['id']))
    validada = analista_client.post(f"{BASE}{nueva['id']}/decision/", {'accion': 'VALIDADA'}, format='json')
    assert validada.status_code == 200


def test_corregir_exige_al_menos_un_campo(analista_client):
    version = _version(ERP_TITLE)
    response = analista_client.post(f'{BASE}{version.id}/decision/', {
        'accion': 'CORREGIDA', 'observacion': 'Observación suficiente para corregir.',
    }, format='json')
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Bandejas, semillas y DoD 4 (tablero)
# ---------------------------------------------------------------------------
def test_bandejas_de_propuestas(analista_client):
    nuevas = {v['titulo']: v for v in analista_client.get(BASE, {'bandeja': 'nuevas'}).json()}
    assert {ERP_TITLE, PHISHING_V2, BACKUP_TITLE} <= set(nuevas)
    assert nuevas[PHISHING_V2]['posible_recurrencia'] is True and nuevas[ERP_TITLE]['posible_recurrencia'] is False
    assert [v['riesgo_codigo'] for v in analista_client.get(BASE, {'bandeja': 'rechazadas'}).json()] == ['RSG-0004']
    decididas = {v['estado'] for v in analista_client.get(BASE, {'bandeja': 'decididas'}).json()}
    assert decididas == {'VALIDADA', 'CORREGIDA', 'RECHAZADA'}
    historial = analista_client.get(BASE, {'riesgo_id': _version(PHISHING_V2).riesgo_id, 'ordering': '-numero'}).json()
    assert [v['numero'] for v in historial] == [2, 1]


def test_citas_de_documento_desactivado_se_preservan_inv04(analista_client):
    rechazada = analista_client.get(BASE, {'bandeja': 'rechazadas'}).json()[0]
    cita = rechazada['citas'][0]
    assert cita['documento_codigo'] == 'MAN-EST-01' and cita['documento_activo'] is False and cita['pagina_inicio'] == 4


def test_detalle_de_incidencia_muestra_riesgo_vinculado(analista_client):
    incidencia = Incidencia.objects.get(titulo='ERP muy lento al registrar facturas')
    vinculos = analista_client.get(f'/api/v1/incidents/{incidencia.id}/').json()['riesgos_vinculados']
    assert vinculos[0]['riesgo_codigo'] == _version(ERP_TITLE).riesgo.codigo and vinculos[0]['estado_vinculo'] == 'SUGERIDA'


def test_dashboard_cuenta_solo_la_ultima_version_validada(analista_client):
    body = analista_client.get('/api/v1/risks/dashboard/').json()

    assert body['total_riesgos'] == 5 and body['total_riesgos_vigentes'] == 2  # RSG-0002 (v1) y RSG-0003 (v2)
    por_nivel = {n['nivel_codigo']: n['total'] for n in body['riesgos_vigentes_por_nivel']}
    assert por_nivel == {'BAJO': 0, 'MEDIO': 0, 'ALTO': 0, 'CRITICO': 2}
    registro = {r['titulo']: r for r in body['registro_riesgos']}
    assert set(registro) == {'Suplantación de identidad por correo electrónico', 'Acceso remoto no autorizado a la VPN'}
    phishing = registro['Suplantación de identidad por correo electrónico']
    assert phishing['version_vigente_numero'] == 1 and phishing['propuesta_pendiente_numero'] == 2
    assert registro['Acceso remoto no autorizado a la VPN']['version_vigente_numero'] == 2
    assert body['propuestas_pendientes'] == 3 and body['propuestas_posible_recurrencia'] == 1
    assert body['versiones_rechazadas'] == 1
    assert sum(body['incidencias_por_estado'].values()) == Incidencia.objects.count()
    assert len(body['serie_incidencias']) == 30


def test_dashboard_no_duplica_un_riesgo_revalidado(analista_client):
    version = _version(PHISHING_V2)
    analista_client.post(f'{BASE}{version.id}/confirm-grouping/', {'activo_confirmado_id': Activo.objects.get(codigo='ACT-002').id}, format='json')
    analista_client.post(f'{BASE}{version.id}/evaluate/', {
        'probabilidad': 5, 'impacto': 4, 'justificacion': 'Recurrencia con adjuntos maliciosos en el último mes.',
    }, format='json')
    assert analista_client.post(f'{BASE}{version.id}/decision/', {'accion': 'VALIDADA'}, format='json').status_code == 200

    body = analista_client.get('/api/v1/risks/dashboard/').json()
    phishing = [r for r in body['registro_riesgos'] if r['riesgo_id'] == version.riesgo_id]
    assert len(phishing) == 1 and phishing[0]['version_vigente_numero'] == 2 and phishing[0]['propuesta_pendiente_id'] is None
    assert body['total_riesgos_vigentes'] == 2
