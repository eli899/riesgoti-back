from pathlib import Path

from django.conf import settings
from rest_framework import serializers

from apps.assets_matrix.models import Activo
from apps.incidents.services import FUNCIONO, NO_FUNCIONO, RAMA_ESTRATEGICA, RAMA_OPERATIVA

# Extensión -> (MIME servido, firmas binarias aceptadas). El MIME declarado por el cliente se ignora.
EVIDENCE_TYPES = {
    '.png': ('image/png', (b'\x89PNG\r\n\x1a\n',)),
    '.jpg': ('image/jpeg', (b'\xff\xd8\xff',)),
    '.jpeg': ('image/jpeg', (b'\xff\xd8\xff',)),
    '.pdf': ('application/pdf', (b'%PDF-',)),
    '.log': ('text/plain', ()),
    '.txt': ('text/plain', ()),
}


# ---------------------------------------------------------------------------
# DTOs de entrada
# ---------------------------------------------------------------------------
class IncidentCreateInputSerializer(serializers.Serializer):
    titulo = serializers.CharField(min_length=5, max_length=255)
    descripcion = serializers.CharField(min_length=20)
    activo_reportado_id = serializers.PrimaryKeyRelatedField(
        source='activo_reportado', queryset=Activo.objects.filter(activo=True), required=False, allow_null=True,
    )
    activo_texto = serializers.CharField(max_length=255, required=False, allow_blank=True, allow_null=True)
    evidencias = serializers.ListField(child=serializers.FileField(), required=False, allow_empty=True)

    def validate_evidencias(self, archivos):
        if len(archivos) > settings.MAX_EVIDENCES_PER_INCIDENT:
            raise serializers.ValidationError(f'Máximo {settings.MAX_EVIDENCES_PER_INCIDENT} evidencias por incidencia.')
        validados = []
        for archivo in archivos:
            nombre = Path(archivo.name).name
            extension = Path(nombre).suffix.lower()
            if extension not in EVIDENCE_TYPES:
                raise serializers.ValidationError(f'{nombre}: formato no permitido (png, jpg, pdf, log, txt).')
            if archivo.size > settings.MAX_EVIDENCE_BYTES:
                raise serializers.ValidationError(
                    f'{nombre}: supera el máximo de {settings.MAX_EVIDENCE_BYTES // (1024 * 1024)} MB.'
                )
            tipo_mime, firmas = EVIDENCE_TYPES[extension]
            archivo.seek(0)
            cabecera = archivo.read(1024)
            archivo.seek(0)
            if firmas and not any(cabecera.startswith(firma) for firma in firmas):
                raise serializers.ValidationError(f'{nombre}: el contenido no corresponde a la extensión {extension}.')
            if not firmas and b'\x00' in cabecera:
                raise serializers.ValidationError(f'{nombre}: un archivo de texto no puede contener datos binarios.')
            validados.append({'archivo': archivo, 'tipo_mime': tipo_mime})
        return validados

    def validate(self, attrs):
        if not attrs.get('activo_reportado') and not (attrs.get('activo_texto') or '').strip():
            raise serializers.ValidationError({
                'activo_reportado_id': 'Seleccione un activo del catálogo o describa el activo afectado en activo_texto.'
            })
        return attrs


class OrientationFeedbackInputSerializer(serializers.Serializer):
    resultado = serializers.ChoiceField(choices=[FUNCIONO, NO_FUNCIONO])


class HumanAttentionInputSerializer(serializers.Serializer):
    acciones = serializers.CharField(required=False, allow_blank=True, max_length=10000)
    nota_resolucion = serializers.CharField(required=False, allow_blank=True, max_length=10000)
    cerrar = serializers.BooleanField(default=False)


# ---------------------------------------------------------------------------
# Mappers de salida
# ---------------------------------------------------------------------------
def _tasks_by_branch(obj) -> dict:
    """Última tarea por rama usando el prefetch de tareas_ia (sin consultas adicionales)."""
    latest = {}
    for tarea in obj.tareas_ia.all():
        actual = latest.get(tarea.rama)
        if actual is None or (tarea.intento, tarea.id) > (actual.intento, actual.id):
            latest[tarea.rama] = tarea
    return latest


