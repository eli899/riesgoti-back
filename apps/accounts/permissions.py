from rest_framework.permissions import BasePermission

from apps.accounts.models import RolPermiso

ADMIN_ROLE_CODE = 'ADMIN'

# Segregación de Funciones (INV-05, ISO/IEC 27001 A.5.3): permisos de evaluación/decisión de riesgos.
SOD_RISK_PERMISSIONS = frozenset({
    'riesgo.revisar_agrupacion',
    'riesgo.evaluar',
    'riesgo.validar',
})

# Permisos de administración que no pueden convivir con SOD_RISK_PERMISSIONS en un mismo rol.
ADMINISTRATIVE_PERMISSIONS = frozenset({
    'usuario.administrar',
    'rol.administrar',
    'matriz.administrar',
    'documento.administrar',
    'activo.administrar',
})


def get_user_permission_codes(user) -> set[str]:
    if not user or not user.is_authenticated or not getattr(user, 'activo', False):
        return set()
    if hasattr(user, '_cached_perm_codes'):
        return user._cached_perm_codes
    codes = set(
        RolPermiso.objects.filter(
            rol_id=user.rol_id,
            rol__activo=True,
            permiso__activo=True,
        ).values_list('permiso__codigo', flat=True)
    )
    user._cached_perm_codes = codes
    return codes


def user_has_permission(user, code: str) -> bool:
    if code in SOD_RISK_PERMISSIONS and user.rol.codigo == ADMIN_ROLE_CODE:
        return False
    return code in get_user_permission_codes(user)


class HasRiesgoTIPermission(BasePermission):
    """
    Evalúa el atributo `required_permission` o `permission_map` (dict por action) del ViewSet.
    Basta con poseer uno de los permisos requeridos. Implementa además la invariante SoD
    ISO 27001: si el permiso requerido pertenece a SOD_RISK_PERMISSIONS y el usuario tiene
    rol.codigo == 'ADMIN', deniega el acceso con HTTP 403 Forbidden.
    """

    SOD_FORBIDDEN_FOR_ADMIN = SOD_RISK_PERMISSIONS

    def has_permission(self, request, view) -> bool:
        user = request.user
        if not user or not user.is_authenticated or not getattr(user, 'activo', False):
            return False

        perm_map = getattr(view, 'permission_map', {})
        required = perm_map.get(getattr(view, 'action', None)) or getattr(view, 'required_permission', None)
        if not required:
            return True

        required_set = {required} if isinstance(required, str) else set(required)

        if user.rol.codigo == ADMIN_ROLE_CODE and (required_set & self.SOD_FORBIDDEN_FOR_ADMIN):
            return False

        return bool(required_set & get_user_permission_codes(user))
