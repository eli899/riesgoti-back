"""
Servicios de dominio de las ramas asíncronas de TAREA_IA.

* OperationalRAGService (ORIENTACION_OPERATIVA): detección de casos sensibles, recuperación filtrada
  (finalidad OPERATIVA/AMBAS), barrera SIN_RESPALDO sin invocar al LLM, Structured Outputs y citas verificadas.
* StrategicRiskAnalysisService (ANALISIS_INCIDENCIA -> VERSION_RIESGO): vectores ISO/IEC 27005, agrupación por
  similitud semántica con riesgos existentes o nuevo riesgo candidato, citas estratégicas verificadas.
* StrategicRetryService: nuevo intento de la rama estratégica cuando la última tarea terminó en ERROR.
* RiskGovernanceDecisionService (v0.6): retiro/restauración de vínculos, confirmación de agrupación, evaluación 5x5
  y decisiones VALIDADA / CORREGIDA / RECHAZADA (las versiones decididas son inmutables).
* RiskDashboardAggregationService (v0.6): indicadores con la última versión VALIDADA por RIESGO.
"""
import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

import numpy as np
from django.conf import settings
from django.db import connection, transaction
from django.db.models import CharField, Count, Exists, Max, OuterRef, Prefetch, Subquery, Value
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.ai_config.models import ConfiguracionIARAG
from apps.assets_matrix.models import CeldaMatriz, ConfiguracionMatriz, NivelRiesgo
from apps.audit.constants import AccionAuditoria
from apps.audit.services import AuditService
from apps.documents_rag.embeddings import EmbeddingProviderService
from apps.documents_rag.constants import FINALIDADES_ESTRATEGICAS, FINALIDADES_OPERATIVAS
from apps.documents_rag.faiss_store import FaissVectorStore
from apps.incidents.constants import EstadoIncidencia
from apps.incidents.models import HistorialEstadoIncidencia, Incidencia
from apps.incidents.services import (
    IncidentService,
    current_status_subquery,
    dispatch_ai_tasks,
    latest_task,
)
from apps.risks import messages as msg
from apps.risks.constants import (
    CORRECTABLE_FIELDS,
    MAX_RESUMEN_CHARS,
    MIN_JUSTIFICACION,
    MIN_JUSTIFICACION_CAMBIO_ACTIVO,
    SIMILITUD_ORIGEN,
    AccionDecisionRiesgo,
    CasoAgrupacion,
    EstadoTareaIA,
    EstadoVersionRiesgo,
    EstadoVinculo,
    OrigenRecomendacion,
    OrigenVersionRiesgo,
    RamaTareaIA,
    TipoOrientacion,
)
from apps.risks.llm_client import DETERMINISTIC_PROVIDER, LLMClient
from apps.risks.llm_schemas import (
    NO_DETERMINADO,
    OperationalGuidanceLLMOutput,
    OperationalStepOutput,
    StrategicExtractionLLMOutput,
)
from apps.risks.models import (
    AnalisisIncidencia,
    CitaOrientacion,
    CitaVersionRiesgo,
    DecisionRiesgo,
    EvaluacionRiesgo,
    OrientacionOperativa,
    PasoOrientacion,
    Riesgo,
    TareaIA,
    VersionIncidencia,
    VersionRiesgo,
)
from config.constants import MAX_ERROR_CHARS

logger = logging.getLogger(__name__)

# Longitud de TAREA_IA.error_codigo (bd.sql).
ERROR_CODIGO_MAX_CHARS = TareaIA._meta.get_field('error_codigo').max_length

# Patrones de incidente de seguridad (alineados con SENSITIVE de figma/src/data.ts).
SENSITIVE_RE = re.compile(
    r'malware|virus|acceso no autorizado|hacke|robo|exposici|filtraci|p[ée]rdida de datos|credencial|contrase[ñn]a|'
    r'phishing|suplant|sospech|ransom|desconocid|otro pa[ií]s',
    re.IGNORECASE,
)
CITATION_RE = re.compile(r'\[(\d+)\]')
MAX_FRAGMENT_CHARS_IN_PROMPT = 1500
GROUPING_LOCK_KEY = 270050  # pg_advisory_xact_lock: serializa la agrupación de riesgos.

SIN_RESPALDO_RESUMEN = ('No se encontraron manuales operativos autorizados que superen el umbral de similitud '
                        'para este caso.')
SIN_RESPALDO_ADVERTENCIA = 'El caso ha sido derivado a un analista humano.'
SENSIBLE_RESUMEN = ('El reporte describe un posible incidente de seguridad de la información que requiere '
                    'contención inmediata por un analista.')
SENSIBLE_ADVERTENCIA = '\n'.join([
    'No hagas clic en enlaces ni abras adjuntos relacionados con el reporte.',
    'No compartas tu contraseña ni códigos de verificación.',
    'Un analista revisará el caso de inmediato.',
])

OPERATIONAL_SYSTEM_PROMPT = """Eres el asistente de soporte TI de RiesgoTI (ISO/IEC 27001/27002).
Redacta una orientación operativa breve para el usuario que reportó la incidencia, en español claro.
Reglas obligatorias:
- Usa EXCLUSIVAMENTE los fragmentos normativos numerados [1]..[k] suministrados; no inventes procedimientos.
- Cada paso debe citar entre corchetes el fragmento que lo respalda, por ejemplo [1].
- numeros_citas_usadas solo puede contener números de fragmentos suministrados.
- Clasifica como SENSIBLE si el reporte involucra phishing, malware, credenciales comprometidas o acceso no
  autorizado; en ese caso entrega solo advertencias de contención y ningún paso técnico.
- No pidas al usuario reinstalar software, modificar configuraciones del sistema ni abrir equipos."""

