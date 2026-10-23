import re
from datetime import timedelta

import django_filters
from django.db.models import Prefetch, Q
from django.http import FileResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.filters import OrderingFilter
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.permissions import HasRiesgoTIPermission, user_has_permission
from apps.incidents.models import HistorialEstadoIncidencia, Incidencia
from apps.incidents.serializers import (
    AtencionIncidenciaOutputSerializer,
    HumanAttentionInputSerializer,
    IncidentCreateInputSerializer,
    IncidentListDetailOutputSerializer,
    IncidentListOutputSerializer,
    OperationalGuidanceOutputSerializer,
    OrientationFeedbackInputSerializer,
)
from apps.incidents.services import (
    EN_ATENCION,
    PENDIENTE_ATENCION_HUMANA,
    RAMA_OPERATIVA,
    IncidentService,
    current_status_subquery,
    evidence_absolute_path,
    latest_task,
)
from apps.risks.models import CitaOrientacion, OrientacionOperativa, TareaIA
from apps.risks.serializers import RetryStrategicAnalysisOutputSerializer
from apps.risks.services import StrategicRetryService

TAG = 'Incidencias'
VIEW_PERMISSIONS = ('incidencia.ver_propias', 'incidencia.ver_todas')
ATTENTION_PERMISSION = 'atencion.atender'
REFERENCE_RE = re.compile(r'^\s*INC-?0*(\d+)\s*$', re.IGNORECASE)


class IncidentFilter(django_filters.FilterSet):
    estado = django_filters.BaseInFilter(field_name='estado_actual', lookup_expr='in')
    activo_reportado_id = django_filters.NumberFilter(field_name='activo_reportado_id')
    dias = django_filters.NumberFilter(method='filter_dias', label='Antigüedad máxima en días')
    q = django_filters.CharFilter(method='filter_q', label='Referencia INC-0001, título o descripción')
    bandeja = django_filters.ChoiceFilter(choices=[('atencion', 'Cola de atención humana N2')], method='filter_bandeja')

    reportante_id = django_filters.NumberFilter(field_name='reportante_id')

    class Meta:
        model = Incidencia
        fields = ['estado', 'activo_reportado_id', 'reportante_id']

    def filter_dias(self, queryset, name, value):
        return queryset.filter(registrada_en__gte=timezone.now() - timedelta(days=int(value)))

    def filter_q(self, queryset, name, value):
        match = REFERENCE_RE.match(value)
        if match:
            return queryset.filter(pk=int(match.group(1)))
        return queryset.filter(Q(titulo__icontains=value) | Q(descripcion__icontains=value))

    def filter_bandeja(self, queryset, name, value):
        if not user_has_permission(self.request.user, 'atencion.ver_cola'):
            raise PermissionDenied('Se requiere el permiso atencion.ver_cola para consultar la cola N2.')
        return queryset.filter(estado_actual__in=[PENDIENTE_ATENCION_HUMANA, EN_ATENCION])


class IncidentOrderingFilter(OrderingFilter):
    def get_default_ordering(self, view):
        # La cola N2 prioriza los casos más antiguos; el resto de bandejas muestra primero los recientes.
        if view.request.query_params.get('bandeja') == 'atencion':
            return ['registrada_en', 'id']
        return super().get_default_ordering(view)