def _orientation_of(tarea):
    return getattr(tarea, 'orientacion_operativa', None) if tarea else None


def _response_of(orientacion):
    return getattr(orientacion, 'respuesta', None) if orientacion else None


class TareaIAResumenOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    rama = serializers.CharField()
    intento = serializers.IntegerField()
    estado = serializers.CharField()
    error_codigo = serializers.CharField(allow_null=True)
    error_detalle = serializers.CharField(allow_null=True)
    creada_en = serializers.DateTimeField()
    terminada_en = serializers.DateTimeField(allow_null=True)


class EvidenciaOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nombre_original = serializers.CharField()
    tipo_mime = serializers.CharField()
    bytes = serializers.IntegerField()
    sha256 = serializers.CharField()
    creada_en = serializers.DateTimeField()


class HistorialEstadoOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    estado = serializers.CharField()
    actor_id = serializers.IntegerField()
    actor_nombre = serializers.CharField(source='actor.nombre_completo')
    motivo = serializers.CharField(allow_null=True)
    ocurrido_en = serializers.DateTimeField()


class AtencionIncidenciaOutputSerializer(serializers.Serializer):
    incidencia_id = serializers.IntegerField()
    analista_id = serializers.IntegerField()
    analista_nombre = serializers.CharField(source='analista.nombre_completo')
    iniciada_en = serializers.DateTimeField()
    acciones = serializers.CharField(allow_null=True)
    nota_resolucion = serializers.CharField(allow_null=True)
    cerrada_en = serializers.DateTimeField(allow_null=True)


class IncidentListOutputSerializer(serializers.Serializer):
    """Fila de bandejas (reportante, cola N2 e historial general)."""

    id = serializers.IntegerField()
    referencia = serializers.SerializerMethodField()
    titulo = serializers.CharField()
    descripcion = serializers.CharField()
    activo_reportado_id = serializers.IntegerField(allow_null=True)
    activo_nombre = serializers.SerializerMethodField()
    activo_texto = serializers.CharField(allow_null=True)
    reportante_id = serializers.IntegerField()
    reportante_nombre = serializers.CharField(source='reportante.nombre_completo')
    estado_actual = serializers.CharField()
    registrada_en = serializers.DateTimeField()
    total_evidencias = serializers.SerializerMethodField()
    orientacion_tipo = serializers.SerializerMethodField()
    orientacion_resultado = serializers.SerializerMethodField()
    tarea_operativa_estado = serializers.SerializerMethodField()
    tarea_estrategica_estado = serializers.SerializerMethodField()
    analista_nombre = serializers.SerializerMethodField()

    def _tasks(self, obj) -> dict:
        cache = self.context.setdefault('_tasks_cache', {})
        if obj.pk not in cache:
            cache[obj.pk] = _tasks_by_branch(obj)
        return cache[obj.pk]

    def get_referencia(self, obj) -> str:
        return f'INC-{obj.id:04d}'

    def get_activo_nombre(self, obj) -> str | None:
        return obj.activo_reportado.nombre if obj.activo_reportado else obj.activo_texto

    def get_total_evidencias(self, obj) -> int:
        return len(obj.evidencias.all())

    def get_orientacion_tipo(self, obj) -> str | None:
        orientacion = _orientation_of(self._tasks(obj).get(RAMA_OPERATIVA))
        return orientacion.tipo if orientacion else None

    def get_orientacion_resultado(self, obj) -> str | None:
        respuesta = _response_of(_orientation_of(self._tasks(obj).get(RAMA_OPERATIVA)))
        return respuesta.resultado if respuesta else None

    def get_tarea_operativa_estado(self, obj) -> str | None:
        tarea = self._tasks(obj).get(RAMA_OPERATIVA)
        return tarea.estado if tarea else None

    def get_tarea_estrategica_estado(self, obj) -> str | None:
        tarea = self._tasks(obj).get(RAMA_ESTRATEGICA)
        return tarea.estado if tarea else None

    def get_analista_nombre(self, obj) -> str | None:
        atencion = getattr(obj, 'atencion', None)
        return atencion.analista.nombre_completo if atencion else None


