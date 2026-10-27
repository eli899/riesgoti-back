"""
Casos de uso transaccionales de incidencias: registro (INV-01), feedback del reportante (INV-02)
y atención humana N2 (INV-03). El estado actual de una incidencia es siempre el último registro de
HISTORIAL_ESTADO_INCIDENCIA ordenado por (ocurrido_en, id).
"""
import hashlib
import logging
import os
import tempfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone
from django.utils.text import get_valid_filename
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.ai_config.models import ConfiguracionIARAG
from apps.audit.constants import AccionAuditoria
from apps.audit.services import AuditService
from apps.incidents import messages as msg
from apps.incidents.constants import ATENCION_TEXTO_MIN_LENGTH, EstadoIncidencia, ResultadoOrientacion
from apps.incidents.models import AtencionIncidencia, EvidenciaIncidencia, HistorialEstadoIncidencia, Incidencia
from apps.risks.constants import EstadoTareaIA, RamaTareaIA, TipoOrientacion
from apps.risks.models import OrientacionOperativa, RespuestaOrientacion, TareaIA
from config.constants import IO_BLOCK_BYTES

logger = logging.getLogger(__name__)


def current_status_subquery():
    return Subquery(
        HistorialEstadoIncidencia.objects.filter(incidencia=OuterRef('pk')).order_by('-ocurrido_en', '-id').values('estado')[:1]
    )


def evidence_absolute_path(clave_archivo: str) -> Path:
    return Path(settings.EVIDENCE_STORAGE_ROOT) / clave_archivo


def latest_task(incidencia: Incidencia, rama: str) -> TareaIA | None:
    return incidencia.tareas_ia.filter(rama=rama).order_by('-intento', '-id').first()


