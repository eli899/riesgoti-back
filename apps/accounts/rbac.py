"""
Catálogo RBAC (ROL / PERMISO / ROL_PERMISO): fuente única de códigos de rol y de permiso en el backend.
Espejo de front/src/constants/rbac.constants.ts.
"""
from enum import StrEnum


class RolCodigo(StrEnum):
    """ROL.codigo de los roles de sistema."""

    REPORTANTE = 'REPORTANTE'
    ANALISTA = 'ANALISTA'
    ADMIN = 'ADMIN'


class CodigoPermiso(StrEnum):
    """PERMISO.codigo"""

    INCIDENCIA_CREAR = 'incidencia.crear'
    INCIDENCIA_VER_PROPIAS = 'incidencia.ver_propias'
    INCIDENCIA_VER_TODAS = 'incidencia.ver_todas'
    INCIDENCIA_CERRAR_PROPIAS_POR_FEEDBACK = 'incidencia.cerrar_propias_por_feedback'
    ATENCION_VER_COLA = 'atencion.ver_cola'
    ATENCION_ATENDER = 'atencion.atender'
    RIESGO_REVISAR_AGRUPACION = 'riesgo.revisar_agrupacion'
    RIESGO_EVALUAR = 'riesgo.evaluar'
    RIESGO_VALIDAR = 'riesgo.validar'
    RIESGO_CONSULTAR = 'riesgo.consultar'
    ACTIVO_ADMINISTRAR = 'activo.administrar'
    DOCUMENTO_ADMINISTRAR = 'documento.administrar'
    MATRIZ_ADMINISTRAR = 'matriz.administrar'
    USUARIO_ADMINISTRAR = 'usuario.administrar'
    ROL_ADMINISTRAR = 'rol.administrar'


# Los conjuntos guardan los valores str (no los miembros) para que los mensajes que los listan muestren el código.

# Segregación de Funciones (INV-05, ISO/IEC 27001 A.5.3): permisos de evaluación/decisión de riesgos.
SOD_RISK_PERMISSIONS = frozenset(p.value for p in (
    CodigoPermiso.RIESGO_REVISAR_AGRUPACION,
    CodigoPermiso.RIESGO_EVALUAR,
    CodigoPermiso.RIESGO_VALIDAR,
))

# Permisos de administración que no pueden convivir con SOD_RISK_PERMISSIONS en un mismo rol.
ADMINISTRATIVE_PERMISSIONS = frozenset(p.value for p in (
    CodigoPermiso.USUARIO_ADMINISTRAR,
    CodigoPermiso.ROL_ADMINISTRAR,
    CodigoPermiso.MATRIZ_ADMINISTRAR,
    CodigoPermiso.DOCUMENTO_ADMINISTRAR,
    CodigoPermiso.ACTIVO_ADMINISTRAR,
))

# Permisos que el rol ADMIN debe conservar para no perder el gobierno de la plataforma.
ADMIN_REQUIRED_PERMISSIONS = frozenset(p.value for p in (CodigoPermiso.USUARIO_ADMINISTRAR, CodigoPermiso.ROL_ADMINISTRAR))

SYSTEM_ROLE_CODES = frozenset(r.value for r in RolCodigo)
