import django_filters
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.pagination import PageNumberPagination

from apps.accounts.permissions import HasRiesgoTIPermission
from apps.accounts.rbac import CodigoPermiso
from apps.audit.models import EventoAuditoria
from apps.audit.serializers import EventoAuditoriaOutputSerializer
from config.constants import OpenApiTag


class AuditEventFilter(django_filters.FilterSet):
    accion = django_filters.CharFilter(field_name='accion', lookup_expr='iexact')
    desde = django_filters.IsoDateTimeFilter(field_name='ocurrido_en', lookup_expr='gte')
    hasta = django_filters.IsoDateTimeFilter(field_name='ocurrido_en', lookup_expr='lte')

    class Meta:
        model = EventoAuditoria
        fields = [
            'accion', 'actor_id', 'incidencia_id', 'version_riesgo_id', 'version_documento_id',
            'matriz_id', 'activo_id', 'usuario_objeto_id', 'rol_id',
        ]


class AuditEventPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200


@extend_schema_view(
    list=extend_schema(tags=[OpenApiTag.AUDITORIA], summary='Bitácora de eventos de auditoría'),
    retrieve=extend_schema(tags=[OpenApiTag.AUDITORIA], summary='Detalle de un evento de auditoría'),
)
class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = EventoAuditoriaOutputSerializer
    permission_classes = [HasRiesgoTIPermission]
    required_permission = CodigoPermiso.USUARIO_ADMINISTRAR
    filterset_class = AuditEventFilter
    search_fields = ['accion', 'detalle']
    ordering_fields = ['ocurrido_en', 'id']
    ordering = ['-ocurrido_en', '-id']
    pagination_class = AuditEventPagination

    def get_queryset(self):
        return EventoAuditoria.objects.select_related('actor').all()
