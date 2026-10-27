"""Casos de uso transaccionales de autenticación, usuarios y roles (RBAC + SoD ISO/IEC 27001)."""
from django.contrib.auth import authenticate
from django.db import transaction
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts import messages as msg
from apps.accounts.models import Permiso, Rol, RolPermiso, Usuario
from apps.accounts.permissions import get_user_permission_codes
from apps.accounts.rbac import (
    ADMIN_REQUIRED_PERMISSIONS,
    ADMINISTRATIVE_PERMISSIONS,
    SOD_RISK_PERMISSIONS,
    SYSTEM_ROLE_CODES,
    RolCodigo,
)
from apps.audit.constants import AccionAuditoria
from apps.audit.services import AuditService


# ---------------------------------------------------------------------------
# Autenticación JWT
# ---------------------------------------------------------------------------
class AuthService:
    @staticmethod
    def build_tokens(user: Usuario) -> dict:
        permisos = sorted(get_user_permission_codes(user))
        refresh = RefreshToken.for_user(user)
        refresh['nombre_completo'] = user.nombre_completo
        refresh['rol_codigo'] = user.rol.codigo
        refresh['permisos'] = permisos
        return {'access': str(refresh.access_token), 'refresh': str(refresh), 'user': user}

    @classmethod
    def login(cls, request, *, correo: str, password: str) -> dict:
        user = authenticate(request, correo=correo, password=password)
        if user is None:
            AuditService.log(accion=AccionAuditoria.INICIO_SESION_FALLIDO, detalle=f'correo={correo}')
            raise AuthenticationFailed(msg.CREDENCIALES_INVALIDAS)
        AuditService.log(actor=user, accion=AccionAuditoria.INICIO_SESION, usuario_objeto=user, detalle=f'correo={user.correo}')
        return cls.build_tokens(user)


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------
class UserService:
    @staticmethod
    def _assert_admin_continuity(actor: Usuario, instance: Usuario, *, nuevo_rol: Rol, nuevo_activo: bool) -> None:
        era_admin_activo = instance.activo and instance.rol.codigo == RolCodigo.ADMIN
        sigue_admin_activo = nuevo_activo and nuevo_rol.codigo == RolCodigo.ADMIN
        if not era_admin_activo or sigue_admin_activo:
            return

        if actor.pk == instance.pk:
            raise ValidationError({'activo': msg.ADMIN_AUTORRETIRO})

        otros_admins = (
            Usuario.objects.select_for_update()
            .filter(rol__codigo=RolCodigo.ADMIN, activo=True)
            .exclude(pk=instance.pk)
        )
        if not list(otros_admins):
            raise ValidationError({'activo': msg.ULTIMO_ADMIN})

    @staticmethod
    @transaction.atomic
    def create_user(actor: Usuario, data: dict) -> Usuario:
        user = Usuario.objects.create_user(
            correo=data['correo'],
            nombres=data['nombres'],
            apellidos=data['apellidos'],
            rol=data['rol'],
            password=data['password'],
        )
        if data.get('activo') is False:
            user.activo = False
            user.save(update_fields=['activo', 'ultima_modificacion'])
        AuditService.log(
            actor=actor, accion=AccionAuditoria.CREAR_USUARIO, usuario_objeto=user, rol=user.rol,
            detalle=f'correo={user.correo} rol={user.rol.codigo}',
        )
        return user

    @classmethod
    @transaction.atomic
    def update_user(cls, actor: Usuario, instance: Usuario, data: dict) -> Usuario:
        nuevo_rol = data.get('rol', instance.rol)
        nuevo_activo = data.get('activo', instance.activo)
        cls._assert_admin_continuity(actor, instance, nuevo_rol=nuevo_rol, nuevo_activo=nuevo_activo)

        cambios = []
        for field in ('nombres', 'apellidos', 'correo', 'rol', 'activo'):
            if field in data and getattr(instance, field) != data[field]:
                setattr(instance, field, data[field])
                cambios.append(field)
        if data.get('password'):
            instance.set_password(data['password'])
            cambios.append('password')
        if not cambios:
            return instance

        instance.save()
        if 'activo' in cambios:
            accion = AccionAuditoria.ACTIVAR_USUARIO if instance.activo else AccionAuditoria.DESACTIVAR_USUARIO
        elif 'rol' in cambios:
            accion = AccionAuditoria.CAMBIAR_ROL_USUARIO
        else:
            accion = AccionAuditoria.ACTUALIZAR_USUARIO
        AuditService.log(
            actor=actor, accion=accion, usuario_objeto=instance, rol=instance.rol,
            detalle=f'campos={",".join(cambios)}',
        )
        return instance


