import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import Permiso, Rol, Usuario
from apps.audit.models import EventoAuditoria
from conftest import ADMIN_2_EMAIL, ADMIN_EMAIL, ANALISTA_EMAIL, SEED_PASSWORD

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Login JWT
# ---------------------------------------------------------------------------
def test_login_devuelve_tokens_claims_y_permisos(api_client):
    response = api_client.post('/api/v1/auth/login/', {'correo': ANALISTA_EMAIL, 'password': SEED_PASSWORD}, format='json')

    assert response.status_code == 200
    body = response.json()
    assert body['user']['rol_codigo'] == 'ANALISTA'
    assert body['user']['nombre_completo'] == 'Andrea Quispe'
    assert 'riesgo.evaluar' in body['user']['permisos']
    assert 'password' not in body['user'] and 'password_hash' not in body['user']

    claims = AccessToken(body['access'])
    assert str(claims['usuario_id']) == str(body['user']['usuario_id'])  # SimpleJWT serializa el id como string
    assert claims['rol_codigo'] == 'ANALISTA'
    assert 'riesgo.validar' in claims['permisos']
    assert EventoAuditoria.objects.filter(accion='INICIO_SESION', actor_id=body['user']['usuario_id']).exists()


def test_login_con_password_incorrecto_retorna_401_y_audita(api_client):
    response = api_client.post('/api/v1/auth/login/', {'correo': ANALISTA_EMAIL, 'password': 'incorrecta'}, format='json')

    assert response.status_code == 401
    assert EventoAuditoria.objects.filter(accion='INICIO_SESION_FALLIDO').exists()


def test_login_de_usuario_inactivo_retorna_401(api_client):
    Usuario.objects.filter(correo=ANALISTA_EMAIL).update(activo=False)
    response = api_client.post('/api/v1/auth/login/', {'correo': ANALISTA_EMAIL, 'password': SEED_PASSWORD}, format='json')
    assert response.status_code == 401


def test_refresh_y_bearer_token_funcionan(api_client):
    login = api_client.post('/api/v1/auth/login/', {'correo': ADMIN_EMAIL, 'password': SEED_PASSWORD}, format='json').json()

    refreshed = api_client.post('/api/v1/auth/refresh/', {'refresh': login['refresh']}, format='json')
    assert refreshed.status_code == 200

    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {refreshed.json()['access']}")
    me = api_client.get('/api/v1/auth/me/')
    assert me.status_code == 200
    assert me.json()['rol_codigo'] == 'ADMIN'


def test_endpoints_protegidos_requieren_autenticacion(api_client):
    assert api_client.get('/api/v1/admin/users/').status_code == 401


# ---------------------------------------------------------------------------
# RBAC sobre administración
# ---------------------------------------------------------------------------
def test_analista_no_puede_administrar_usuarios(analista_client):
    assert analista_client.get('/api/v1/admin/users/').status_code == 403
    assert analista_client.get('/api/v1/admin/roles/').status_code == 403
    assert analista_client.get('/api/v1/admin/audit-events/').status_code == 403


def test_admin_crea_usuario_sin_exponer_password(admin_client):
    analista_rol = Rol.objects.get(codigo='ANALISTA')
    response = admin_client.post('/api/v1/admin/users/', {
        'nombres': 'Rosa', 'apellidos': 'Lema', 'correo': 'Rosa.Lema@empresa.pe',
        'rol_id': analista_rol.id, 'password': 'Clave-Segura-2026',
    }, format='json')

    assert response.status_code == 201, response.json()
    body = response.json()
    assert body['rol_codigo'] == 'ANALISTA'
    assert 'password' not in body and 'password_hash' not in body
    assert Usuario.objects.get(pk=body['id']).check_password('Clave-Segura-2026')
    assert EventoAuditoria.objects.filter(accion='CREAR_USUARIO', usuario_objeto_id=body['id']).exists()


def test_crear_usuario_con_correo_duplicado_falla(admin_client):
    rol = Rol.objects.get(codigo='REPORTANTE')
    response = admin_client.post('/api/v1/admin/users/', {
        'nombres': 'X', 'apellidos': 'Y', 'correo': ANALISTA_EMAIL.upper(), 'rol_id': rol.id, 'password': 'Clave-Segura-2026',
    }, format='json')
    assert response.status_code == 400
    assert 'correo' in response.json()


def test_admin_no_puede_desactivarse_a_si_mismo(admin_client, admin_user):
    response = admin_client.patch(f'/api/v1/admin/users/{admin_user.id}/', {'activo': False}, format='json')
    assert response.status_code == 400
    admin_user.refresh_from_db()
    assert admin_user.activo is True


