import time
from unittest import mock

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.accounts.models import Usuario
from apps.assets_matrix.models import Activo
from apps.audit.models import EventoAuditoria
from apps.documents_rag.models import FragmentoDocumento
from apps.incidents.models import AtencionIncidencia, EvidenciaIncidencia, Incidencia
from apps.incidents.services import IncidentService, evidence_absolute_path
from apps.risks.models import CitaOrientacion, OrientacionOperativa, PasoOrientacion, TareaIA
from conftest import ANALISTA_EMAIL, REPORTANTE_EMAIL

pytestmark = pytest.mark.django_db

BASE = '/api/v1/incidents/'
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64


def _client(correo: str) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=Usuario.objects.get(correo=correo))
    return client


def _payload(**extra) -> dict:
    return {
        'titulo': 'Error de conexión al guardar asiento en ERP',
        'descripcion': 'Al guardar un asiento contable aparece un timeout tras 60 segundos.',
        'activo_reportado_id': Activo.objects.get(codigo='ACT-001').id,
        **extra,
    }


def _create(client, **extra) -> dict:
    response = client.post(BASE, _payload(**extra), format='multipart')
    assert response.status_code == 201, response.json()
    return response.json()


def _deliver_guidance(incidencia_id: int, tipo: str = 'SUGERENCIA') -> OrientacionOperativa:
    """Simula lo que hará el worker operativo de v0.5."""
    tarea = TareaIA.objects.get(incidencia_id=incidencia_id, rama='OPERATIVA')
    tarea.estado = 'COMPLETADA'
    tarea.save(update_fields=['estado'])
    orientacion = OrientacionOperativa.objects.create(tarea=tarea, tipo=tipo, resumen='El ERP presenta timeouts.')
    PasoOrientacion.objects.create(orientacion=orientacion, orden=1, instruccion='Cierre sesión y vuelva a ingresar [1].')
    fragmento = FragmentoDocumento.objects.filter(version_documento__documento__codigo='POL-CONT-01').first()
    CitaOrientacion.objects.create(orientacion=orientacion, numero=1, fragmento=fragmento)
    return orientacion


# ---------------------------------------------------------------------------
# Registro transaccional (INV-01)
# ---------------------------------------------------------------------------
def test_reportante_registra_incidencia_con_evidencia_y_dos_tareas(reportante_client, django_capture_on_commit_callbacks):
    _create(reportante_client)  # Calentamiento: excluye del cronómetro la carga inicial de vistas y URLs del proceso.
    with mock.patch('apps.incidents.services.dispatch_ai_tasks') as dispatch, \
            django_capture_on_commit_callbacks(execute=True):
        started = time.perf_counter()
        body = _create(reportante_client, evidencias=[SimpleUploadedFile('captura.png', PNG, content_type='image/png')])
        elapsed = time.perf_counter() - started

    assert elapsed < 0.3, f'El registro tardó {elapsed:.3f}s (> 300 ms)'
    assert body['estado_actual'] == 'EN_ANALISIS'
    assert body['referencia'] == f"INC-{body['id']:04d}"
    assert body['activo_nombre'] == 'ERP Contable'
    assert [h['estado'] for h in body['historial']] == ['REGISTRADA', 'EN_ANALISIS']
    assert body['tareas_ia']['operativa']['estado'] == 'PENDIENTE'
    assert body['tareas_ia']['estrategica']['estado'] == 'PENDIENTE'
    dispatch.assert_called_once_with(body['tareas_ia']['operativa']['id'], body['tareas_ia']['estrategica']['id'])

    evidencia = EvidenciaIncidencia.objects.get(incidencia_id=body['id'])
    assert evidencia.tipo_mime == 'image/png' and evidencia.bytes == len(PNG) and len(evidencia.sha256) == 64
    assert evidence_absolute_path(evidencia.clave_archivo).read_bytes() == PNG
    tareas = TareaIA.objects.filter(incidencia_id=body['id'])
    assert {t.clave_idempotencia for t in tareas} == {f"inc-{body['id']}-op-v1", f"inc-{body['id']}-est-v1"}
    assert EventoAuditoria.objects.filter(accion='REGISTRAR_INCIDENCIA', incidencia_id=body['id']).exists()