STRATEGIC_SYSTEM_PROMPT = """Eres un analista de riesgos de seguridad de la información (ISO/IEC 27005:2022).
A partir del reporte de incidencia identifica activo, amenaza, vulnerabilidad y consecuencia.
Reglas obligatorias:
- Si un elemento no está sustentado explícitamente en el reporte, responde exactamente NO_DETERMINADO.
- riesgo_candidato es un título breve del riesgo; descripcion_riesgo lo explica en 1-3 oraciones.
- extracto_reporte es una cita textual corta del reporte que sustenta el análisis.
- La recomendación solo puede apoyarse en los fragmentos normativos numerados suministrados, citándolos como [n];
  numeros_citas_estrategicas solo puede contener números suministrados. Si ninguno aplica, deja la recomendación vacía."""


# ---------------------------------------------------------------------------
# Utilidades comunes
# ---------------------------------------------------------------------------
def get_active_config() -> ConfiguracionIARAG | None:
    return ConfiguracionIARAG.objects.filter(activa=True).order_by('-creado_en', '-id').first()


def incident_query_text(incidencia) -> str:
    activo = incidencia.activo_reportado.nombre if incidencia.activo_reportado else (incidencia.activo_texto or NO_DETERMINADO)
    return f'{incidencia.titulo}\nActivo: {activo}\n{incidencia.descripcion}'


def numbered_context(hits) -> str:
    if not hits:
        return '(sin fragmentos normativos aplicables)'
    lines = []
    for number, hit in enumerate(hits, start=1):
        fragmento = hit.fragmento
        version = fragmento.version_documento
        lines.append(
            f'[{number}] {version.documento.codigo} {version.version}, págs. {fragmento.pagina_inicio}-{fragmento.pagina_fin} '
            f'(similitud {hit.score:.2f}):\n{fragmento.contenido[:MAX_FRAGMENT_CHARS_IN_PROMPT]}'
        )
    return '\n\n'.join(lines)


def verified_citation_numbers(declared: list[int], texts: list[str | None], total: int) -> list[int]:
    """Solo números 1..total, ya sea declarados o referenciados como [n] en los textos (prohibido inventar citas)."""
    found = set(declared or [])
    for text in texts:
        found.update(int(n) for n in CITATION_RE.findall(text or ''))
    return sorted(n for n in found if 1 <= n <= total)


def strip_invalid_citations(text: str | None, valid: list[int]) -> str | None:
    if text is None:
        return None
    cleaned = CITATION_RE.sub(lambda m: m.group(0) if int(m.group(1)) in valid else '', text)
    cleaned = re.sub(r'[ \t]+([.,;:])', r'\1', re.sub(r'[ \t]{2,}', ' ', cleaned))
    return cleaned.strip()


MIN_SENTENCE_CHARS = 20


def first_sentence(contenido: str) -> str:
    """Primera oración con contenido del fragmento, omitiendo el prefijo [Documento: ...] y los encabezados Markdown."""
    lines = [
        line for line in contenido.splitlines()
        if line.strip() and not line.startswith('[Documento:') and not line.lstrip().startswith('#')
    ]
    body = ' '.join(re.sub(r'[*_`>|]+', ' ', ' '.join(lines)).split())
    for sentence in re.split(r'(?<=[.!?])\s+', body):
        if len(sentence) >= MIN_SENTENCE_CHARS:
            return sentence[:MAX_RESUMEN_CHARS]
    return (body or contenido)[:MAX_RESUMEN_CHARS]


def _clean(value: str | None) -> str:
    value = (value or '').strip()
    return value if value else NO_DETERMINADO


class TaskLifecycle:
    @staticmethod
    def claim(tarea_id: int, rama: str) -> TareaIA | None:
        """Pasa la tarea de PENDIENTE a PROCESANDO; cualquier otro estado se omite (idempotencia)."""
        with transaction.atomic():
            tarea = (
                TareaIA.objects.select_for_update(of=('self',))  # Solo la fila de TAREA_IA (hay LEFT JOIN anulables).
                .select_related('incidencia__activo_reportado', 'incidencia__reportante', 'solicitada_por')
                .filter(pk=tarea_id, rama=rama).first()
            )
            if tarea is None or tarea.estado != EstadoTareaIA.PENDIENTE:
                return None
            tarea.estado, tarea.iniciada_en = EstadoTareaIA.PROCESANDO, timezone.now()
            tarea.save(update_fields=['estado', 'iniciada_en'])
            return tarea

    @staticmethod
    def complete(tarea: TareaIA, *, proveedor: str, modelo: str) -> None:
        tarea.estado, tarea.terminada_en = EstadoTareaIA.COMPLETADA, timezone.now()
        tarea.proveedor, tarea.modelo = proveedor, modelo
        tarea.error_codigo = tarea.error_detalle = None
        tarea.save(update_fields=['estado', 'terminada_en', 'proveedor', 'modelo', 'error_codigo', 'error_detalle'])

    @staticmethod
    def fail(tarea: TareaIA, exc: BaseException) -> None:
        TareaIA.objects.filter(pk=tarea.pk).update(
            estado=EstadoTareaIA.ERROR, terminada_en=timezone.now(),
            error_codigo=type(exc).__name__[:ERROR_CODIGO_MAX_CHARS], error_detalle=str(exc)[:MAX_ERROR_CHARS],
        )


def escalate_if_analyzing(incidencia, actor, motivo: str) -> bool:
    """Deriva a PENDIENTE_ATENCION_HUMANA solo si la incidencia sigue en análisis (no pisa EN_ATENCION ni CERRADA)."""
    with transaction.atomic():
        locked, estado = IncidentService._lock_with_status(incidencia.pk)
        if estado not in (EstadoIncidencia.REGISTRADA, EstadoIncidencia.EN_ANALISIS):
            return False
        IncidentService.transition(locked, EstadoIncidencia.PENDIENTE_ATENCION_HUMANA, actor, motivo)
        return True


