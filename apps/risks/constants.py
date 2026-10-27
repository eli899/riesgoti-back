"""Valores de dominio de tareas IA, orientación operativa y gobierno de riesgos. Espejo de front/src/constants/domain.constants.ts."""
from enum import StrEnum


class RamaTareaIA(StrEnum):
    """TAREA_IA.rama"""

    OPERATIVA = 'OPERATIVA'
    ESTRATEGICA = 'ESTRATEGICA'


class EstadoTareaIA(StrEnum):
    """TAREA_IA.estado"""

    PENDIENTE = 'PENDIENTE'
    PROCESANDO = 'PROCESANDO'
    COMPLETADA = 'COMPLETADA'
    ERROR = 'ERROR'


class TipoOrientacion(StrEnum):
    """ORIENTACION_OPERATIVA.tipo"""

    SUGERENCIA = 'SUGERENCIA'
    SENSIBLE = 'SENSIBLE'
    SIN_RESPALDO = 'SIN_RESPALDO'


class EstadoVinculo(StrEnum):
    """VERSION_INCIDENCIA.estado"""

    SUGERIDA = 'SUGERIDA'
    CONFIRMADA = 'CONFIRMADA'
    RETIRADA = 'RETIRADA'


class AccionDecisionRiesgo(StrEnum):
    """DECISION_RIESGO.accion"""

    VALIDADA = 'VALIDADA'
    CORREGIDA = 'CORREGIDA'
    RECHAZADA = 'RECHAZADA'


class EstadoVersionRiesgo(StrEnum):
    """Estado derivado de VERSION_RIESGO: PENDIENTE mientras no exista DECISION_RIESGO; si existe, su acción."""

    PENDIENTE = 'PENDIENTE'
    VALIDADA = AccionDecisionRiesgo.VALIDADA.value
    CORREGIDA = AccionDecisionRiesgo.CORREGIDA.value
    RECHAZADA = AccionDecisionRiesgo.RECHAZADA.value


class OrigenVersionRiesgo(StrEnum):
    """VERSION_RIESGO.origen"""

    IA = 'IA'
    ANALISTA = 'ANALISTA'


class OrigenRecomendacion(StrEnum):
    """VERSION_RIESGO.origen_recomendacion"""

    NORMATIVA_INTERNA = 'NORMATIVA_INTERNA'
    IA = 'IA'
    ANALISTA = 'ANALISTA'


class CasoAgrupacion(StrEnum):
    """Resultado de la agrupación estratégica de una incidencia (registrado en EVENTO_AUDITORIA.detalle)."""

    NUEVO_RIESGO = 'NUEVO_RIESGO'
    AGRUPACION = 'AGRUPACION'
    RECURRENCIA_NUEVA_VERSION = 'RECURRENCIA_NUEVA_VERSION'


# Decisiones que exigen observación (rechazo o corrección).
DECISIONES_CON_OBSERVACION = (AccionDecisionRiesgo.RECHAZADA, AccionDecisionRiesgo.CORREGIDA)


class BandejaRiesgo(StrEnum):
    """Parámetro `bandeja` de GET /risk-versions/. Espejo de RISK_INBOXES (front/src/constants/domain.constants.ts)."""

    NUEVAS = 'nuevas'
    PENDIENTES_REVISION = 'pendientes_revision'
    RECHAZADAS = 'rechazadas'
    DECIDIDAS = 'decididas'


BANDEJAS_RIESGO = [
    (BandejaRiesgo.NUEVAS.value, 'Pendientes sin agrupación confirmada'),
    (BandejaRiesgo.PENDIENTES_REVISION.value, 'Pendientes con agrupación confirmada'),
    (BandejaRiesgo.RECHAZADAS.value, 'Versiones rechazadas'),
    (BandejaRiesgo.DECIDIDAS.value, 'Versiones con decisión registrada'),
]

# Campos de contenido de VERSION_RIESGO que una corrección del analista puede modificar.
CORRECTABLE_FIELDS = ('titulo', 'descripcion', 'amenaza', 'vulnerabilidad', 'consecuencia', 'recomendacion')

# Longitudes mínimas (caracteres) de las justificaciones de evaluación, decisión y retiro.
MIN_JUSTIFICACION = 15
MIN_JUSTIFICACION_CAMBIO_ACTIVO = 10
MIN_OBSERVACION = 10

# Longitud máxima del resumen extraído de un fragmento citado.
MAX_RESUMEN_CHARS = 300

# Similitud registrada para la incidencia que origina un riesgo nuevo.
SIMILITUD_ORIGEN = 1.0

# Longitudes máximas de los textos de decisión y agrupación (columnas TEXT; límite de la API).
OBSERVACION_MAX_LENGTH = 2000
DECISION_TEXTO_MAX_LENGTH = 4000