@extend_schema_view(
    list=extend_schema(tags=[TAG], summary='Incidencias visibles para el usuario (propias o todas según permisos)'),
    retrieve=extend_schema(tags=[TAG], responses=IncidentListDetailOutputSerializer),
)
class IncidentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [HasRiesgoTIPermission]
    permission_map = {
        'list': VIEW_PERMISSIONS,
        'retrieve': VIEW_PERMISSIONS,
        'create': 'incidencia.crear',
        'operational_guidance': VIEW_PERMISSIONS,
        'download_evidence': VIEW_PERMISSIONS,
        'orientation_feedback': 'incidencia.cerrar_propias_por_feedback',
        'start_attention': ATTENTION_PERMISSION,
        'attention': ATTENTION_PERMISSION,
        'retry_strategic': ATTENTION_PERMISSION,
    }
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    serializer_class = IncidentListOutputSerializer
    pagination_class = None
    filterset_class = IncidentFilter
    filter_backends = [django_filters.rest_framework.DjangoFilterBackend, IncidentOrderingFilter]
    ordering_fields = ['registrada_en', 'id']
    ordering = ['-registrada_en', '-id']

    def _base_queryset(self):
        qs = (
            Incidencia.objects.select_related('reportante', 'activo_reportado', 'atencion__analista')
            .annotate(estado_actual=current_status_subquery())
            .prefetch_related(
                'evidencias',
                Prefetch('tareas_ia', queryset=TareaIA.objects.select_related(
                    'orientacion_operativa__respuesta', 'analisis_estrategico',
                )),
            )
        )
        if getattr(self, 'swagger_fake_view', False):  # Generación del esquema OpenAPI sin usuario.
            return qs.none()
        if not user_has_permission(self.request.user, 'incidencia.ver_todas'):
            qs = qs.filter(reportante=self.request.user)  # Sin ver_todas solo se ven las incidencias propias.
        return qs

    def _with_history(self, qs):
        return qs.prefetch_related(
            Prefetch('historial_estados', queryset=HistorialEstadoIncidencia.objects.select_related('actor').order_by('ocurrido_en', 'id')),
        )

    def get_queryset(self):
        qs = self._base_queryset()
        return self._with_history(qs) if self.action == 'retrieve' else qs

    def get_serializer_class(self):
        return IncidentListDetailOutputSerializer if self.action == 'retrieve' else IncidentListOutputSerializer

    def _detail(self, incidencia_id: int, status_code=status.HTTP_200_OK) -> Response:
        incidencia = self._with_history(self._base_queryset()).get(pk=incidencia_id)
        return Response(IncidentListDetailOutputSerializer(incidencia).data, status=status_code)

    @extend_schema(
        tags=[TAG],
        request={'multipart/form-data': IncidentCreateInputSerializer, 'application/json': IncidentCreateInputSerializer},
        responses={201: IncidentListDetailOutputSerializer},
        summary='Registra una incidencia (transaccional, previo a cualquier llamada de IA)',
    )
    def create(self, request):
        dto = IncidentCreateInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        data = dto.validated_data
        incidencia, _, _ = IncidentService.create_incident_transactional(
            reportante=request.user,
            titulo=data['titulo'],
            descripcion=data['descripcion'],
            activo_reportado=data.get('activo_reportado'),
            activo_texto=data.get('activo_texto'),
            archivos_evidencia=data.get('evidencias', []),
        )
        return self._detail(incidencia.id, status.HTTP_201_CREATED)

    @extend_schema(tags=[TAG], responses={200: OperationalGuidanceOutputSerializer}, summary='Estado y orientación operativa RAG')
    @action(detail=True, methods=['get'], url_path='operational-guidance')
    def operational_guidance(self, request, pk=None):
        incidencia = self.get_object()
        tarea = latest_task(incidencia, RAMA_OPERATIVA)
        orientacion = None
        if tarea is not None:
            orientacion = (
                OrientacionOperativa.objects.filter(tarea=tarea)
                .select_related('respuesta')
                .prefetch_related(
                    'pasos',
                    Prefetch('citas', queryset=CitaOrientacion.objects.select_related(
                        'fragmento__version_documento__documento',
                    )),
                )
                .first()
            )
        payload = {
            'incidencia': incidencia, 'estado': IncidentService.get_current_status(incidencia),
            'tarea': tarea, 'orientacion': orientacion,
        }
        return Response(OperationalGuidanceOutputSerializer(payload).data)

    @extend_schema(
        tags=[TAG], request=OrientationFeedbackInputSerializer, responses={200: IncidentListDetailOutputSerializer},
        summary='Confirmación del reportante: FUNCIONO cierra la incidencia; NO_FUNCIONO la escala a N2',
    )
    @action(detail=True, methods=['post'], url_path='orientation-feedback')
    def orientation_feedback(self, request, pk=None):
        dto = OrientationFeedbackInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        incidencia = self.get_object()
        IncidentService.register_orientation_feedback(incidencia=incidencia, actor=request.user, **dto.validated_data)
        return self._detail(incidencia.id)

    @extend_schema(tags=[TAG], request=None, responses={200: IncidentListDetailOutputSerializer}, summary='Inicia la atención humana N2')
    @action(detail=True, methods=['post'], url_path='start-attention')
    def start_attention(self, request, pk=None):
        incidencia = self.get_object()
        IncidentService.start_attention(incidencia=incidencia, analista=request.user)
        return self._detail(incidencia.id)

    @extend_schema(
        tags=[TAG], request=HumanAttentionInputSerializer, responses={200: AtencionIncidenciaOutputSerializer},
        summary='Guarda el avance o cierra la atención N2 (las notas nunca se indexan en FAISS)',
    )
    @action(detail=True, methods=['patch'], url_path='attention')
    def attention(self, request, pk=None):
        dto = HumanAttentionInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        incidencia = self.get_object()
        IncidentService.update_attention(incidencia=incidencia, analista=request.user, data=dto.validated_data)
        return self._detail(incidencia.id)

    @extend_schema(
        tags=[TAG], request=None, responses={202: RetryStrategicAnalysisOutputSerializer},
        summary='Reintenta el análisis estratégico cuando la última TAREA_IA estratégica terminó en ERROR',
    )
    @action(detail=True, methods=['post'], url_path='retry-strategic')
    def retry_strategic(self, request, pk=None):
        incidencia = self.get_object()
        tarea = StrategicRetryService.retry(incidencia, request.user)
        payload = {'incidencia_id': incidencia.id, 'tarea_ia': tarea}
        return Response(RetryStrategicAnalysisOutputSerializer(payload).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        tags=[TAG], responses={(200, 'application/octet-stream'): bytes},
        parameters=[OpenApiParameter('evidencia_id', int, OpenApiParameter.PATH)],
        summary='Descarga una evidencia adjunta',
    )
    @action(detail=True, methods=['get'], url_path=r'evidences/(?P<evidencia_id>\d+)/download')
    def download_evidence(self, request, pk=None, evidencia_id=None):
        incidencia = self.get_object()
        evidencia = incidencia.evidencias.filter(pk=evidencia_id).first()
        if evidencia is None:
            raise NotFound('Evidencia no encontrada.')
        path = evidence_absolute_path(evidencia.clave_archivo)
        if not path.exists():
            raise NotFound('El archivo de la evidencia no está disponible en el almacenamiento.')
        return FileResponse(
            open(path, 'rb'), as_attachment=True, filename=evidencia.nombre_original, content_type=evidencia.tipo_mime,
        )