# ---------------------------------------------------------------------------
# Rama Operativa
# ---------------------------------------------------------------------------
class OperationalRAGService:
    @staticmethod
    def deterministic_guidance(incidencia, hits) -> OperationalGuidanceLLMOutput:
        """Modo extractivo local: un paso por fragmento recuperado, citándolo literalmente."""
        pasos = [
            OperationalStepOutput(orden=n, instruccion=f'Aplica el lineamiento vigente: «{first_sentence(hit.fragmento.contenido)}» [{n}]')
            for n, hit in enumerate(hits[:3], start=1)
        ]
        return OperationalGuidanceLLMOutput(
            tipo=TipoOrientacion.SUGERENCIA,
            resumen=f'Se encontraron {len(pasos)} lineamiento(s) autorizado(s) aplicables a «{incidencia.titulo}».',
            advertencia='Orientación generada en modo extractivo local (sin proveedor de IA configurado); '
                        'si los pasos no resuelven el caso, indícalo para escalarlo a un analista.',
            pasos=pasos,
            numeros_citas_usadas=list(range(1, len(pasos) + 1)),
        )

    @classmethod
    def run(cls, tarea_id: int) -> dict:
        tarea = TaskLifecycle.claim(tarea_id, RamaTareaIA.OPERATIVA)
        if tarea is None:
            return {'status': 'skipped', 'tarea_id': tarea_id}
        incidencia, actor = tarea.incidencia, tarea.solicitada_por
        try:
            if SENSITIVE_RE.search(f'{incidencia.titulo} {incidencia.descripcion}'):
                return cls._persist(
                    tarea, tipo=TipoOrientacion.SENSIBLE, resumen=SENSIBLE_RESUMEN, advertencia=SENSIBLE_ADVERTENCIA, pasos=[], citas=[],
                    proveedor=DETERMINISTIC_PROVIDER, modelo='deteccion-sensible-v1',
                    motivo='Derivación automática: reporte sensible de seguridad que requiere contención por un analista.',
                )

            cfg = get_active_config()
            client = LLMClient(cfg)
            hits = FaissVectorStore.search_authorized_fragments(incident_query_text(incidencia), FINALIDADES_OPERATIVAS, cfg)
            if not hits:  # Barrera anti-alucinación: no se invoca al LLM.
                return cls._sin_respaldo(tarea, proveedor=client.provider_label, modelo=client.model_label)

            output = client.generate(
                system=OPERATIONAL_SYSTEM_PROMPT,
                user=f'Reporte de incidencia:\n{incident_query_text(incidencia)}\n\nFragmentos normativos autorizados:\n{numbered_context(hits)}',
                schema=OperationalGuidanceLLMOutput,
                fallback=lambda: cls.deterministic_guidance(incidencia, hits),
            )
            valid = verified_citation_numbers(output.numeros_citas_usadas, [p.instruccion for p in output.pasos], len(hits))
            pasos = [strip_invalid_citations(p.instruccion, valid) for p in sorted(output.pasos, key=lambda p: p.orden)]
            citas = [(n, hits[n - 1].fragmento) for n in valid]

            if output.tipo == TipoOrientacion.SENSIBLE:
                return cls._persist(
                    tarea, tipo=TipoOrientacion.SENSIBLE, resumen=output.resumen, advertencia=output.advertencia or SENSIBLE_ADVERTENCIA,
                    pasos=pasos, citas=citas, proveedor=client.provider_label, modelo=client.model_label,
                    motivo='Derivación automática: el modelo clasificó el reporte como incidente de seguridad sensible.',
                )
            if not citas:  # Sugerencia sin ninguna cita verificable: se trata como sin respaldo.
                return cls._sin_respaldo(tarea, proveedor=client.provider_label, modelo=client.model_label)
            return cls._persist(
                tarea, tipo=TipoOrientacion.SUGERENCIA, resumen=output.resumen, advertencia=output.advertencia, pasos=[p for p in pasos if p],
                citas=citas, proveedor=client.provider_label, modelo=client.model_label, motivo=None,
            )
        except Exception as exc:  # INV-01: la incidencia nunca queda huérfana.
            logger.exception('Fallo en la rama operativa de TAREA_IA %s', tarea.id)
            TaskLifecycle.fail(tarea, exc)
            escalate_if_analyzing(
                incidencia, actor, f'Fallo del proveedor de IA en la orientación operativa ({type(exc).__name__}); '
                                   'escalado a Analista N2.',
            )
            return {'status': 'error', 'tarea_id': tarea.id, 'error': f'{type(exc).__name__}: {exc}'}

    @classmethod
    def _sin_respaldo(cls, tarea, *, proveedor: str, modelo: str) -> dict:
        return cls._persist(
            tarea, tipo=TipoOrientacion.SIN_RESPALDO, resumen=SIN_RESPALDO_RESUMEN, advertencia=SIN_RESPALDO_ADVERTENCIA, pasos=[], citas=[],
            proveedor=proveedor, modelo=modelo,
            motivo='Sin respaldo documental autorizado sobre el umbral de similitud; escalado a Analista N2.',
        )

    @staticmethod
    def _persist(tarea, *, tipo, resumen, advertencia, pasos, citas, proveedor, modelo, motivo) -> dict:
        with transaction.atomic():
            orientacion = OrientacionOperativa.objects.create(tarea=tarea, tipo=tipo, resumen=resumen, advertencia=advertencia)
            PasoOrientacion.objects.bulk_create([
                PasoOrientacion(orientacion=orientacion, orden=orden, instruccion=instruccion)
                for orden, instruccion in enumerate(pasos, start=1)
            ])
            CitaOrientacion.objects.bulk_create([
                CitaOrientacion(orientacion=orientacion, numero=numero, fragmento=fragmento) for numero, fragmento in citas
            ])
            TaskLifecycle.complete(tarea, proveedor=proveedor, modelo=modelo)
            escalada = bool(motivo) and escalate_if_analyzing(tarea.incidencia, tarea.solicitada_por, motivo)
        return {'status': 'ok', 'tarea_id': tarea.id, 'tipo': tipo, 'citas': len(citas), 'escalada': escalada}


