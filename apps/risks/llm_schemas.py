"""Contratos Pydantic de Structured Outputs para las ramas Operativa y Estratégica."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

from apps.risks.constants import TipoOrientacion

NO_DETERMINADO = 'NO_DETERMINADO'


class OperationalStepOutput(BaseModel):
    orden: int = Field(..., ge=1, description='Orden secuencial del paso (1, 2, 3...)')
    instruccion: str = Field(..., min_length=5, description='Instrucción accionable incluyendo referencias [1], [2] cuando aplique')


class OperationalGuidanceLLMOutput(BaseModel):
    tipo: Literal[TipoOrientacion.SUGERENCIA, TipoOrientacion.SENSIBLE] = Field(
        ...,
        description='SENSIBLE si el reporte involucra phishing, malware, credenciales comprometidas o acceso no autorizado; '
                    'SUGERENCIA en caso contrario',
    )
    resumen: str = Field(..., min_length=10)
    advertencia: Optional[str] = Field(None)
    pasos: list[OperationalStepOutput] = Field(default_factory=list)
    numeros_citas_usadas: list[int] = Field(
        default_factory=list,
        description='Índices 1-based de los fragmentos suministrados en el prompt que fueron efectivamente citados',
    )


class StrategicExtractionLLMOutput(BaseModel):
    activo_identificado: str = Field(default=NO_DETERMINADO)
    amenaza: str = Field(default=NO_DETERMINADO)
    vulnerabilidad: str = Field(default=NO_DETERMINADO)
    consecuencia: str = Field(default=NO_DETERMINADO)
    riesgo_candidato: str = Field(..., min_length=5)
    descripcion_riesgo: str = Field(..., min_length=10)
    extracto_reporte: str = Field(..., min_length=5)
    recomendacion: Optional[str] = Field(None)
    numeros_citas_estrategicas: list[int] = Field(default_factory=list)
