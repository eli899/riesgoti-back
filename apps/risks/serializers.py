from rest_framework import serializers

from apps.assets_matrix.models import Activo

DECISION_ACTIONS = ['VALIDADA', 'CORREGIDA', 'RECHAZADA']
CORRECTABLE_FIELDS = ('titulo', 'descripcion', 'amenaza', 'vulnerabilidad', 'consecuencia', 'recomendacion')


# ---------------------------------------------------------------------------
# Reintento de la rama estratégica (v0.5)
# ---------------------------------------------------------------------------
class RetryStrategicTaskOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    rama = serializers.CharField()
    intento = serializers.IntegerField()
    estado = serializers.CharField()
    clave_idempotencia = serializers.CharField()
    creada_en = serializers.DateTimeField()


class RetryStrategicAnalysisOutputSerializer(serializers.Serializer):
    incidencia_id = serializers.IntegerField()
    tarea_ia = RetryStrategicTaskOutputSerializer()


# ---------------------------------------------------------------------------
# DTOs de entrada de gobierno de riesgos
# ---------------------------------------------------------------------------
class RemoveIncidentFromGroupInputSerializer(serializers.Serializer):
    motivo_retiro = serializers.CharField(min_length=10, trim_whitespace=True)


class RestoreIncidentToGroupInputSerializer(serializers.Serializer):
    observacion = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class ConfirmGroupingInputSerializer(serializers.Serializer):
    activo_confirmado_id = serializers.PrimaryKeyRelatedField(
        source='activo_confirmado', queryset=Activo.objects.filter(activo=True),
        error_messages={'does_not_exist': 'El activo seleccionado no existe o está inactivo.'},
    )
    justificacion_cambio_activo = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class RiskEvaluateInputSerializer(serializers.Serializer):
    probabilidad = serializers.IntegerField(min_value=1, max_value=5)
    impacto = serializers.IntegerField(min_value=1, max_value=5)
    justificacion = serializers.CharField(min_length=15, trim_whitespace=True)


class RiskDecisionInputSerializer(serializers.Serializer):
    """Las precondiciones que dependen del estado de la versión se validan en RiskGovernanceDecisionService."""

    accion = serializers.ChoiceField(choices=DECISION_ACTIONS)
    observacion = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    justificacion_sin_fuentes = serializers.CharField(required=False, allow_blank=True, max_length=4000)
    titulo = serializers.CharField(required=False, allow_blank=True, max_length=255)
    descripcion = serializers.CharField(required=False, allow_blank=True)
    amenaza = serializers.CharField(required=False, allow_blank=True)
    vulnerabilidad = serializers.CharField(required=False, allow_blank=True)
    consecuencia = serializers.CharField(required=False, allow_blank=True)
    recomendacion = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        observacion = (attrs.get('observacion') or '').strip()
        if attrs['accion'] in ('RECHAZADA', 'CORREGIDA') and len(observacion) < 10:
            verbo = 'rechazar' if attrs['accion'] == 'RECHAZADA' else 'corregir'
            raise serializers.ValidationError({
                'observacion': f'Para {verbo} la propuesta debe registrar una observación de al menos 10 caracteres.'
            })
        if attrs['accion'] == 'CORREGIDA' and not any((attrs.get(f) or '').strip() for f in CORRECTABLE_FIELDS):
            raise serializers.ValidationError({'titulo': 'Indique al menos un campo corregido para la nueva versión.'})
        return attrs


# ---------------------------------------------------------------------------
# Mappers de salida
# ---------------------------------------------------------------------------
class CitaVersionRiesgoOutputSerializer(serializers.Serializer):
    numero = serializers.IntegerField()
    fragmento_id = serializers.IntegerField()
    documento_codigo = serializers.CharField(source='fragmento.version_documento.documento.codigo')
    documento_titulo = serializers.CharField(source='fragmento.version_documento.documento.titulo')
    version = serializers.CharField(source='fragmento.version_documento.version')
    documento_activo = serializers.BooleanField(source='fragmento.version_documento.activa')
    pagina_inicio = serializers.IntegerField(source='fragmento.pagina_inicio', allow_null=True)
    pagina_fin = serializers.IntegerField(source='fragmento.pagina_fin', allow_null=True)
    contenido = serializers.CharField(source='fragmento.contenido')