# ---------------------------------------------------------------------------
# Rama Estratégica
# ---------------------------------------------------------------------------
THREAT_RULES = [
    (r'phishing|suplant|correo sospech|credencial|contrase[ñn]a', 'Suplantación de identidad (phishing)',
     'Compromiso de credenciales corporativas'),
    (r'malware|virus|ransom|adjunto|\.zip', 'Distribución de malware', 'Infección de equipos o pérdida de información'),
    (r'acceso no autorizado|otro pa[ií]s|ubicaci[oó]n (desconocida|no habitual)|inicio de sesi[oó]n',
     'Acceso no autorizado', 'Exposición de información interna'),
    (r'respaldo|copia de seguridad|backup|restaur', 'Pérdida de datos', 'Imposibilidad de restaurar información reciente'),
    (r'vpn|acceso remoto|conexi[oó]n remota|no (puedo|logro) conectar', 'Indisponibilidad del acceso remoto',
     'Imposibilidad de operar de forma remota con los sistemas corporativos'),
    (r'acceso denegado|sin permiso|no abre', 'Indisponibilidad de acceso a la información',
     'Interrupción de procesos que dependen de la información'),
    (r'impresora|t[óo]ner|hojas en blanco', 'Falla de equipo', 'Interrupción menor de la operación'),
    (r'se reinicia|se apaga|pantalla azul', 'Falla de hardware o firmware del equipo', 'Pérdida de trabajo no guardado'),
    (r'lent|demora|congela|tiempo de espera|timeout|504|no responde|tarda', 'Interrupción o degradación del servicio',
     'Retraso en los procesos que dependen del activo'),
]


@dataclass(frozen=True)
class GroupingMatch:
    version: VersionRiesgo
    analisis: AnalisisIncidencia
    score: float


class StrategicRiskAnalysisService:
    @staticmethod
    def deterministic_extraction(incidencia, hits) -> StrategicExtractionLLMOutput:
        texto = f'{incidencia.titulo} {incidencia.descripcion}'.lower()
        amenaza, consecuencia = NO_DETERMINADO, NO_DETERMINADO
        for pattern, threat, consequence in THREAT_RULES:
            if re.search(pattern, texto):
                amenaza, consecuencia = threat, consequence
                break
        activo = incidencia.activo_reportado.nombre if incidencia.activo_reportado else (incidencia.activo_texto or NO_DETERMINADO)
        riesgo = f'{amenaza} en {activo}' if amenaza != NO_DETERMINADO else f'Riesgo operativo asociado a {activo}'
        recomendacion = f'Aplicar el lineamiento interno: «{first_sentence(hits[0].fragmento.contenido)}» [1]' if hits else None
        return StrategicExtractionLLMOutput(
            activo_identificado=activo,
            amenaza=amenaza,
            vulnerabilidad=NO_DETERMINADO,  # No inferible por reglas a partir del reporte.
            consecuencia=consecuencia,
            riesgo_candidato=riesgo[:255],
            descripcion_riesgo=f'Riesgo derivado del reporte «{incidencia.titulo}»: {incidencia.descripcion}'[:2000],
            extracto_reporte=incidencia.descripcion[:200],
            recomendacion=recomendacion,
            numeros_citas_estrategicas=[1] if hits else [],
        )

    @staticmethod
    def signature(*, activo: str, amenaza: str, consecuencia: str, titulo: str, descripcion: str) -> str:
        return f'Activo: {activo}. Amenaza: {amenaza}. Consecuencia: {consecuencia}. Reporte: {titulo}. {descripcion}'

    @classmethod
    def _analysis_signature(cls, analisis: AnalisisIncidencia) -> str:
        incidencia = analisis.tarea.incidencia
        return cls.signature(
            activo=analisis.activo_identificado or NO_DETERMINADO, amenaza=analisis.amenaza or NO_DETERMINADO,
            consecuencia=analisis.consecuencia or NO_DETERMINADO, titulo=incidencia.titulo, descripcion=incidencia.descripcion,
        )

    @classmethod
    def find_best_match(cls, analisis: AnalisisIncidencia, cfg) -> GroupingMatch | None:
        """Mayor similitud coseno contra los análisis vinculados (no retirados) a versiones de riesgo existentes."""
        vinculos = list(
            VersionIncidencia.objects.exclude(estado=EstadoVinculo.RETIRADA)
            .exclude(analisis__tarea__incidencia_id=analisis.tarea.incidencia_id)
            .select_related('analisis__tarea__incidencia', 'version__riesgo')
        )
        if not vinculos:
            return None
        vectors = EmbeddingProviderService.embed_texts(
            [cls._analysis_signature(analisis)] + [cls._analysis_signature(v.analisis) for v in vinculos], cfg,
        )
        scores = vectors[1:] @ vectors[0]
        best = int(np.argmax(scores))
        return GroupingMatch(version=vinculos[best].version, analisis=vinculos[best].analisis, score=float(scores[best]))

    @classmethod
    def run(cls, tarea_id: int) -> dict:
        tarea = TaskLifecycle.claim(tarea_id, RamaTareaIA.ESTRATEGICA)
        if tarea is None:
            return {'status': 'skipped', 'tarea_id': tarea_id}
        incidencia = tarea.incidencia
        try:
            # INV-02: la rama estratégica no consulta ni depende del estado operativo de la incidencia.
            cfg = get_active_config()
            client = LLMClient(cfg)
            hits = FaissVectorStore.search_authorized_fragments(incident_query_text(incidencia), FINALIDADES_ESTRATEGICAS, cfg)
            output = client.generate(
                system=STRATEGIC_SYSTEM_PROMPT,
                user=f'Reporte de incidencia:\n{incident_query_text(incidencia)}\n\nFragmentos normativos autorizados:\n{numbered_context(hits)}',
                schema=StrategicExtractionLLMOutput,
                fallback=lambda: cls.deterministic_extraction(incidencia, hits),
            )
            valid = verified_citation_numbers(output.numeros_citas_estrategicas, [output.recomendacion], len(hits))
            recomendacion = strip_invalid_citations(output.recomendacion, valid) or None
            citas = [(n, hits[n - 1].fragmento) for n in valid]
            return cls._persist(tarea, cfg, client, output, recomendacion, citas)
        except Exception as exc:
            logger.exception('Fallo en la rama estratégica de TAREA_IA %s', tarea.id)
            TaskLifecycle.fail(tarea, exc)
            return {'status': 'error', 'tarea_id': tarea.id, 'error': f'{type(exc).__name__}: {exc}'}

    @classmethod
    def _persist(cls, tarea, cfg, client, output, recomendacion, citas) -> dict:
        threshold = float(settings.RISK_GROUPING_THRESHOLD)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_xact_lock(%s)', [GROUPING_LOCK_KEY])

            analisis = AnalisisIncidencia.objects.create(
                tarea=tarea,
                activo_identificado=_clean(output.activo_identificado)[:255],
                amenaza=_clean(output.amenaza),
                vulnerabilidad=_clean(output.vulnerabilidad),
                consecuencia=_clean(output.consecuencia),
                riesgo_candidato=output.riesgo_candidato,
            )
            match = cls.find_best_match(analisis, cfg)
            version_fields = {
                'origen': OrigenVersionRiesgo.IA,
                'creada_por': tarea.solicitada_por,
                'titulo': output.riesgo_candidato[:255],
                'descripcion': output.descripcion_riesgo,
                'amenaza': analisis.amenaza,
                'vulnerabilidad': analisis.vulnerabilidad,
                'consecuencia': analisis.consecuencia,
                'recomendacion': recomendacion,
                'origen_recomendacion': (OrigenRecomendacion.NORMATIVA_INTERNA if citas else OrigenRecomendacion.IA) if recomendacion else None,
            }
            referencia = f'INC-{tarea.incidencia_id:04d}'

            if match and match.score >= threshold:
                riesgo = match.version.riesgo
                latest = riesgo.versiones.order_by('-numero').first()
                motivo = (f'Similitud semántica {match.score:.2f} con INC-{match.analisis.tarea.incidencia_id:04d} '
                          f'(misma huella de activo/amenaza en {riesgo.codigo}).')
                if DecisionRiesgo.objects.filter(version=latest).exists():
                    # Recurrencia sobre un riesgo ya decidido: nueva propuesta de versión para alertar al analista.
                    version = VersionRiesgo.objects.create(riesgo=riesgo, numero=latest.numero + 1, **version_fields)
                    caso, nueva_version = CasoAgrupacion.RECURRENCIA_NUEVA_VERSION, True
                else:
                    version, caso, nueva_version = latest, CasoAgrupacion.AGRUPACION, False
                similitud = match.score
            else:
                riesgo = Riesgo.objects.create(codigo='RSG-PENDIENTE')
                riesgo.codigo = f'RSG-{riesgo.id:04d}'
                riesgo.save(update_fields=['codigo'])
                version = VersionRiesgo.objects.create(riesgo=riesgo, numero=1, **version_fields)
                caso, nueva_version, similitud, motivo = CasoAgrupacion.NUEVO_RIESGO, True, SIMILITUD_ORIGEN, 'Incidencia de origen.'

            VersionIncidencia.objects.create(
                version=version, analisis=analisis, estado=EstadoVinculo.SUGERIDA,
                similitud=Decimal(f'{min(max(similitud, 0.0), 1.0):.4f}'), motivo_similitud=motivo,
                extracto_reporte=output.extracto_reporte[:2000],
            )
            if nueva_version:
                CitaVersionRiesgo.objects.bulk_create([
                    CitaVersionRiesgo(version=version, numero=numero, fragmento=fragmento) for numero, fragmento in citas
                ])
            TaskLifecycle.complete(tarea, proveedor=client.provider_label, modelo=client.model_label)
            AuditService.log(
                accion=AccionAuditoria.ANALIZAR_RIESGO_INCIDENCIA, incidencia=tarea.incidencia, version_riesgo=version,
                detalle=f'{referencia} caso={caso} riesgo={riesgo.codigo} v{version.numero} similitud={similitud:.4f} '
                        f'citas={len(citas) if nueva_version else 0} proveedor={client.provider_label}',
            )
        return {
            'status': 'ok', 'tarea_id': tarea.id, 'caso': caso, 'riesgo': riesgo.codigo,
            'version': version.numero, 'similitud': round(similitud, 4),
        }