class IncidentService:
    @staticmethod
    def get_current_status(incidencia: Incidencia) -> str:
        annotated = getattr(incidencia, 'estado_actual', None)
        if annotated:
            return annotated
        last_entry = incidencia.historial_estados.order_by('-ocurrido_en', '-id').first()
        return last_entry.estado if last_entry else EstadoIncidencia.REGISTRADA

    @staticmethod
    def _lock_with_status(incidencia_id: int) -> tuple[Incidencia, str]:
        incidencia = Incidencia.objects.select_for_update().get(pk=incidencia_id)
        return incidencia, IncidentService.get_current_status(incidencia)

    @staticmethod
    def transition(incidencia: Incidencia, estado: str, actor, motivo: str) -> HistorialEstadoIncidencia:
        """
        Agrega un estado garantizando que quede ordenado después del último registrado: ocurrido_en es monotónico
        aunque el reloj del servidor retroceda (ajustes NTP) o exista historial fechado en el futuro.
        """
        entry = HistorialEstadoIncidencia.objects.create(incidencia=incidencia, estado=estado, actor=actor, motivo=motivo)
        previo = (
            HistorialEstadoIncidencia.objects.filter(incidencia=incidencia).exclude(pk=entry.pk)
            .order_by('-ocurrido_en', '-id').values_list('ocurrido_en', flat=True).first()
        )
        if previo is not None and entry.ocurrido_en <= previo:
            entry.ocurrido_en = previo + timedelta(microseconds=1)
            HistorialEstadoIncidencia.objects.filter(pk=entry.pk).update(ocurrido_en=entry.ocurrido_en)
        return entry

    # ------------------------------------------------------------------
    # Registro (INV-01)
    # ------------------------------------------------------------------
    @staticmethod
    def _stage_evidence(uploaded, tipo_mime: str) -> dict:
        """Copia el adjunto a un temporal calculando SHA-256 por bloques (sin cargarlo completo en memoria)."""
        root = Path(settings.EVIDENCE_STORAGE_ROOT)
        root.mkdir(parents=True, exist_ok=True)
        hasher, size = hashlib.sha256(), 0
        fd, tmp_name = tempfile.mkstemp(dir=root, prefix='.upload_')
        with os.fdopen(fd, 'wb') as handle:
            for block in uploaded.chunks(IO_BLOCK_BYTES):
                hasher.update(block)
                size += len(block)
                handle.write(block)
        return {
            'tmp_path': Path(tmp_name), 'sha256': hasher.hexdigest(), 'bytes': size,
            'uploaded': uploaded, 'tipo_mime': tipo_mime,
        }

    @staticmethod
    def _new_task(incidencia: Incidencia, rama: str, cfg, reportante) -> TareaIA:
        sufijo = 'op' if rama == RamaTareaIA.OPERATIVA else 'est'
        return TareaIA.objects.create(
            incidencia=incidencia,
            rama=rama,
            intento=1,
            clave_idempotencia=f'inc-{incidencia.id}-{sufijo}-v1',
            estado=EstadoTareaIA.PENDIENTE,
            proveedor=cfg.proveedor_llm if cfg else None,
            modelo=cfg.modelo_llm if cfg else None,
            version_configuracion=cfg.version_configuracion if cfg else None,
            solicitada_por=reportante,
        )

    @classmethod
    def create_incident_transactional(
        cls,
        *,
        reportante,
        titulo: str,
        descripcion: str,
        activo_reportado=None,
        activo_texto: str | None = None,
        archivos_evidencia: list[dict] | None = None,
    ) -> tuple[Incidencia, TareaIA, TareaIA]:
        """archivos_evidencia: [{'archivo': UploadedFile, 'tipo_mime': str validado por el DTO de entrada}]."""
        archivos_evidencia = archivos_evidencia or []
        cfg = ConfiguracionIARAG.objects.filter(activa=True).order_by('-creado_en', '-id').first()
        staged = [cls._stage_evidence(item['archivo'], item['tipo_mime']) for item in archivos_evidencia]
        stored: list[Path] = []
        try:
            with transaction.atomic():
                incidencia = Incidencia.objects.create(
                    reportante=reportante,
                    activo_reportado=activo_reportado,
                    activo_texto=(activo_texto or '').strip() or None,
                    titulo=titulo.strip(),
                    descripcion=descripcion.strip(),
                )

                for item in staged:
                    uploaded = item['uploaded']
                    safe_name = get_valid_filename(Path(uploaded.name).name)[:120] or 'evidencia'
                    clave = f'inc_{incidencia.id}/{item["sha256"][:12]}_{safe_name}'
                    destino = evidence_absolute_path(clave)
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(item['tmp_path'], destino)
                    stored.append(destino)
                    EvidenciaIncidencia.objects.create(
                        incidencia=incidencia,
                        nombre_original=Path(uploaded.name).name[:255],
                        clave_archivo=clave,
                        tipo_mime=item['tipo_mime'],
                        bytes=item['bytes'],
                        sha256=item['sha256'],
                    )

                cls.transition(incidencia, EstadoIncidencia.REGISTRADA, reportante, 'Registro inicial de incidencia por el reportante.')
                cls.transition(incidencia, EstadoIncidencia.EN_ANALISIS, reportante,
                               'Incidencia en análisis automático (ramas Operativa y Estratégica).')

                tarea_op = cls._new_task(incidencia, RamaTareaIA.OPERATIVA, cfg, reportante)
                tarea_est = cls._new_task(incidencia, RamaTareaIA.ESTRATEGICA, cfg, reportante)

                AuditService.log(
                    actor=reportante, incidencia=incidencia, activo=activo_reportado, accion=AccionAuditoria.REGISTRAR_INCIDENCIA,
                    detalle=f'Incidencia #{incidencia.id} registrada con {len(staged)} evidencia(s).',
                )
                op_id, est_id = tarea_op.id, tarea_est.id
                transaction.on_commit(lambda: dispatch_ai_tasks(op_id, est_id))
        except Exception:
            for item in staged:
                item['tmp_path'].unlink(missing_ok=True)
            for path in stored:
                path.unlink(missing_ok=True)
            raise
        return incidencia, tarea_op, tarea_est

    # ------------------------------------------------------------------
    # Feedback del reportante (INV-02)
    # ------------------------------------------------------------------
    @classmethod
    @transaction.atomic
    def register_orientation_feedback(cls, *, incidencia: Incidencia, actor, resultado: str) -> RespuestaOrientacion:
        incidencia, estado = cls._lock_with_status(incidencia.pk)
        if incidencia.reportante_id != actor.id:
            raise PermissionDenied(msg.SOLO_REPORTANTE_CONFIRMA)
        if estado != EstadoIncidencia.EN_ANALISIS:
            raise ValidationError({'estado': msg.CONFIRMACION_FUERA_DE_ESTADO.format(estado=estado)})

        tarea = latest_task(incidencia, RamaTareaIA.OPERATIVA)
        orientacion = OrientacionOperativa.objects.filter(tarea=tarea).first() if tarea else None
        if orientacion is None or orientacion.tipo != TipoOrientacion.SUGERENCIA:
            raise ValidationError({'orientacion': msg.SIN_SUGERENCIA})
        if RespuestaOrientacion.objects.filter(orientacion=orientacion).exists():
            raise ValidationError({'resultado': msg.ORIENTACION_YA_CONFIRMADA})

        respuesta = RespuestaOrientacion.objects.create(orientacion=orientacion, resultado=resultado)
        if resultado == ResultadoOrientacion.FUNCIONO:
            # INV-02: el cierre operativo no toca ni detiene TAREA_IA(rama='ESTRATEGICA').
            cls.transition(incidencia, EstadoIncidencia.CERRADA, actor,
                           'Resuelta mediante orientación operativa automática (confirmado por reportante).')
        else:
            cls.transition(incidencia, EstadoIncidencia.PENDIENTE_ATENCION_HUMANA, actor,
                           'La orientación operativa no resolvió el incidente; escalado a Analista N2.')
        AuditService.log(
            actor=actor, incidencia=incidencia, accion=AccionAuditoria.CONFIRMAR_ORIENTACION_OPERATIVA,
            detalle=f'resultado={resultado} tarea_operativa={tarea.id}',
        )
        return respuesta

    # ------------------------------------------------------------------
    # Atención humana N2 (INV-03)
    # ------------------------------------------------------------------
    @classmethod
    @transaction.atomic
    def start_attention(cls, *, incidencia: Incidencia, analista) -> AtencionIncidencia:
        incidencia, estado = cls._lock_with_status(incidencia.pk)
        atencion = AtencionIncidencia.objects.filter(incidencia=incidencia).first()

        if estado == EstadoIncidencia.EN_ATENCION and atencion and atencion.cerrada_en is None:
            if atencion.analista_id != analista.id:
                raise ValidationError({'estado': msg.YA_EN_ATENCION.format(analista=atencion.analista.nombre_completo)})
            return atencion  # Idempotente para el mismo analista.
        if estado not in (EstadoIncidencia.EN_ANALISIS, EstadoIncidencia.PENDIENTE_ATENCION_HUMANA):
            raise ValidationError({'estado': msg.ATENCION_FUERA_DE_ESTADO.format(estado=estado)})

        if atencion is None:
            atencion = AtencionIncidencia.objects.create(incidencia=incidencia, analista=analista)
        else:  # Reapertura tras un cierre previo: conserva acciones/notas como historial.
            atencion.analista, atencion.cerrada_en = analista, None
            atencion.save(update_fields=['analista', 'cerrada_en'])

        cls.transition(incidencia, EstadoIncidencia.EN_ATENCION, analista, f'Atención humana N2 iniciada por {analista.nombre_completo}.')
        AuditService.log(actor=analista, incidencia=incidencia, accion=AccionAuditoria.INICIAR_ATENCION_HUMANA, detalle=f'estado_previo={estado}')
        return atencion

    @classmethod
    @transaction.atomic
    def update_attention(cls, *, incidencia: Incidencia, analista, data: dict) -> AtencionIncidencia:
        incidencia, estado = cls._lock_with_status(incidencia.pk)
        atencion = AtencionIncidencia.objects.select_for_update().filter(incidencia=incidencia).first()
        if estado != EstadoIncidencia.EN_ATENCION or atencion is None:
            raise ValidationError({'estado': msg.SIN_ATENCION_INICIADA})
        if atencion.analista_id != analista.id:
            raise PermissionDenied(msg.SOLO_ANALISTA_ASIGNADO)

        for field in ('acciones', 'nota_resolucion'):
            if field in data:
                setattr(atencion, field, data[field])
        cerrar = data.get('cerrar', False)
        if cerrar:
            errores = {
                field: msg.CIERRE_TEXTO_CORTO.format(minimo=ATENCION_TEXTO_MIN_LENGTH)
                for field in ('acciones', 'nota_resolucion')
                if len((getattr(atencion, field) or '').strip()) < ATENCION_TEXTO_MIN_LENGTH
            }
            if errores:
                raise ValidationError(errores)
            atencion.cerrada_en = timezone.now()
        # INV-03: acciones y nota_resolucion quedan solo como historial; jamás se indexan en FAISS.
        atencion.save(update_fields=['acciones', 'nota_resolucion', 'cerrada_en'])

        if cerrar:
            cls.transition(incidencia, EstadoIncidencia.CERRADA, analista, 'Incidencia cerrada por el Analista N2 tras la atención humana.')
            AuditService.log(actor=analista, incidencia=incidencia, accion=AccionAuditoria.CERRAR_ATENCION_HUMANA,
                             detalle='Cierre operativo N2 (el riesgo asociado no se valida ni rechaza).')
        else:
            AuditService.log(actor=analista, incidencia=incidencia, accion=AccionAuditoria.REGISTRAR_AVANCE_ATENCION, detalle='Avance parcial N2.')
        return atencion


def dispatch_ai_tasks(*tarea_ids: int) -> None:
    """
    Encola las ramas Operativa y Estratégica tras el COMMIT (INV-01). Los workers se implementan en v0.5
    (apps.risks.tasks); mientras no existan, las TAREA_IA quedan en PENDIENTE para re-encolarse luego.
    """
    try:
        from apps.risks.tasks import run_operational_rag_task, run_strategic_risk_task
    except ImportError:
        logger.warning('Workers de IA no disponibles (apps.risks.tasks); TAREA_IA %s quedan en PENDIENTE.', tarea_ids)
        return
    tareas = {t.id: t.rama for t in TareaIA.objects.filter(id__in=tarea_ids)}
    for tarea_id in tarea_ids:
        task = run_operational_rag_task if tareas.get(tarea_id) == RamaTareaIA.OPERATIVA else run_strategic_risk_task
        task.delay(tarea_id)
