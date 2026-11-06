"""Edición de incidencias por el reportante y eliminación física por el administrador (CHG-0035)."""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import EventoAuditoria
from apps.incidents.models import EvidenciaIncidencia, HistorialEstadoIncidencia, Incidencia
from apps.incidents.services import IncidentService, evidence_absolute_path
from apps.risks.models import DecisionRiesgo, TareaIA, VersionIncidencia
from conftest import ANALISTA_EMAIL, REPORTANTE_EMAIL, _client_for

pytestmark = pytest.mark.django_db

BASE = '/api/v1/incidents/'
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64


def _create(client, **extra) -> dict:
    from apps.assets_matrix.models import Activo

    payload = {
        'titulo': 'Impresora del piso 3 sin respuesta',
        'descripcion': 'La impresora compartida no responde desde esta mañana a ningún usuario.',
        'activo_reportado_id': Activo.objects.get(codigo='ACT-001').id,
        **extra,
    }
    response = client.post(BASE, payload, format='multipart')
    assert response.status_code == 201, response.json()
    return response.json()


# ---------------------------------------------------------------------------
# Edición (PATCH)
# ---------------------------------------------------------------------------
def test_reportante_edita_su_incidencia_y_queda_auditado(reportante_client):
    body = _create(reportante_client)
    response = reportante_client.patch(
        f"{BASE}{body['id']}/", {'titulo': 'Impresora del piso 3 apagada', 'activo_texto': 'Impresora HP piso 3'}, format='json',
    )
    assert response.status_code == 200, response.json()
    data = response.json()
    assert data['titulo'] == 'Impresora del piso 3 apagada'
    assert data['activo_texto'] == 'Impresora HP piso 3'
    assert data['estado_actual'] == 'EN_ANALISIS'  # La edición no altera el estado ni relanza la IA.
    assert TareaIA.objects.filter(incidencia_id=body['id']).count() == 2
    assert EventoAuditoria.objects.filter(incidencia_id=body['id'], accion='ACTUALIZAR_INCIDENCIA').exists()


def test_edicion_rechaza_campos_invalidos_y_peticion_vacia(reportante_client):
    body = _create(reportante_client)
    assert reportante_client.patch(f"{BASE}{body['id']}/", {'titulo': 'abc'}, format='json').status_code == 400
    assert reportante_client.patch(f"{BASE}{body['id']}/", {}, format='json').status_code == 400
    sin_activo = reportante_client.patch(f"{BASE}{body['id']}/", {'activo_reportado_id': None}, format='json')
    assert sin_activo.status_code == 400 and 'activo_reportado_id' in sin_activo.json()


def test_otro_reportante_y_analista_no_editan(reportante_client):
    body = _create(reportante_client)
    otro = _client_for('jorge.salas@empresa.pe')
    assert otro.patch(f"{BASE}{body['id']}/", {'titulo': 'Título ajeno modificado'}, format='json').status_code == 404
    analista = _client_for(ANALISTA_EMAIL)
    assert analista.patch(f"{BASE}{body['id']}/", {'titulo': 'Título del analista'}, format='json').status_code == 403


def test_incidencia_cerrada_no_admite_edicion(reportante_client):
    body = _create(reportante_client)
    incidencia = Incidencia.objects.get(pk=body['id'])
    IncidentService.transition(incidencia, 'CERRADA', incidencia.reportante, 'Cierre de prueba.')
    response = reportante_client.patch(f"{BASE}{body['id']}/", {'titulo': 'Título tras el cierre'}, format='json')
    assert response.status_code == 400 and 'estado' in response.json()


# ---------------------------------------------------------------------------
# Eliminación física (DELETE)
# ---------------------------------------------------------------------------
def test_admin_elimina_incidencia_con_dependientes_y_evidencias(reportante_client, admin_client, django_capture_on_commit_callbacks):
    body = _create(reportante_client, evidencias=[SimpleUploadedFile('captura.png', PNG, content_type='image/png')])
    clave = EvidenciaIncidencia.objects.get(incidencia_id=body['id']).clave_archivo
    assert evidence_absolute_path(clave).exists()

    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.delete(f"{BASE}{body['id']}/")

    assert response.status_code == 204
    assert not Incidencia.objects.filter(pk=body['id']).exists()
    assert not HistorialEstadoIncidencia.objects.filter(incidencia_id=body['id']).exists()
    assert not TareaIA.objects.filter(incidencia_id=body['id']).exists()
    assert not evidence_absolute_path(clave).exists()
    evento = EventoAuditoria.objects.filter(accion='ELIMINAR_INCIDENCIA').latest('id')
    assert f"#{body['id']}" in evento.detalle


def test_reportante_y_analista_no_eliminan(reportante_client):
    body = _create(reportante_client)
    assert reportante_client.delete(f"{BASE}{body['id']}/").status_code == 403
    assert _client_for(ANALISTA_EMAIL).delete(f"{BASE}{body['id']}/").status_code == 403


def test_no_se_elimina_con_ia_en_curso(reportante_client, admin_client):
    body = _create(reportante_client)
    TareaIA.objects.filter(incidencia_id=body['id'], rama='OPERATIVA').update(estado='PROCESANDO')
    assert admin_client.delete(f"{BASE}{body['id']}/").status_code == 409
    assert Incidencia.objects.filter(pk=body['id']).exists()


def test_no_se_elimina_evidencia_de_un_riesgo_decidido(admin_client):
    vinculo = VersionIncidencia.objects.filter(version__in=DecisionRiesgo.objects.values('version')).select_related(
        'analisis__tarea',
    ).first()
    assert vinculo is not None, 'La semilla debe incluir riesgos decididos con incidencias vinculadas.'
    incidencia_id = vinculo.analisis.tarea.incidencia_id
    response = admin_client.delete(f'{BASE}{incidencia_id}/')
    assert response.status_code == 409
    assert Incidencia.objects.filter(pk=incidencia_id).exists()


def test_reportante_no_ve_permiso_de_eliminar(reportante_client):
    """Sanidad del catálogo: el reportante recibe editar_propias y no eliminar."""
    from apps.accounts.permissions import get_user_permission_codes
    from apps.accounts.models import Usuario

    codes = get_user_permission_codes(Usuario.objects.get(correo=REPORTANTE_EMAIL))
    assert 'incidencia.editar_propias' in codes and 'incidencia.eliminar' not in codes