class VersionIncidenciaOutputSerializer(serializers.Serializer):
    analisis_id = serializers.IntegerField()
    incidencia_id = serializers.IntegerField(source='analisis.tarea.incidencia_id')
    referencia = serializers.SerializerMethodField()
    titulo = serializers.CharField(source='analisis.tarea.incidencia.titulo')
    registrada_en = serializers.DateTimeField(source='analisis.tarea.incidencia.registrada_en')
    estado_incidencia = serializers.CharField(allow_null=True)
    activo_nombre = serializers.SerializerMethodField()
    estado = serializers.CharField()
    similitud = serializers.DecimalField(max_digits=5, decimal_places=4, coerce_to_string=False, allow_null=True)
    motivo_similitud = serializers.CharField(allow_null=True)
    extracto_reporte = serializers.CharField(allow_null=True)
    revisada_por_nombre = serializers.SerializerMethodField()
    revisada_en = serializers.DateTimeField(allow_null=True)
    motivo_retiro = serializers.CharField(allow_null=True)

    def get_referencia(self, obj) -> str:
        return f'INC-{obj.analisis.tarea.incidencia_id:04d}'

    def get_activo_nombre(self, obj) -> str | None:
        incidencia = obj.analisis.tarea.incidencia
        return incidencia.activo_reportado.nombre if incidencia.activo_reportado else incidencia.activo_texto

    def get_revisada_por_nombre(self, obj) -> str | None:
        return obj.revisada_por.nombre_completo if obj.revisada_por else None


class EvaluacionRiesgoOutputSerializer(serializers.Serializer):
    version_id = serializers.IntegerField()
    celda_id = serializers.IntegerField()
    probabilidad = serializers.IntegerField(source='celda.probabilidad')
    impacto = serializers.IntegerField(source='celda.impacto')
    nivel_codigo = serializers.CharField(source='celda.nivel.codigo')
    nivel_orden = serializers.IntegerField(source='celda.nivel.orden')
    matriz_id = serializers.IntegerField(source='celda.matriz_id')
    matriz_nombre = serializers.CharField(source='celda.matriz.nombre')
    matriz_version = serializers.CharField(source='celda.matriz.version')
    justificacion = serializers.CharField(allow_null=True)
    evaluador_id = serializers.IntegerField()
    evaluador_nombre = serializers.CharField(source='evaluador.nombre_completo')
    evaluada_en = serializers.DateTimeField()


class DecisionRiesgoOutputSerializer(serializers.Serializer):
    version_id = serializers.IntegerField()
    accion = serializers.CharField()
    analista_id = serializers.IntegerField()
    analista_nombre = serializers.CharField(source='analista.nombre_completo')
    observacion = serializers.CharField(allow_null=True)
    justificacion_sin_fuentes = serializers.CharField(allow_null=True)
    decidida_en = serializers.DateTimeField()


