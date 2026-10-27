"""Mensajes de error de negocio de cuentas, usuarios y roles. Las plantillas se completan con str.format."""

CREDENCIALES_INVALIDAS = 'Credenciales inválidas o usuario inactivo.'
CORREO_DUPLICADO = 'Ya existe un usuario con este correo.'
PASSWORD_OBLIGATORIA = 'La contraseña es obligatoria al crear un usuario.'
ROL_CODIGO_DUPLICADO = 'Ya existe un rol con este código.'
ROL_CODIGO_FORMATO = 'Use MAYÚSCULAS, dígitos y guion bajo (ej. AUDITOR_TI).'
PERMISOS_DESCONOCIDOS = 'Permisos inexistentes o inactivos: {permisos}.'
ADMIN_AUTORRETIRO = 'Un administrador no puede retirarse su propio acceso administrativo.'
ULTIMO_ADMIN = 'No se puede desactivar ni cambiar de rol al último administrador activo.'
SOD_ADMIN_PERMISOS = 'Segregación de Funciones: el rol ADMIN no puede recibir {permisos}.'
ADMIN_PERMISOS_OBLIGATORIOS = 'El rol ADMIN debe conservar {permisos}.'
ADMIN_NO_DESACTIVABLE = 'El rol ADMIN no puede desactivarse.'
SOD_COMBINACION = (
    'Segregación de Funciones: un mismo rol no puede combinar permisos de administración '
    'con permisos de evaluación/decisión de riesgos.'
)
ROL_BASE_CODIGO_INMUTABLE = 'El código de un rol base del sistema no puede modificarse.'
ROL_CON_USUARIOS_ACTIVOS = 'No se puede desactivar un rol con usuarios activos asignados.'