class StrategicRetryService:
    @staticmethod
    @transaction.atomic
    def retry(incidencia, actor) -> TareaIA:
        IncidentService._lock_with_status(incidencia.pk)
        anterior = latest_task(incidencia, RamaTareaIA.ESTRATEGICA)
        if anterior is None or anterior.estado != EstadoTareaIA.ERROR:
            estado = anterior.estado if anterior else 'inexistente'
            raise ValidationError({'tarea_ia': msg.REINTENTO_FUERA_DE_ESTADO.format(estado=estado)})
        cfg = get_active_config()
        intento = anterior.intento + 1
        tarea = TareaIA.objects.create(
            incidencia=incidencia, rama=RamaTareaIA.ESTRATEGICA, intento=intento,
            clave_idempotencia=f'inc-{incidencia.id}-est-v{intento}', estado=EstadoTareaIA.PENDIENTE,
            proveedor=getattr(cfg, 'proveedor_llm', None), modelo=getattr(cfg, 'modelo_llm', None),
            version_configuracion=getattr(cfg, 'version_configuracion', None), solicitada_por=actor,
        )
        AuditService.log(
            actor=actor, incidencia=incidencia, accion=AccionAuditoria.REINTENTAR_ANALISIS_ESTRATEGICO,
            detalle=f'tarea_anterior={anterior.id} ({anterior.error_codigo}) nueva_tarea={tarea.id} intento={intento}',
        )
        tarea_id = tarea.id
        transaction.on_commit(lambda: dispatch_ai_tasks(tarea_id))
        return tarea


# ---------------------------------------------------------------------------
# Gobierno de riesgos (v0.6): depuración de agrupaciones, evaluación 5x5 y decisiones ISO/IEC 27005
# ---------------------------------------------------------------------------


