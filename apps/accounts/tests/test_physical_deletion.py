"""Eliminación física de usuarios, roles, activos, versiones documentales y propuestas de riesgo (CHG-0035)."""
import pytest

from apps.accounts.models import Rol, Usuario
from apps.assets_matrix.models import Activo, TipoActivo
from apps.audit.models import EventoAuditoria
from apps.documents_rag.faiss_store import FaissVectorStore
from apps.documents_rag.models import Documento, FragmentoDocumento, VersionDocumento
from apps.documents_rag.tasks import process_pdf_version_task
from apps.documents_rag.tests.test_documents_rag import _upload
from apps.risks.models import CitaVersionRiesgo, DecisionRiesgo, Riesgo, VersionRiesgo
from conftest import ADMIN_2_EMAIL, ADMIN_EMAIL, ANALISTA_EMAIL

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------
def _new_user(correo='temporal@empresa.pe', rol='REPORTANTE') -> Usuario:
    return Usuario.objects.create_user(correo=correo, nombres='Usuario', apellidos='Temporal', rol=Rol.objects.get(codigo=rol), password='x')


def test_admin_elimina_usuario_sin_registros(admin_client):
    user = _new_user()
    assert admin_client.delete(f'/api/v1/admin/users/{user.pk}/').status_code == 204
    assert not Usuario.objects.filter(pk=user.pk).exists()
    assert EventoAuditoria.objects.filter(accion='ELIMINAR_USUARIO', detalle__contains='temporal@empresa.pe').exists()


def test_usuario_con_registros_responde_409(admin_client):
    analista = Usuario.objects.get(correo=ANALISTA_EMAIL)
    response = admin_client.delete(f'/api/v1/admin/users/{analista.pk}/')
    assert response.status_code == 409
    assert Usuario.objects.filter(pk=analista.pk).exists()


def test_admin_no_se_elimina_a_si_mismo(admin_client):
    yo = Usuario.objects.get(correo=ADMIN_EMAIL)
    assert admin_client.delete(f'/api/v1/admin/users/{yo.pk}/').status_code == 409


def test_no_se_elimina_al_ultimo_admin_activo(admin_client):
    Usuario.objects.filter(correo=ADMIN_2_EMAIL).update(activo=False)
    nuevo = _new_user('admin.temporal@empresa.pe', 'ADMIN')
    Usuario.objects.filter(correo=ADMIN_EMAIL).update(activo=False)
    from conftest import _client_for

    response = _client_for('admin.temporal@empresa.pe').delete(f'/api/v1/admin/users/{nuevo.pk}/')
    assert response.status_code == 409


def test_analista_no_elimina_usuarios(analista_client):
    assert analista_client.delete(f'/api/v1/admin/users/{_new_user().pk}/').status_code == 403


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
def test_admin_elimina_rol_personalizado_sin_usuarios(admin_client):
    rol = Rol.objects.create(codigo='AUDITOR_TI', nombre='Auditor TI')
    assert admin_client.delete(f'/api/v1/admin/roles/{rol.pk}/').status_code == 204
    assert not Rol.objects.filter(pk=rol.pk).exists()


def test_roles_base_o_con_usuarios_responden_409(admin_client):
    assert admin_client.delete(f"/api/v1/admin/roles/{Rol.objects.get(codigo='REPORTANTE').pk}/").status_code == 409
    rol = Rol.objects.create(codigo='AUDITOR_TI', nombre='Auditor TI')
    Usuario.objects.create_user(correo='auditor@empresa.pe', nombres='Ana', apellidos='Auditora', rol=rol, password='x')
    assert admin_client.delete(f'/api/v1/admin/roles/{rol.pk}/').status_code == 409


# ---------------------------------------------------------------------------
# Activos
# ---------------------------------------------------------------------------
def test_admin_elimina_activo_sin_referencias_y_409_si_las_tiene(admin_client):
    nuevo = Activo.objects.create(codigo='ACT-999', nombre='Activo temporal', tipo=TipoActivo.objects.first(), criticidad=1)
    assert admin_client.delete(f'/api/v1/assets/{nuevo.pk}/').status_code == 204
    assert not Activo.objects.filter(pk=nuevo.pk).exists()

    referenciado = Activo.objects.get(codigo='ACT-001')
    assert admin_client.delete(f'/api/v1/assets/{referenciado.pk}/').status_code == 409


# ---------------------------------------------------------------------------
# Versiones documentales
# ---------------------------------------------------------------------------
def test_admin_elimina_version_inactiva_sin_citas_con_vectores_y_pdf(admin_client, django_capture_on_commit_callbacks):
    from apps.documents_rag.services import pdf_absolute_path

    response = _upload(admin_client, codigo='POL-TMP-01')
    assert response.status_code == 201, response.json()
    version_id = response.json()['id']
    process_pdf_version_task(version_id)
    version = VersionDocumento.objects.get(pk=version_id)
    fragment_ids = list(version.fragmentos.values_list('id', flat=True))
    assert fragment_ids and pdf_absolute_path(version.clave_archivo).exists()

    with django_capture_on_commit_callbacks(execute=True):
        assert admin_client.delete(f'/api/v1/admin/document-versions/{version_id}/').status_code == 204

    assert not FragmentoDocumento.objects.filter(id__in=fragment_ids).exists()
    assert not Documento.objects.filter(codigo='POL-TMP-01').exists()
    assert not pdf_absolute_path(version.clave_archivo).exists()
    index = FaissVectorStore.load(version.modelo_embedding)
    restantes = set(index.id_map.at(i) for i in range(index.ntotal)) if index is not None else set()
    assert not restantes & set(fragment_ids)


def test_version_activa_o_citada_responde_409(admin_client):
    citada = VersionDocumento.objects.filter(fragmentos__citas_riesgo__isnull=False).distinct().first()
    assert citada is not None
    assert admin_client.delete(f'/api/v1/admin/document-versions/{citada.pk}/').status_code == 409
    VersionDocumento.objects.filter(pk=citada.pk).update(activa=False)
    assert admin_client.delete(f'/api/v1/admin/document-versions/{citada.pk}/').status_code == 409
    assert VersionDocumento.objects.filter(pk=citada.pk).exists()


# ---------------------------------------------------------------------------
# Propuestas de riesgo
# ---------------------------------------------------------------------------
def test_admin_elimina_propuesta_pendiente_y_su_riesgo_huerfano(admin_client):
    riesgo = Riesgo.objects.create(codigo='RSG-9999')
    version = VersionRiesgo.objects.create(
        riesgo=riesgo, numero=1, origen='IA', titulo='Propuesta temporal', creada_por=Usuario.objects.get(correo=ADMIN_EMAIL),
    )
    assert admin_client.delete(f'/api/v1/risk-versions/{version.pk}/').status_code == 204
    assert not Riesgo.objects.filter(pk=riesgo.pk).exists()
    assert EventoAuditoria.objects.filter(accion='ELIMINAR_VERSION_RIESGO', detalle__contains='RSG-9999').exists()


def test_version_decidida_responde_409_y_analista_no_elimina(admin_client, analista_client):
    decidida = DecisionRiesgo.objects.select_related('version').first().version
    assert admin_client.delete(f'/api/v1/risk-versions/{decidida.pk}/').status_code == 409
    assert CitaVersionRiesgo.objects.filter(version=decidida).exists() or VersionRiesgo.objects.filter(pk=decidida.pk).exists()
    assert analista_client.delete(f'/api/v1/risk-versions/{decidida.pk}/').status_code == 403