# ---------------------------------------------------------------------------
# Roles y permisos
# ---------------------------------------------------------------------------
class RoleService:
    @staticmethod
    def validate_permission_set(codigo: str, permiso_codigos: set[str], activo: bool) -> None:
        """Valida SoD (INV-05) sobre el conjunto final de permisos de un rol."""
        if codigo == RolCodigo.ADMIN:
            prohibidos = permiso_codigos & SOD_RISK_PERMISSIONS
            if prohibidos:
                raise ValidationError({'permisos': msg.SOD_ADMIN_PERMISOS.format(permisos=sorted(prohibidos))})
            faltantes = ADMIN_REQUIRED_PERMISSIONS - permiso_codigos
            if faltantes:
                raise ValidationError({'permisos': msg.ADMIN_PERMISOS_OBLIGATORIOS.format(permisos=sorted(faltantes))})
            if not activo:
                raise ValidationError({'activo': msg.ADMIN_NO_DESACTIVABLE})

        if (permiso_codigos & SOD_RISK_PERMISSIONS) and (permiso_codigos & ADMINISTRATIVE_PERMISSIONS):
            raise ValidationError({'permisos': msg.SOD_COMBINACION})

    @staticmethod
    def _sync_permissions(rol: Rol, permiso_codigos: set[str]) -> None:
        permisos = Permiso.objects.filter(codigo__in=permiso_codigos)
        RolPermiso.objects.filter(rol=rol).exclude(permiso__in=permisos).delete()
        existentes = set(RolPermiso.objects.filter(rol=rol).values_list('permiso_id', flat=True))
        for permiso in permisos:
            if permiso.pk not in existentes:
                RolPermiso.objects.create(rol=rol, permiso=permiso)

    @classmethod
    @transaction.atomic
    def create_role(cls, actor: Usuario, data: dict) -> Rol:
        permisos = set(data['permisos'])
        cls.validate_permission_set(data['codigo'], permisos, data.get('activo', True))
        rol = Rol.objects.create(codigo=data['codigo'], nombre=data['nombre'], activo=data.get('activo', True))
        cls._sync_permissions(rol, permisos)
        AuditService.log(
            actor=actor, accion=AccionAuditoria.CREAR_ROL, rol=rol,
            detalle=f'codigo={rol.codigo} permisos={",".join(sorted(permisos))}',
        )
        return rol

    @classmethod
    @transaction.atomic
    def update_role(cls, actor: Usuario, instance: Rol, data: dict) -> Rol:
        if instance.codigo in SYSTEM_ROLE_CODES and data['codigo'] != instance.codigo:
            raise ValidationError({'codigo': msg.ROL_BASE_CODIGO_INMUTABLE})
        permisos = set(data['permisos'])
        cls.validate_permission_set(data['codigo'], permisos, data['activo'])
        if instance.activo and not data['activo'] and instance.usuarios.filter(activo=True).exists():
            raise ValidationError({'activo': msg.ROL_CON_USUARIOS_ACTIVOS})

        instance.codigo, instance.nombre, instance.activo = data['codigo'], data['nombre'], data['activo']
        instance.save()
        cls._sync_permissions(instance, permisos)
        AuditService.log(
            actor=actor, accion=AccionAuditoria.ACTUALIZAR_ROL, rol=instance,
            detalle=f'codigo={instance.codigo} activo={instance.activo} permisos={",".join(sorted(permisos))}',
        )
        return instance