def risk_version_queryset():
    """VERSION_RIESGO con estado derivado de DECISION_RIESGO, indicador de recurrencia y relaciones precargadas."""
    estado_incidencia = Subquery(
        HistorialEstadoIncidencia.objects.filter(incidencia_id=OuterRef('analisis__tarea__incidencia_id'))
        .order_by('-ocurrido_en', '-id').values('estado')[:1]
    )
    anteriores = VersionRiesgo.objects.filter(riesgo_id=OuterRef('riesgo_id'), numero__lt=OuterRef('numero'))
    return (
        VersionRiesgo.objects.select_related(
            'riesgo', 'creada_por', 'activo_confirmado', 'agrupacion_confirmada_por',
            'evaluacion__celda__nivel', 'evaluacion__celda__matriz', 'evaluacion__evaluador', 'decision__analista',
        )
        .annotate(
            estado=Coalesce('decision__accion', Value(EstadoVersionRiesgo.PENDIENTE), output_field=CharField()),
            posible_recurrencia=Exists(anteriores.filter(decision__accion=AccionDecisionRiesgo.VALIDADA)),
            version_anterior_id=Subquery(anteriores.order_by('-numero').values('id')[:1]),
        )
        .prefetch_related(
            Prefetch('citas', queryset=CitaVersionRiesgo.objects.select_related('fragmento__version_documento__documento')),
            Prefetch('incidencias_vinculadas', queryset=VersionIncidencia.objects.select_related(
                'analisis__tarea__incidencia__activo_reportado', 'revisada_por',
            ).annotate(estado_incidencia=estado_incidencia).order_by('-similitud')),
        )
    )