class IncidentListDetailOutputSerializer(IncidentListOutputSerializer):
    """Detalle completo: evidencias, historial de estados, atención N2, tareas IA y riesgos vinculados."""

    evidencias = EvidenciaOutputSerializer(many=True)
    historial = serializers.SerializerMethodField()
    atencion = serializers.SerializerMethodField()
    tareas_ia = serializers.SerializerMethodField()
    riesgos_vinculados = serializers.SerializerMethodField()

    def get_historial(self, obj) -> list[dict]:
        return HistorialEstadoOutputSerializer(obj.historial_estados.all(), many=True).data

    def get_atencion(self, obj) -> dict | None:
        atencion = getattr(obj, 'atencion', None)
        return AtencionIncidenciaOutputSerializer(atencion).data if atencion else None

    def get_tareas_ia(self, obj) -> dict:
        tareas = self._tasks(obj)
        return {
            'operativa': TareaIAResumenOutputSerializer(tareas[RAMA_OPERATIVA]).data if RAMA_OPERATIVA in tareas else None,
            'estrategica': TareaIAResumenOutputSerializer(tareas[RAMA_ESTRATEGICA]).data if RAMA_ESTRATEGICA in tareas else None,
        }

    def get_riesgos_vinculados(self, obj) -> list[dict]:
        tarea = self._tasks(obj).get(RAMA_ESTRATEGICA)
        analisis = getattr(tarea, 'analisis_estrategico', None) if tarea else None
        if analisis is None:
            return []
        return [
            {
                'riesgo_id': vinculo.version.riesgo_id,
                'riesgo_codigo': vinculo.version.riesgo.codigo,
                'version_id': vinculo.version_id,
                'version_numero': vinculo.version.numero,
                'estado_vinculo': vinculo.estado,
            }
            for vinculo in analisis.versiones_vinculadas.select_related('version__riesgo')
        ]


# ---------------------------------------------------------------------------
# Orientación operativa
# ---------------------------------------------------------------------------
class PasoOrientacionOutputSerializer(serializers.Serializer):
    orden = serializers.IntegerField()
    instruccion = serializers.CharField()


class CitaOrientacionOutputSerializer(serializers.Serializer):
    numero = serializers.IntegerField()
    fragmento_id = serializers.IntegerField()
    documento_codigo = serializers.CharField(source='fragmento.version_documento.documento.codigo')
    documento_titulo = serializers.CharField(source='fragmento.version_documento.documento.titulo')
    version = serializers.CharField(source='fragmento.version_documento.version')
    pagina_inicio = serializers.IntegerField(source='fragmento.pagina_inicio', allow_null=True)
    pagina_fin = serializers.IntegerField(source='fragmento.pagina_fin', allow_null=True)
    contenido = serializers.CharField(source='fragmento.contenido')


class RespuestaOrientacionOutputSerializer(serializers.Serializer):
    resultado = serializers.CharField()
    respondida_en = serializers.DateTimeField()


class OrientacionOutputSerializer(serializers.Serializer):
    tipo = serializers.CharField(allow_null=True)
    resumen = serializers.CharField(allow_null=True)
    advertencia = serializers.CharField(allow_null=True)
    creada_en = serializers.DateTimeField()
    pasos = PasoOrientacionOutputSerializer(many=True)
    citas = CitaOrientacionOutputSerializer(many=True)
    respuesta = serializers.SerializerMethodField()

    def get_respuesta(self, obj) -> dict | None:
        respuesta = _response_of(obj)
        return RespuestaOrientacionOutputSerializer(respuesta).data if respuesta else None


class OperationalGuidanceOutputSerializer(serializers.Serializer):
    """Entrada: dict {'incidencia', 'estado', 'tarea', 'orientacion'} construido por la vista."""

    incidencia_id = serializers.IntegerField(source='incidencia.id')
    estado_incidencia = serializers.CharField(source='estado')
    tarea_ia = serializers.SerializerMethodField()
    orientacion = serializers.SerializerMethodField()

    def get_tarea_ia(self, obj) -> dict | None:
        tarea = obj['tarea']
        if tarea is None:
            return None
        return {'id': tarea.id, 'estado': tarea.estado, 'error_codigo': tarea.error_codigo, 'error_detalle': tarea.error_detalle}

    def get_orientacion(self, obj) -> dict | None:
        return OrientacionOutputSerializer(obj['orientacion']).data if obj['orientacion'] else None