def test_registro_encola_y_deja_tareas_pendientes_hasta_que_corra_el_worker(reportante_client, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        body = _create(reportante_client, activo_reportado_id='', activo_texto='Sistema de nómina')
    assert body['activo_reportado_id'] is None and body['activo_nombre'] == 'Sistema de nómina'
    assert set(TareaIA.objects.filter(incidencia_id=body['id']).values_list('estado', flat=True)) == {'PENDIENTE'}


def test_fallo_en_registro_no_deja_incidencia_ni_archivos(reportante_client, _isolated_storage):
    archivos_antes = set((_isolated_storage / 'evidences').rglob('*')) if (_isolated_storage / 'evidences').exists() else set()
    with mock.patch.object(IncidentService, '_new_task', side_effect=RuntimeError('fallo simulado')):
        with pytest.raises(RuntimeError):
            reportante_client.post(BASE, _payload(evidencias=[SimpleUploadedFile('a.png', PNG)]), format='multipart')
    assert not Incidencia.objects.filter(titulo=_payload()['titulo']).exists()
    archivos_despues = {p for p in (_isolated_storage / 'evidences').rglob('*') if p.is_file()}
    assert archivos_despues <= {p for p in archivos_antes if p.is_file()}


@pytest.mark.parametrize('payload,campo', [
    ({'titulo': 'Mal'}, 'titulo'),
    ({'descripcion': 'Muy corta'}, 'descripcion'),
    ({'activo_reportado_id': '', 'activo_texto': ''}, 'activo_reportado_id'),
    ({'evidencias': [SimpleUploadedFile('virus.exe', b'MZ')]}, 'evidencias'),
    ({'evidencias': [SimpleUploadedFile('falsa.png', b'GIF89a')]}, 'evidencias'),
    ({'evidencias': [SimpleUploadedFile('log.txt', b'texto\x00binario')]}, 'evidencias'),
])
def test_validaciones_de_registro(reportante_client, payload, campo):
    response = reportante_client.post(BASE, _payload(**payload), format='multipart')
    assert response.status_code == 400
    assert campo in response.json()


def test_activo_inactivo_no_se_puede_reportar(reportante_client):
    inactivo = Activo.objects.get(codigo='ACT-007')
    response = reportante_client.post(BASE, _payload(activo_reportado_id=inactivo.id), format='multipart')
    assert response.status_code == 400


def test_solo_reportante_puede_registrar(analista_client, admin_client):
    assert analista_client.post(BASE, _payload(), format='multipart').status_code == 403
    assert admin_client.post(BASE, _payload(), format='multipart').status_code == 403


# ---------------------------------------------------------------------------
# Visibilidad y bandejas
# ---------------------------------------------------------------------------
def test_reportante_solo_ve_sus_incidencias(reportante_client):
    propia = _create(reportante_client)
    ajena = _create(_client('jorge.salas@empresa.pe'))

    ids = {i['id'] for i in reportante_client.get(BASE).json()}
    assert propia['id'] in ids and ajena['id'] not in ids
    assert reportante_client.get(f"{BASE}{ajena['id']}/").status_code == 404
    assert reportante_client.get(f"{BASE}{ajena['id']}/operational-guidance/").status_code == 404


def test_analista_ve_todas_y_filtra_por_referencia_y_estado(analista_client, reportante_client):
    body = _create(reportante_client)
    assert analista_client.get(BASE, {'q': body['referencia']}).json()[0]['id'] == body['id']
    en_analisis = analista_client.get(BASE, {'estado': 'EN_ANALISIS'}).json()
    assert body['id'] in {i['id'] for i in en_analisis}
    assert all(i['estado_actual'] == 'EN_ANALISIS' for i in en_analisis)


def test_cola_n2_ordena_por_antiguedad_y_exige_ver_cola(analista_client, reportante_client):
    primera, segunda = _create(reportante_client), _create(reportante_client)
    for inc in (primera, segunda):
        IncidentService.transition(Incidencia.objects.get(pk=inc['id']), 'PENDIENTE_ATENCION_HUMANA',
                                   Usuario.objects.get(correo=REPORTANTE_EMAIL), 'Derivación de prueba')

    cola = analista_client.get(BASE, {'bandeja': 'atencion'}).json()
    ids = [i['id'] for i in cola]
    assert ids.index(primera['id']) < ids.index(segunda['id'])
    assert all(i['estado_actual'] in ('PENDIENTE_ATENCION_HUMANA', 'EN_ATENCION') for i in cola)
    assert reportante_client.get(BASE, {'bandeja': 'atencion'}).status_code == 403


def test_descarga_de_evidencia(reportante_client, analista_client):
    body = _create(reportante_client, evidencias=[SimpleUploadedFile('error.log', b'timeout 504\n')])
    evidencia_id = body['evidencias'][0]['id']

    response = analista_client.get(f"{BASE}{body['id']}/evidences/{evidencia_id}/download/")

    assert response.status_code == 200
    assert b''.join(response.streaming_content) == b'timeout 504\n'
    assert 'error.log' in response['Content-Disposition']


# ---------------------------------------------------------------------------
# Orientación operativa y feedback (INV-02)
# ---------------------------------------------------------------------------
def test_guidance_pendiente_y_luego_con_citas(reportante_client):
    body = _create(reportante_client)
    pendiente = reportante_client.get(f"{BASE}{body['id']}/operational-guidance/").json()
    assert pendiente['tarea_ia']['estado'] == 'PENDIENTE' and pendiente['orientacion'] is None

    _deliver_guidance(body['id'])
    guia = reportante_client.get(f"{BASE}{body['id']}/operational-guidance/").json()

    assert guia['tarea_ia']['estado'] == 'COMPLETADA'
    assert guia['orientacion']['pasos'][0]['instruccion'].endswith('[1].')
    cita = guia['orientacion']['citas'][0]
    assert cita['documento_codigo'] == 'POL-CONT-01' and cita['contenido'].startswith('[Documento: POL-CONT-01')
    assert guia['orientacion']['respuesta'] is None


def test_funciono_cierra_pero_no_toca_la_rama_estrategica(reportante_client):
    body = _create(reportante_client)
    _deliver_guidance(body['id'])
    estrategica = TareaIA.objects.get(incidencia_id=body['id'], rama='ESTRATEGICA')
    estrategica.estado = 'PROCESANDO'
    estrategica.save(update_fields=['estado'])

    response = reportante_client.post(f"{BASE}{body['id']}/orientation-feedback/", {'resultado': 'FUNCIONO'}, format='json')

    assert response.status_code == 200 and response.json()['estado_actual'] == 'CERRADA'
    estrategica.refresh_from_db()
    assert estrategica.estado == 'PROCESANDO'  # INV-02
    assert reportante_client.post(f"{BASE}{body['id']}/orientation-feedback/", {'resultado': 'NO_FUNCIONO'},
                                  format='json').status_code == 400


def test_no_funciono_escala_a_n2(reportante_client):
    body = _create(reportante_client)
    _deliver_guidance(body['id'])
    response = reportante_client.post(f"{BASE}{body['id']}/orientation-feedback/", {'resultado': 'NO_FUNCIONO'}, format='json')
    assert response.json()['estado_actual'] == 'PENDIENTE_ATENCION_HUMANA'
    assert response.json()['orientacion_resultado'] == 'NO_FUNCIONO'
    assert EventoAuditoria.objects.filter(accion='CONFIRMAR_ORIENTACION_OPERATIVA', incidencia_id=body['id']).exists()


def test_feedback_sin_sugerencia_o_de_otro_usuario_falla(reportante_client):
    body = _create(reportante_client)
    url = f"{BASE}{body['id']}/orientation-feedback/"
    assert reportante_client.post(url, {'resultado': 'FUNCIONO'}, format='json').status_code == 400  # aún sin orientación

    _deliver_guidance(body['id'], tipo='SIN_RESPALDO')
    assert reportante_client.post(url, {'resultado': 'FUNCIONO'}, format='json').status_code == 400
    otro = _client('jorge.salas@empresa.pe')
    assert otro.post(url, {'resultado': 'FUNCIONO'}, format='json').status_code == 404


# ---------------------------------------------------------------------------
# Atención humana N2 (INV-03)
# ---------------------------------------------------------------------------
def test_flujo_completo_de_atencion_n2(reportante_client, analista_client):
    body = _create(reportante_client)
    url = f"{BASE}{body['id']}"

    inicio = analista_client.post(f'{url}/start-attention/')
    assert inicio.status_code == 200 and inicio.json()['estado_actual'] == 'EN_ATENCION'
    assert analista_client.post(f'{url}/start-attention/').status_code == 200  # idempotente

    avance = analista_client.patch(f'{url}/attention/', {'acciones': 'Revisión de sesiones', 'cerrar': False}, format='json')
    assert avance.json()['estado_actual'] == 'EN_ATENCION'
    assert avance.json()['atencion']['acciones'] == 'Revisión de sesiones'

    with mock.patch('apps.documents_rag.faiss_store.FaissVectorStore.add_vectors') as add_vectors:
        cierre = analista_client.patch(f'{url}/attention/', {
            'acciones': 'Se liberaron bloqueos de sesión en la tabla contable.',
            'nota_resolucion': 'El usuario registró los asientos sin timeout.',
            'cerrar': True,
        }, format='json')
    add_vectors.assert_not_called()  # INV-03

    assert cierre.status_code == 200 and cierre.json()['estado_actual'] == 'CERRADA'
    assert AtencionIncidencia.objects.get(incidencia_id=body['id']).cerrada_en is not None
    estados = [h['estado'] for h in cierre.json()['historial']]
    assert estados == ['REGISTRADA', 'EN_ANALISIS', 'EN_ATENCION', 'CERRADA']
    assert EventoAuditoria.objects.filter(accion='CERRAR_ATENCION_HUMANA', incidencia_id=body['id']).exists()


def test_cierre_exige_notas_de_10_caracteres(reportante_client, analista_client):
    body = _create(reportante_client)
    analista_client.post(f"{BASE}{body['id']}/start-attention/")
    response = analista_client.patch(f"{BASE}{body['id']}/attention/",
                                     {'acciones': 'corto', 'nota_resolucion': '', 'cerrar': True}, format='json')
    assert response.status_code == 400
    assert set(response.json()) == {'acciones', 'nota_resolucion'}


def test_otro_analista_no_puede_tomar_ni_editar_un_caso_en_atencion(reportante_client, analista_client):
    body = _create(reportante_client)
    analista_client.post(f"{BASE}{body['id']}/start-attention/")
    otro = _client('martin.torres@empresa.pe')

    assert otro.post(f"{BASE}{body['id']}/start-attention/").status_code == 400
    assert otro.patch(f"{BASE}{body['id']}/attention/", {'acciones': 'x'}, format='json').status_code == 403


def test_atencion_requiere_rol_analista(reportante_client, admin_client):
    body = _create(reportante_client)
    assert reportante_client.post(f"{BASE}{body['id']}/start-attention/").status_code == 403
    assert admin_client.post(f"{BASE}{body['id']}/start-attention/").status_code == 403


def test_no_se_atiende_una_incidencia_cerrada(reportante_client, analista_client):
    body = _create(reportante_client)
    _deliver_guidance(body['id'])
    reportante_client.post(f"{BASE}{body['id']}/orientation-feedback/", {'resultado': 'FUNCIONO'}, format='json')
    assert analista_client.post(f"{BASE}{body['id']}/start-attention/").status_code == 400
    assert Usuario.objects.get(correo=ANALISTA_EMAIL).atenciones_asignadas.filter(incidencia_id=body['id']).count() == 0


# ---------------------------------------------------------------------------
# Semilla 1..17 (figma/src/data.ts)
# ---------------------------------------------------------------------------
def test_seed_reproduce_estados_del_prototipo(analista_client):
    from apps.incidents.seed_incidents import SEED_INCIDENTS

    seeded = {i['titulo']: i for i in analista_client.get(BASE).json()}
    for spec in SEED_INCIDENTS:
        assert seeded[spec.titulo]['estado_actual'] == spec.estado, spec.titulo

    cola = analista_client.get(BASE, {'bandeja': 'atencion'}).json()
    assert {'Tiempo de espera agotado en el ERP', 'Inicios de sesión VPN desde ubicación desconocida'} <= {i['titulo'] for i in cola}
    vpn = seeded['Inicios de sesión VPN desde ubicación desconocida']
    assert vpn['orientacion_tipo'] == 'SENSIBLE' and vpn['analista_nombre'] == 'Martín Torres'
    laptop = seeded['Laptop se reinicia sola']
    assert laptop['tarea_estrategica_estado'] == 'ERROR' and laptop['orientacion_resultado'] == 'NO_FUNCIONO'

    detalle = analista_client.get(f"{BASE}{seeded['ERP muy lento al registrar facturas']['id']}/").json()
    assert detalle['evidencias'][0]['nombre_original'] == 'captura-erp.png' and detalle['evidencias'][0]['bytes'] == 284000
    assert [h['estado'] for h in detalle['historial']] == [
        'REGISTRADA', 'EN_ANALISIS', 'PENDIENTE_ATENCION_HUMANA', 'EN_ATENCION', 'CERRADA',
    ]


# ---------------------------------------------------------------------------
# Orden del historial de estados (CHG-0007)
# ---------------------------------------------------------------------------
def test_transicion_queda_despues_de_un_historial_fechado_en_el_futuro(reportante_client):
    from datetime import timedelta

    from django.utils import timezone

    from apps.incidents.models import HistorialEstadoIncidencia

    body = _create(reportante_client)
    incidencia = Incidencia.objects.get(pk=body['id'])
    futuro = timezone.now() + timedelta(hours=5)
    HistorialEstadoIncidencia.objects.filter(incidencia=incidencia, estado='EN_ANALISIS').update(ocurrido_en=futuro)

    entry = IncidentService.transition(incidencia, 'PENDIENTE_ATENCION_HUMANA', incidencia.reportante, 'Derivación de prueba')

    assert entry.ocurrido_en > futuro
    assert IncidentService.get_current_status(Incidencia.objects.get(pk=incidencia.pk)) == 'PENDIENTE_ATENCION_HUMANA'


def test_transicion_es_monotonica_aunque_el_reloj_retroceda(reportante_client):
    from datetime import timedelta

    from django.utils import timezone

    body = _create(reportante_client)
    incidencia = Incidencia.objects.get(pk=body['id'])
    retrocedido = timezone.now() - timedelta(milliseconds=2)  # Simula un ajuste NTP hacia atrás.

    with mock.patch('django.utils.timezone.now', return_value=retrocedido):
        IncidentService.transition(incidencia, 'PENDIENTE_ATENCION_HUMANA', incidencia.reportante, 'Reloj retrocedido')

    historial = list(incidencia.historial_estados.order_by('ocurrido_en', 'id').values_list('estado', flat=True))
    assert historial == ['REGISTRADA', 'EN_ANALISIS', 'PENDIENTE_ATENCION_HUMANA']


def test_fechas_semilla_nunca_quedan_en_el_futuro():
    from django.utils import timezone

    from apps.incidents.seed_incidents import ago

    ahora = timezone.now()
    assert all(ago(0, hora) < ahora for hora in range(24))
    assert ago(3, 23) < ahora
