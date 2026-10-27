"""Valores de dominio de incidencias. Espejo de front/src/constants/domain.constants.ts."""
from enum import StrEnum


class EstadoIncidencia(StrEnum):
    """HISTORIAL_ESTADO_INCIDENCIA.estado"""

    REGISTRADA = 'REGISTRADA'
    EN_ANALISIS = 'EN_ANALISIS'
    PENDIENTE_ATENCION_HUMANA = 'PENDIENTE_ATENCION_HUMANA'
    EN_ATENCION = 'EN_ATENCION'
    CERRADA = 'CERRADA'


class ResultadoOrientacion(StrEnum):
    """RESPUESTA_ORIENTACION.resultado"""

    FUNCIONO = 'FUNCIONO'
    NO_FUNCIONO = 'NO_FUNCIONO'


# Cola de atención humana N2.
ESTADOS_COLA_ATENCION = (EstadoIncidencia.PENDIENTE_ATENCION_HUMANA, EstadoIncidencia.EN_ATENCION)


class BandejaIncidencia(StrEnum):
    """Parámetro `bandeja` de GET /incidents/. Espejo de INCIDENT_INBOXES (front/src/constants/domain.constants.ts)."""

    ATENCION = 'atencion'


BANDEJAS_INCIDENCIA = [(BandejaIncidencia.ATENCION.value, 'Cola de atención humana N2')]

# Longitudes de INCIDENCIA y ATENCION_INCIDENCIA (los máximos de columnas CharField se leen del modelo).
TITULO_MIN_LENGTH = 5
DESCRIPCION_MIN_LENGTH = 20
ATENCION_TEXTO_MIN_LENGTH = 10
ATENCION_TEXTO_MAX_LENGTH = 10000
