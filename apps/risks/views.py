import django_filters
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasRiesgoTIPermission
from apps.risks.models import VersionRiesgo
from apps.risks.serializers import (
    ConfirmGroupingInputSerializer,
    EvaluacionRiesgoOutputSerializer,
    RemoveIncidentFromGroupInputSerializer,
    RestoreIncidentToGroupInputSerializer,
    RiskDashboardOutputSerializer,
    RiskDecisionInputSerializer,
    RiskEvaluateInputSerializer,
    RiskVersionListDetailOutputSerializer,
)
from apps.risks.services import (
    ESTADO_PENDIENTE,
    RiskDashboardAggregationService,
    RiskGovernanceDecisionService,
    risk_version_queryset,
)

TAG = 'Gobierno de Riesgos'
# Solo riesgo.consultar: HasRiesgoTIPermission niega al ADMIN cualquier conjunto que incluya un permiso SoD.
READ_PERMISSIONS = 'riesgo.consultar'
BANDEJAS = [
    ('nuevas', 'Pendientes sin agrupación confirmada'),
    ('pendientes_revision', 'Pendientes con agrupación confirmada'),
    ('rechazadas', 'Versiones rechazadas'),
    ('decididas', 'Versiones con decisión registrada'),
]


class RiskVersionFilter(django_filters.FilterSet):
    estado = django_filters.BaseInFilter(field_name='estado', lookup_expr='in')
    riesgo_id = django_filters.NumberFilter(field_name='riesgo_id')
    origen = django_filters.CharFilter(field_name='origen', lookup_expr='iexact')
    bandeja = django_filters.ChoiceFilter(choices=BANDEJAS, method='filter_bandeja')
    q = django_filters.CharFilter(method='filter_q', label='Código RSG, título o amenaza')

    class Meta:
        model = VersionRiesgo
        fields = ['estado', 'riesgo_id', 'origen']

    def filter_bandeja(self, queryset, name, value):
        if value == 'nuevas':
            return queryset.filter(estado=ESTADO_PENDIENTE, agrupacion_confirmada_por__isnull=True)
        if value == 'pendientes_revision':
            return queryset.filter(estado=ESTADO_PENDIENTE, agrupacion_confirmada_por__isnull=False)
        if value == 'rechazadas':
            return queryset.filter(estado='RECHAZADA')
        return queryset.exclude(estado=ESTADO_PENDIENTE)

    def filter_q(self, queryset, name, value):
        return queryset.filter(Q(riesgo__codigo__icontains=value) | Q(titulo__icontains=value) | Q(amenaza__icontains=value))