class RiskGovernanceDecisionService:
    @staticmethod
    def _lock_pending(version: VersionRiesgo) -> VersionRiesgo:
        locked = VersionRiesgo.objects.select_for_update(of=('self',)).select_related('riesgo').get(pk=version.pk)
        if DecisionRiesgo.objects.filter(version=locked).exists():
            raise ValidationError({'version': msg.VERSION_YA_DECIDIDA})
        return locked

    @staticmethod
    def _reset_grouping_confirmation(version: VersionRiesgo) -> bool:
        if version.agrupacion_confirmada_por_id is None:
            return False
        version.agrupacion_confirmada_por, version.agrupacion_confirmada_en = None, None
        version.save(update_fields=['agrupacion_confirmada_por', 'agrupacion_confirmada_en'])
        return True

    @staticmethod
    def _link(version: VersionRiesgo, analisis_id: int) -> VersionIncidencia:
        link = (
            VersionIncidencia.objects.select_for_update(of=('self',)).select_related('analisis__tarea__incidencia')
            .filter(version=version, analisis_id=analisis_id).first()
        )
        if link is None:
            raise NotFound(msg.INCIDENCIA_NO_VINCULADA)
        return link

    # -- Depuración de la agrupación ------------------------------------
    @classmethod
    @transaction.atomic
    def remove_incident(cls, *, version, analisis_id: int, actor, motivo_retiro: str) -> VersionRiesgo:
        version = cls._lock_pending(version)
        link = cls._link(version, analisis_id)
        if link.estado == EstadoVinculo.RETIRADA:
            raise ValidationError({'estado': msg.INCIDENCIA_YA_RETIRADA})
        # La fila histórica nunca se elimina: se marca RETIRADA con motivo y revisor.
        VersionIncidencia.objects.filter(version=version, analisis_id=analisis_id).update(
            estado=EstadoVinculo.RETIRADA, motivo_retiro=motivo_retiro, revisada_por=actor, revisada_en=timezone.now(),
        )
        reset = cls._reset_grouping_confirmation(version)
        AuditService.log(
            actor=actor, accion=AccionAuditoria.RETIRAR_INCIDENCIA_AGRUPACION, version_riesgo=version, incidencia=link.analisis.tarea.incidencia,
            detalle=f'{version.riesgo.codigo} v{version.numero} INC-{link.analisis.tarea.incidencia_id:04d} '
                    f'motivo={motivo_retiro} confirmacion_reiniciada={reset}',
        )
        return version

    @classmethod
    @transaction.atomic
    def restore_incident(cls, *, version, analisis_id: int, actor, observacion: str = '') -> VersionRiesgo:
        version = cls._lock_pending(version)
        link = cls._link(version, analisis_id)
        if link.estado != EstadoVinculo.RETIRADA:
            raise ValidationError({'estado': msg.SOLO_RESTAURAR_RETIRADAS})
        VersionIncidencia.objects.filter(version=version, analisis_id=analisis_id).update(
            estado=EstadoVinculo.SUGERIDA, motivo_retiro=None, revisada_por=actor, revisada_en=timezone.now(),
        )
        reset = cls._reset_grouping_confirmation(version)
        AuditService.log(
            actor=actor, accion=AccionAuditoria.RESTAURAR_INCIDENCIA_AGRUPACION, version_riesgo=version, incidencia=link.analisis.tarea.incidencia,
            detalle=f'{version.riesgo.codigo} v{version.numero} INC-{link.analisis.tarea.incidencia_id:04d} '
                    f'motivo_retiro_previo={link.motivo_retiro} observacion={observacion or "-"} confirmacion_reiniciada={reset}',
        )
        return version

    @classmethod
    @transaction.atomic
    def confirm_grouping(cls, *, version, actor, activo_confirmado, justificacion_cambio_activo: str = '') -> VersionRiesgo:
        version = cls._lock_pending(version)
        incluidas = VersionIncidencia.objects.filter(version=version).exclude(estado=EstadoVinculo.RETIRADA)
        if not incluidas.exists():
            raise ValidationError({'agrupacion': msg.AGRUPACION_VACIA})
        reportados = set(
            incluidas.exclude(analisis__tarea__incidencia__activo_reportado__isnull=True)
            .values_list('analisis__tarea__incidencia__activo_reportado_id', flat=True)
        )
        justificacion = (justificacion_cambio_activo or '').strip()
        if reportados and activo_confirmado.id not in reportados and len(justificacion) < MIN_JUSTIFICACION_CAMBIO_ACTIVO:
            raise ValidationError({
                'justificacion_cambio_activo': msg.CAMBIO_ACTIVO_SIN_JUSTIFICAR.format(minimo=MIN_JUSTIFICACION_CAMBIO_ACTIVO),
            })
        ahora = timezone.now()
        version.activo_confirmado, version.agrupacion_confirmada_por, version.agrupacion_confirmada_en = activo_confirmado, actor, ahora
        version.save(update_fields=['activo_confirmado', 'agrupacion_confirmada_por', 'agrupacion_confirmada_en'])
        confirmadas = incluidas.update(estado=EstadoVinculo.CONFIRMADA, revisada_por=actor, revisada_en=ahora)
        AuditService.log(
            actor=actor, accion=AccionAuditoria.CONFIRMAR_AGRUPACION_RIESGO, version_riesgo=version, activo=activo_confirmado,
            detalle=f'{version.riesgo.codigo} v{version.numero} activo={activo_confirmado.codigo} incidencias={confirmadas}'
                    + (f' justificacion_cambio_activo={justificacion}' if justificacion else ''),
        )
        return version

    # -- Evaluación en matriz 5x5 (INV-04) -------------------------------
    @classmethod
    @transaction.atomic
    def evaluate(cls, *, version, actor, probabilidad: int, impacto: int, justificacion: str) -> EvaluacionRiesgo:
        version = cls._lock_pending(version)
        matriz = ConfiguracionMatriz.objects.filter(activa=True).order_by('-creada_en', '-id').first()
        if matriz is None:
            raise ValidationError({'matriz': msg.SIN_MATRIZ_ACTIVA})
        celda = CeldaMatriz.objects.select_related('nivel').filter(matriz=matriz, probabilidad=probabilidad, impacto=impacto).first()
        if celda is None:
            raise ValidationError({'matriz': msg.CELDA_NO_ENCONTRADA})
        evaluacion, creada = EvaluacionRiesgo.objects.update_or_create(
            version=version,
            defaults={'celda': celda, 'evaluador': actor, 'justificacion': justificacion.strip(), 'evaluada_en': timezone.now()},
        )
        AuditService.log(
            actor=actor, accion=AccionAuditoria.EVALUAR_RIESGO, version_riesgo=version, matriz=matriz,
            detalle=f'{version.riesgo.codigo} v{version.numero} P{probabilidad} x I{impacto} = {celda.nivel.codigo} '
                    f'celda={celda.id} matriz={matriz.version} {"nueva" if creada else "reevaluacion"}',
        )
        return evaluacion

    # -- Decisión ISO/IEC 27005 ------------------------------------------
    @staticmethod
    def _validate_validation_preconditions(version: VersionRiesgo, data: dict) -> None:
        if not version.activo_confirmado_id or not version.agrupacion_confirmada_por_id:
            raise ValidationError({'agrupacion': msg.VALIDAR_SIN_AGRUPACION})
        evaluacion = EvaluacionRiesgo.objects.filter(version=version).first()
        if not evaluacion or len((evaluacion.justificacion or '').strip()) < MIN_JUSTIFICACION:
            raise ValidationError({'evaluacion': msg.VALIDAR_SIN_EVALUACION})
        sin_fuentes = (data.get('justificacion_sin_fuentes') or '').strip()
        if not CitaVersionRiesgo.objects.filter(version=version).exists() and len(sin_fuentes) < MIN_JUSTIFICACION:
            raise ValidationError({'justificacion_sin_fuentes': msg.VALIDAR_SIN_FUENTES.format(minimo=MIN_JUSTIFICACION)})

    @staticmethod
    def _clone_corrected(version: VersionRiesgo, actor, data: dict) -> VersionRiesgo:
        numero = (VersionRiesgo.objects.filter(riesgo=version.riesgo).aggregate(m=Max('numero'))['m'] or version.numero) + 1
        campos = {f: (data.get(f) or '').strip() or getattr(version, f) for f in CORRECTABLE_FIELDS}
        nueva = VersionRiesgo.objects.create(
            riesgo=version.riesgo, numero=numero, origen=OrigenVersionRiesgo.ANALISTA, creada_por=actor,
            origen_recomendacion=OrigenRecomendacion.ANALISTA if (data.get('recomendacion') or '').strip() else version.origen_recomendacion,
            activo_confirmado=version.activo_confirmado,
            agrupacion_confirmada_por=version.agrupacion_confirmada_por,
            agrupacion_confirmada_en=version.agrupacion_confirmada_en,
            **campos,
        )
        VersionIncidencia.objects.bulk_create([
            VersionIncidencia(
                version=nueva, analisis_id=link.analisis_id, estado=link.estado, similitud=link.similitud,
                motivo_similitud=link.motivo_similitud, extracto_reporte=link.extracto_reporte,
                revisada_por_id=link.revisada_por_id, revisada_en=link.revisada_en, motivo_retiro=link.motivo_retiro,
            )
            for link in VersionIncidencia.objects.filter(version=version)
        ])
        CitaVersionRiesgo.objects.bulk_create([
            CitaVersionRiesgo(version=nueva, numero=cita.numero, fragmento_id=cita.fragmento_id)
            for cita in CitaVersionRiesgo.objects.filter(version=version)
        ])
        return nueva

    @classmethod
    @transaction.atomic
    def decide(cls, *, version, actor, data: dict) -> tuple[DecisionRiesgo, VersionRiesgo | None]:
        version = cls._lock_pending(version)
        accion = data['accion']
        if accion == AccionDecisionRiesgo.VALIDADA:
            cls._validate_validation_preconditions(version, data)
        decision = DecisionRiesgo.objects.create(
            version=version, accion=accion, analista=actor,
            observacion=(data.get('observacion') or '').strip() or None,
            justificacion_sin_fuentes=(data.get('justificacion_sin_fuentes') or '').strip() or None,
        )
        nueva = cls._clone_corrected(version, actor, data) if accion == AccionDecisionRiesgo.CORREGIDA else None
        AuditService.log(
            actor=actor, accion=AccionAuditoria.DECIDIR_VERSION_RIESGO, version_riesgo=version, activo=version.activo_confirmado,
            detalle=f'{version.riesgo.codigo} v{version.numero} accion={accion}'
                    + (f' nueva_version=v{nueva.numero}' if nueva else ''),
        )
        return decision, nueva


