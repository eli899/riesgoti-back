"""Valores de dominio de la base documental. Espejo de front/src/constants/domain.constants.ts."""
from enum import StrEnum


class ProcesamientoDocumento(StrEnum):
    """VERSION_DOCUMENTO.procesamiento"""

    PROCESANDO = 'PROCESANDO'
    ERROR = 'ERROR'
    PENDIENTE_AUTORIZACION = 'PENDIENTE_AUTORIZACION'
    AUTORIZADO = 'AUTORIZADO'


class FinalidadDocumento(StrEnum):
    """VERSION_DOCUMENTO.finalidad"""

    OPERATIVA = 'OPERATIVA'
    ESTRATEGICA = 'ESTRATEGICA'
    AMBAS = 'AMBAS'


# Finalidades admitidas por cada rama del Retriever.
FINALIDADES_OPERATIVAS = (FinalidadDocumento.OPERATIVA, FinalidadDocumento.AMBAS)
FINALIDADES_ESTRATEGICAS = (FinalidadDocumento.ESTRATEGICA, FinalidadDocumento.AMBAS)

# Versiones ya procesadas cuyo índice depende del modelo de embedding vigente.
PROCESAMIENTOS_INDEXADOS = (ProcesamientoDocumento.PENDIENTE_AUTORIZACION, ProcesamientoDocumento.AUTORIZADO)

# Longitudes mínimas de la carga de VERSION_DOCUMENTO (los máximos se leen del modelo).
CODIGO_MIN_LENGTH = 2
TITULO_MIN_LENGTH = 5
VERSION_MIN_LENGTH = 1