@extend_schema_view(
    list=extend_schema(tags=[TAG], summary='Versiones de riesgo (bandejas de propuestas, historial y comparador)'),
    retrieve=extend_schema(tags=[TAG], summary='Detalle de una versión de riesgo'),
)
class RiskVersionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """
    Lectura con riesgo.consultar (ADMIN en modo solo lectura). Las mutaciones exigen permisos de evaluación y
    decisión que HasRiesgoTIPermission niega siempre al rol ADMIN (INV-05, HTTP 403).
    """

    permission_classes = [HasRiesgoTIPermission]
    permission_map = {
        'list': READ_PERMISSIONS,
        'retrieve': READ_PERMISSIONS,
        'remove_incident': 'riesgo.revisar_agrupacion',
        'restore_incident': 'riesgo.revisar_agrupacion',
        'confirm_grouping': 'riesgo.revisar_agrupacion',
        'evaluate': 'riesgo.evaluar',
        'decision': 'riesgo.validar',
    }
    serializer_class = RiskVersionListDetailOutputSerializer
    pagination_class = None
    filterset_class = RiskVersionFilter
    ordering_fields = ['creada_en', 'numero', 'id']
    ordering = ['-creada_en', '-id']

    def get_queryset(self):
        return risk_version_queryset()

    def _render(self, version_id: int, status_code=status.HTTP_200_OK) -> Response:
        return Response(RiskVersionListDetailOutputSerializer(risk_version_queryset().get(pk=version_id)).data, status=status_code)

    @extend_schema(
        tags=[TAG], request=RemoveIncidentFromGroupInputSerializer, responses={200: RiskVersionListDetailOutputSerializer},
        parameters=[OpenApiParameter('analisis_id', int, OpenApiParameter.PATH)],
        summary='Retira un falso positivo de la agrupación (la fila se conserva como RETIRADA)',
    )
    @action(detail=True, methods=['patch'], url_path=r'incidents/(?P<analisis_id>\d+)/remove')
    def remove_incident(self, request, pk=None, analisis_id=None):
        dto = RemoveIncidentFromGroupInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        version = RiskGovernanceDecisionService.remove_incident(
            version=self.get_object(), analisis_id=int(analisis_id), actor=request.user, **dto.validated_data,
        )
        return self._render(version.id)

    @extend_schema(
        tags=[TAG], request=RestoreIncidentToGroupInputSerializer, responses={200: RiskVersionListDetailOutputSerializer},
        parameters=[OpenApiParameter('analisis_id', int, OpenApiParameter.PATH)],
        summary='Restaura una incidencia retirada a la agrupación',
    )
    @action(detail=True, methods=['patch'], url_path=r'incidents/(?P<analisis_id>\d+)/restore')
    def restore_incident(self, request, pk=None, analisis_id=None):
        dto = RestoreIncidentToGroupInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        version = RiskGovernanceDecisionService.restore_incident(
            version=self.get_object(), analisis_id=int(analisis_id), actor=request.user, **dto.validated_data,
        )
        return self._render(version.id)

    @extend_schema(
        tags=[TAG], request=ConfirmGroupingInputSerializer, responses={200: RiskVersionListDetailOutputSerializer},
        summary='Confirma el activo afectado y la agrupación de incidencias',
    )
    @action(detail=True, methods=['post'], url_path='confirm-grouping')
    def confirm_grouping(self, request, pk=None):
        dto = ConfirmGroupingInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        version = RiskGovernanceDecisionService.confirm_grouping(version=self.get_object(), actor=request.user, **dto.validated_data)
        return self._render(version.id)

    @extend_schema(
        tags=[TAG], request=RiskEvaluateInputSerializer, responses={200: EvaluacionRiesgoOutputSerializer},
        summary='Evalúa la versión en la matriz 5x5 activa (celda_id histórico inmutable)',
    )
    @action(detail=True, methods=['post'])
    def evaluate(self, request, pk=None):
        dto = RiskEvaluateInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        evaluacion = RiskGovernanceDecisionService.evaluate(version=self.get_object(), actor=request.user, **dto.validated_data)
        return Response(EvaluacionRiesgoOutputSerializer(evaluacion).data)

    @extend_schema(
        tags=[TAG], request=RiskDecisionInputSerializer, responses={200: RiskVersionListDetailOutputSerializer},
        summary='Emite la decisión ISO/IEC 27005 (VALIDADA, CORREGIDA crea v n+1, RECHAZADA)',
    )
    @action(detail=True, methods=['post'])
    def decision(self, request, pk=None):
        dto = RiskDecisionInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        version = self.get_object()
        _, nueva = RiskGovernanceDecisionService.decide(version=version, actor=request.user, data=dto.validated_data)
        # CORREGIDA devuelve la nueva versión del analista para continuar su evaluación y validación.
        return self._render(nueva.id if nueva else version.id, status.HTTP_201_CREATED if nueva else status.HTTP_200_OK)


class RiskDashboardAPIView(APIView):
    permission_classes = [HasRiesgoTIPermission]
    required_permission = 'riesgo.consultar'

    @extend_schema(tags=[TAG], responses={200: RiskDashboardOutputSerializer},
                   summary='Indicadores de riesgos vigentes (última versión VALIDADA por RIESGO) e incidencias')
    def get(self, request):
        return Response(RiskDashboardOutputSerializer(RiskDashboardAggregationService.build()).data)
