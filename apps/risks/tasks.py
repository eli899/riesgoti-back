from celery import shared_task
from django.conf import settings

from apps.risks.services import OperationalRAGService, StrategicRiskAnalysisService

# Los servicios capturan cualquier excepción y la registran en TAREA_IA (estado ERROR); la tarea Celery no
# se reintenta automáticamente para no duplicar orientaciones. El límite suave aborta llamadas colgadas al proveedor.
TASK_OPTIONS = {
    'acks_late': True,
    'soft_time_limit': settings.CELERY_AI_TASK_SOFT_TIME_LIMIT,
    'time_limit': settings.CELERY_AI_TASK_TIME_LIMIT,
}


@shared_task(name='risks.run_operational_rag', **TASK_OPTIONS)
def run_operational_rag_task(tarea_ia_id: int) -> dict:
    """Rama Operativa: ORIENTACION_OPERATIVA con citas verificadas, SENSIBLE o SIN_RESPALDO (INV-01)."""
    return OperationalRAGService.run(tarea_ia_id)


@shared_task(name='risks.run_strategic_risk', **TASK_OPTIONS)
def run_strategic_risk_task(tarea_ia_id: int) -> dict:
    """Rama Estratégica: ANALISIS_INCIDENCIA y agrupación en VERSION_RIESGO, independiente del cierre operativo (INV-02)."""
    return StrategicRiskAnalysisService.run(tarea_ia_id)
