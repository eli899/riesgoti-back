from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasRiesgoTIPermission, user_has_permission
from apps.accounts.rbac import CodigoPermiso
from apps.assets_matrix.models import Activo, TipoActivo
from apps.assets_matrix.serializers import (
    ActivoInputSerializer,
    ActivoOutputSerializer,
    MatrizActivaOutputSerializer,
    PublishMatrixInputSerializer,
    TipoActivoOutputSerializer,
)
from apps.assets_matrix.services import MatrixService
from apps.audit.constants import AccionAuditoria
from apps.audit.mixins import AuditLogMixin
from config.constants import OpenApiTag

ASSET_ADMIN_PERMISSION = CodigoPermiso.ACTIVO_ADMINISTRAR


# ---------------------------------------------------------------------------
# Catálogo de activos
# ---------------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(tags=[OpenApiTag.CATALOGO_ACTIVOS], responses=ActivoOutputSerializer(many=True)),
    retrieve=extend_schema(tags=[OpenApiTag.CATALOGO_ACTIVOS], responses=ActivoOutputSerializer),
    create=extend_schema(tags=[OpenApiTag.CATALOGO_ACTIVOS], request=ActivoInputSerializer, responses={201: ActivoOutputSerializer}),
    partial_update=extend_schema(tags=[OpenApiTag.CATALOGO_ACTIVOS], request=ActivoInputSerializer, responses=ActivoOutputSerializer),
)
class ActivoViewSet(
    AuditLogMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    Lectura para cualquier usuario autenticado (los reportantes eligen el activo afectado; solo ven activos vigentes).
    Alta y edición exigen `activo.administrar`. No existe DELETE: desactivar preserva las referencias históricas.
    """

    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    permission_classes = [HasRiesgoTIPermission]
    permission_map = {'create': ASSET_ADMIN_PERMISSION, 'partial_update': ASSET_ADMIN_PERMISSION}
    serializer_class = ActivoOutputSerializer
    filterset_fields = ['activo', 'tipo_id', 'criticidad']
    search_fields = ['codigo', 'nombre', 'descripcion']
    ordering_fields = ['codigo', 'nombre', 'criticidad', 'creado_en']
    ordering = ['codigo']
    audit_actions = {'create': AccionAuditoria.CREAR_ACTIVO, 'update': AccionAuditoria.ACTUALIZAR_ACTIVO}

    def get_queryset(self):
        qs = Activo.objects.select_related('tipo').all()
        if not user_has_permission(self.request.user, ASSET_ADMIN_PERMISSION):
            qs = qs.filter(activo=True)
        return qs

    def get_audit_targets(self, instance) -> dict:
        return {'activo': instance}

    def get_audit_detail(self, instance, action: str) -> str:
        return f'codigo={instance.codigo} activo={instance.activo} criticidad={instance.criticidad}'

    def resolve_audit_action(self, instance, action: str) -> str | None:
        previo = getattr(self, '_activo_previo', None)
        if action == 'update' and previo is not None and previo != instance.activo:
            return AccionAuditoria.ACTIVAR_ACTIVO if instance.activo else AccionAuditoria.DESACTIVAR_ACTIVO
        return super().resolve_audit_action(instance, action)

    def create(self, request):
        dto = ActivoInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        self.perform_create(dto)
        return Response(ActivoOutputSerializer(dto.instance).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        instance = self.get_object()
        self._activo_previo = instance.activo
        dto = ActivoInputSerializer(instance, data=request.data, partial=True)
        dto.is_valid(raise_exception=True)
        self.perform_update(dto)
        return Response(ActivoOutputSerializer(dto.instance).data)


@extend_schema_view(list=extend_schema(tags=[OpenApiTag.CATALOGO_ACTIVOS], summary='Tipos de activo vigentes'))
class TipoActivoViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = TipoActivoOutputSerializer
    pagination_class = None
    ordering = ['nombre']

    def get_queryset(self):
        return TipoActivo.objects.filter(activo=True)


# ---------------------------------------------------------------------------
# Matriz de riesgo 5x5
# ---------------------------------------------------------------------------
class ActiveMatrixView(APIView):
    @extend_schema(responses={200: MatrizActivaOutputSerializer}, tags=[OpenApiTag.MATRIZ_RIESGO], summary='Matriz 5x5 activa')
    def get(self, request):
        return Response(MatrizActivaOutputSerializer(MatrixService.get_active()).data)


class PublishMatrixView(APIView):
    permission_classes = [HasRiesgoTIPermission]
    required_permission = CodigoPermiso.MATRIZ_ADMINISTRAR

    @extend_schema(
        request=PublishMatrixInputSerializer,
        responses={201: MatrizActivaOutputSerializer},
        tags=[OpenApiTag.MATRIZ_RIESGO],
        summary='Publica una nueva versión inmutable de la matriz 5x5',
    )
    def post(self, request):
        dto = PublishMatrixInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        matriz = MatrixService.publish(request.user, dto.validated_data)
        return Response(MatrizActivaOutputSerializer(matriz).data, status=status.HTTP_201_CREATED)