class RiskVersionListDetailOutputSerializer(serializers.Serializer):
    """Mapper de VERSION_RIESGO para fromApiRiskVersionToDomain (bandeja, workspace, historial y comparador)."""

    id = serializers.IntegerField()
    riesgo_id = serializers.IntegerField()
    riesgo_codigo = serializers.CharField(source='riesgo.codigo')
    numero = serializers.IntegerField()
    origen = serializers.CharField(allow_null=True)
    estado = serializers.CharField()
    posible_recurrencia = serializers.BooleanField()
    version_anterior_id = serializers.IntegerField(allow_null=True)
    titulo = serializers.CharField()
    descripcion = serializers.CharField(allow_null=True)
    amenaza = serializers.CharField(allow_null=True)
    vulnerabilidad = serializers.CharField(allow_null=True)
    consecuencia = serializers.CharField(allow_null=True)
    recomendacion = serializers.CharField(allow_null=True)
    origen_recomendacion = serializers.CharField(allow_null=True)
    creada_por_id = serializers.IntegerField()
    creada_por_nombre = serializers.CharField(source='creada_por.nombre_completo')
    creada_en = serializers.DateTimeField()
    activo_identificado = serializers.SerializerMethodField()
    activo_confirmado_id = serializers.IntegerField(allow_null=True)
    activo_confirmado_nombre = serializers.SerializerMethodField()
    activo_confirmado_criticidad = serializers.SerializerMethodField()
    agrupacion_confirmada = serializers.SerializerMethodField()
    agrupacion_confirmada_por_nombre = serializers.SerializerMethodField()
    agrupacion_confirmada_en = serializers.DateTimeField(allow_null=True)
    tiene_citas_estrategicas = serializers.SerializerMethodField()
    citas = CitaVersionRiesgoOutputSerializer(many=True)
    incidencias = serializers.SerializerMethodField()
    total_incidencias_incluidas = serializers.SerializerMethodField()
    evaluacion = serializers.SerializerMethodField()
    decision = serializers.SerializerMethodField()

    def _links(self, obj):
        return list(obj.incidencias_vinculadas.all())

    def get_activo_identificado(self, obj) -> str | None:
        links = self._links(obj)
        return links[0].analisis.activo_identificado if links else None

    def get_activo_confirmado_nombre(self, obj) -> str | None:
        return obj.activo_confirmado.nombre if obj.activo_confirmado else None

    def get_activo_confirmado_criticidad(self, obj) -> int | None:
        return obj.activo_confirmado.criticidad if obj.activo_confirmado else None

    def get_agrupacion_confirmada(self, obj) -> bool:
        return obj.agrupacion_confirmada_por_id is not None

    def get_agrupacion_confirmada_por_nombre(self, obj) -> str | None:
        return obj.agrupacion_confirmada_por.nombre_completo if obj.agrupacion_confirmada_por else None

    def get_tiene_citas_estrategicas(self, obj) -> bool:
        return len(obj.citas.all()) > 0

    def get_incidencias(self, obj) -> list[dict]:
        return VersionIncidenciaOutputSerializer(self._links(obj), many=True).data

    def get_total_incidencias_incluidas(self, obj) -> int:
        return sum(1 for link in self._links(obj) if link.estado != 'RETIRADA')

    def get_evaluacion(self, obj) -> dict | None:
        evaluacion = getattr(obj, 'evaluacion', None)
        return EvaluacionRiesgoOutputSerializer(evaluacion).data if evaluacion else None

    def get_decision(self, obj) -> dict | None:
        decision = getattr(obj, 'decision', None)
        return DecisionRiesgoOutputSerializer(decision).data if decision else None


class NivelConteoOutputSerializer(serializers.Serializer):
    nivel_codigo = serializers.CharField()
    orden = serializers.IntegerField()
    total = serializers.IntegerField()


class RegistroRiesgoOutputSerializer(serializers.Serializer):
    riesgo_id = serializers.IntegerField()
    riesgo_codigo = serializers.CharField()
    version_vigente_id = serializers.IntegerField()
    version_vigente_numero = serializers.IntegerField()
    titulo = serializers.CharField()
    activo_confirmado_id = serializers.IntegerField(allow_null=True)
    activo_confirmado_nombre = serializers.CharField(allow_null=True)
    nivel_codigo = serializers.CharField(allow_null=True)
    probabilidad = serializers.IntegerField(allow_null=True)
    impacto = serializers.IntegerField(allow_null=True)
    validada_en = serializers.DateTimeField()
    total_incidencias = serializers.IntegerField()
    propuesta_pendiente_id = serializers.IntegerField(allow_null=True)
    propuesta_pendiente_numero = serializers.IntegerField(allow_null=True)


class RiskDashboardOutputSerializer(serializers.Serializer):
    generado_en = serializers.DateTimeField()
    total_riesgos = serializers.IntegerField()
    total_riesgos_vigentes = serializers.IntegerField()
    riesgos_vigentes_por_nivel = NivelConteoOutputSerializer(many=True)
    propuestas_pendientes = serializers.IntegerField()
    propuestas_nuevas_agrupaciones = serializers.IntegerField()
    propuestas_pendientes_revision = serializers.IntegerField()
    propuestas_posible_recurrencia = serializers.IntegerField()
    versiones_rechazadas = serializers.IntegerField()
    incidencias_por_estado = serializers.DictField(child=serializers.IntegerField())
    incidencias_por_activo = serializers.ListField(child=serializers.DictField())
    serie_incidencias = serializers.ListField(child=serializers.DictField())
    registro_riesgos = RegistroRiesgoOutputSerializer(many=True)