def test_no_se_puede_desactivar_al_ultimo_admin_activo(admin_client, admin_user):
    # Con dos ADMIN activos, desactivar al otro está permitido.
    otro_admin = Usuario.objects.get(correo=ADMIN_2_EMAIL)
    assert admin_client.patch(f'/api/v1/admin/users/{otro_admin.id}/', {'activo': False}, format='json').status_code == 200

    # Un gestor de usuarios (rol no ADMIN) intenta desactivar al único ADMIN restante.
    gestor_rol = Rol.objects.create(codigo='GESTOR_USUARIOS', nombre='Gestor de usuarios')
    gestor_rol.rol_permisos.create(permiso=Permiso.objects.get(codigo='usuario.administrar'))
    gestor = Usuario.objects.create_user(
        correo='gestor@empresa.pe', nombres='Gestor', apellidos='Usuarios', rol=gestor_rol, password=SEED_PASSWORD,
    )
    client = APIClient()
    client.force_authenticate(user=gestor)

    response = client.patch(f'/api/v1/admin/users/{admin_user.id}/', {'activo': False}, format='json')

    assert response.status_code == 400
    admin_user.refresh_from_db()
    assert admin_user.activo is True


def test_no_se_puede_cambiar_de_rol_al_ultimo_admin(admin_client, admin_user):
    otro_admin = Usuario.objects.get(correo=ADMIN_2_EMAIL)
    analista_rol = Rol.objects.get(codigo='ANALISTA')
    assert admin_client.patch(f'/api/v1/admin/users/{otro_admin.id}/', {'activo': False}, format='json').status_code == 200

    # Queda un solo ADMIN activo (admin_user): un tercero no puede retirarle el rol, ni él mismo.
    response = admin_client.patch(f'/api/v1/admin/users/{admin_user.id}/', {'rol_id': analista_rol.id}, format='json')
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Roles y Segregación de Funciones (INV-05)
# ---------------------------------------------------------------------------
def _admin_role_payload(extra_perms=()):
    return {
        'codigo': 'ADMIN', 'nombre': 'Administrador', 'activo': True,
        'permisos': [
            'incidencia.ver_propias', 'incidencia.ver_todas', 'riesgo.consultar', 'activo.administrar',
            'documento.administrar', 'matriz.administrar', 'usuario.administrar', 'rol.administrar', *extra_perms,
        ],
    }


@pytest.mark.parametrize('permiso', ['riesgo.evaluar', 'riesgo.validar', 'riesgo.revisar_agrupacion'])
def test_rol_admin_no_puede_recibir_permisos_de_riesgo(admin_client, permiso):
    admin_rol = Rol.objects.get(codigo='ADMIN')
    response = admin_client.put(f'/api/v1/admin/roles/{admin_rol.id}/', _admin_role_payload([permiso]), format='json')

    assert response.status_code == 400
    assert not admin_rol.rol_permisos.filter(permiso__codigo=permiso).exists()


def test_actualizar_rol_admin_valido_y_auditado(admin_client):
    admin_rol = Rol.objects.get(codigo='ADMIN')
    payload = _admin_role_payload()
    payload['permisos'].remove('incidencia.ver_propias')

    response = admin_client.put(f'/api/v1/admin/roles/{admin_rol.id}/', payload, format='json')

    assert response.status_code == 200, response.json()
    assert 'incidencia.ver_propias' not in response.json()['permisos']
    assert EventoAuditoria.objects.filter(accion='ACTUALIZAR_ROL', rol_id=admin_rol.id).exists()


def test_rol_nuevo_no_puede_combinar_administracion_y_evaluacion(admin_client):
    response = admin_client.post('/api/v1/admin/roles/', {
        'codigo': 'SUPERVISOR', 'nombre': 'Supervisor', 'permisos': ['usuario.administrar', 'riesgo.evaluar'],
    }, format='json')
    assert response.status_code == 400


def test_crear_rol_valido(admin_client):
    response = admin_client.post('/api/v1/admin/roles/', {
        'codigo': 'AUDITOR_TI', 'nombre': 'Auditor TI', 'permisos': ['riesgo.consultar', 'incidencia.ver_todas'],
    }, format='json')
    assert response.status_code == 201, response.json()
    assert response.json()['permisos'] == ['incidencia.ver_todas', 'riesgo.consultar']


def test_codigo_de_rol_base_es_inmutable(admin_client):
    analista = Rol.objects.get(codigo='ANALISTA')
    response = admin_client.put(f'/api/v1/admin/roles/{analista.id}/', {
        'codigo': 'ANALISTA_SR', 'nombre': 'Analista', 'activo': True, 'permisos': ['riesgo.consultar'],
    }, format='json')
    assert response.status_code == 400


def test_permiso_sod_deniega_admin_aunque_tenga_el_permiso(rf, admin_user):
    """HasRiesgoTIPermission niega al ADMIN los permisos de riesgo aun si un dato corrupto se los asignara."""
    from apps.accounts.permissions import HasRiesgoTIPermission

    admin_user._cached_perm_codes = {'riesgo.evaluar'}
    request = rf.post('/fake/')
    request.user = admin_user
    view = type('View', (), {'required_permission': 'riesgo.evaluar', 'action': 'create'})()
    assert HasRiesgoTIPermission().has_permission(request, view) is False