# ---------------------------------------------------------------------------
# Tablero de indicadores (sin duplicar riesgos con múltiples versiones)
# ---------------------------------------------------------------------------
class RiskDashboardAggregationService:
    SERIE_DIAS = 30

    @classmethod
    def build(cls) -> dict:
        # Equivalente a DISTINCT ON (riesgo_id): última versión VALIDADA y última pendiente por RIESGO.
        ultima_validada = VersionRiesgo.objects.filter(riesgo_id=OuterRef('id'), decision__accion=AccionDecisionRiesgo.VALIDADA).order_by('-numero', '-id')
        pendiente = VersionRiesgo.objects.filter(riesgo_id=OuterRef('id'), decision__isnull=True).order_by('-numero', '-id')
        riesgos = list(
            Riesgo.objects.annotate(
                vigente_id=Subquery(ultima_validada.values('id')[:1]),
                pendiente_id=Subquery(pendiente.values('id')[:1]),
                pendiente_numero=Subquery(pendiente.values('numero')[:1]),
            ).order_by('codigo')
        )
        vigentes = [r for r in riesgos if r.vigente_id]
        versiones = VersionRiesgo.objects.select_related(
            'activo_confirmado', 'evaluacion__celda__nivel', 'decision',
        ).in_bulk([r.vigente_id for r in vigentes])
        incidencias_por_riesgo = dict(
            VersionIncidencia.objects.exclude(estado=EstadoVinculo.RETIRADA)
            .values('version__riesgo_id').annotate(total=Count('analisis__tarea__incidencia_id', distinct=True))
            .values_list('version__riesgo_id', 'total')
        )

        niveles = {n.codigo: {'nivel_codigo': n.codigo, 'orden': n.orden, 'total': 0} for n in NivelRiesgo.objects.order_by('orden')}
        registro = []
        for riesgo in vigentes:
            version = versiones[riesgo.vigente_id]
            evaluacion = getattr(version, 'evaluacion', None)
            nivel = evaluacion.celda.nivel.codigo if evaluacion else None
            if nivel in niveles:
                niveles[nivel]['total'] += 1
            registro.append({
                'riesgo_id': riesgo.id, 'riesgo_codigo': riesgo.codigo,
                'version_vigente_id': version.id, 'version_vigente_numero': version.numero, 'titulo': version.titulo,
                'activo_confirmado_id': version.activo_confirmado_id,
                'activo_confirmado_nombre': version.activo_confirmado.nombre if version.activo_confirmado else None,
                'nivel_codigo': nivel,
                'probabilidad': evaluacion.celda.probabilidad if evaluacion else None,
                'impacto': evaluacion.celda.impacto if evaluacion else None,
                'validada_en': version.decision.decidida_en,
                'total_incidencias': incidencias_por_riesgo.get(riesgo.id, 0),
                'propuesta_pendiente_id': riesgo.pendiente_id, 'propuesta_pendiente_numero': riesgo.pendiente_numero,
            })

        pendientes = VersionRiesgo.objects.filter(decision__isnull=True)
        recurrencia = Exists(VersionRiesgo.objects.filter(
            riesgo_id=OuterRef('riesgo_id'), numero__lt=OuterRef('numero'), decision__accion=AccionDecisionRiesgo.VALIDADA,
        ))
        return {
            'generado_en': timezone.now(),
            'total_riesgos': len(riesgos),
            'total_riesgos_vigentes': len(vigentes),
            'riesgos_vigentes_por_nivel': list(niveles.values()),
            'propuestas_pendientes': pendientes.count(),
            'propuestas_nuevas_agrupaciones': pendientes.filter(agrupacion_confirmada_por__isnull=True).count(),
            'propuestas_pendientes_revision': pendientes.filter(agrupacion_confirmada_por__isnull=False).count(),
            'propuestas_posible_recurrencia': pendientes.filter(recurrencia).count(),
            'versiones_rechazadas': VersionRiesgo.objects.filter(decision__accion=AccionDecisionRiesgo.RECHAZADA).count(),
            'incidencias_por_estado': cls._incidents_by_status(),
            'incidencias_por_activo': cls._incidents_by_asset(),
            'serie_incidencias': cls._incident_series(),
            'registro_riesgos': registro,
        }

    @staticmethod
    def _incidents_by_status() -> dict:
        conteo = {estado.value: 0 for estado in EstadoIncidencia}
        filas = (
            Incidencia.objects.annotate(estado_actual=current_status_subquery())
            .values('estado_actual').annotate(total=Count('id')).values_list('estado_actual', 'total')
        )
        for estado, total in filas:
            conteo[estado] = conteo.get(estado, 0) + total
        return conteo

    @staticmethod
    def _incidents_by_asset() -> list[dict]:
        filas = (
            Incidencia.objects.values('activo_reportado_id', 'activo_reportado__nombre')
            .annotate(total=Count('id')).order_by('-total', 'activo_reportado__nombre')
        )
        return [
            {'activo_id': f['activo_reportado_id'], 'activo_nombre': f['activo_reportado__nombre'] or 'Activo fuera del catálogo',
             'total': f['total']}
            for f in filas
        ]

    @classmethod
    def _incident_series(cls) -> list[dict]:
        hoy = timezone.localdate()
        desde = hoy - timedelta(days=cls.SERIE_DIAS - 1)
        filas = dict(
            Incidencia.objects.annotate(fecha=TruncDate('registrada_en', tzinfo=timezone.get_current_timezone()))
            .filter(fecha__gte=desde)
            .values('fecha').annotate(total=Count('id')).values_list('fecha', 'total')
        )
        return [
            {'fecha': (desde + timedelta(days=i)).isoformat(), 'total': filas.get(desde + timedelta(days=i), 0)}
            for i in range(cls.SERIE_DIAS)
        ]
