from django.db.models import Count
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
    TipoActivoInputSerializer,
    TipoActivoOutputSerializer,
)
from apps.assets_matrix.services import AssetService, AssetTypeService, MatrixService
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
    destroy=extend_schema(tags=[OpenApiTag.CATALOGO_ACTIVOS], responses={204: None}, summary='Elimina físicamente un activo sin referencias (409 si las tiene)'),
)
class ActivoViewSet(
    AuditLogMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """
    Lectura para cualquier usuario autenticado (los reportantes eligen el activo afectado; solo ven activos vigentes).
    Alta, edición y eliminación física exigen `activo.administrar`; DELETE responde 409 si el activo tiene referencias
    históricas (en ese caso se desactiva).
    """

    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']
    permission_classes = [HasRiesgoTIPermission]
    permission_map = {'create': ASSET_ADMIN_PERMISSION, 'partial_update': ASSET_ADMIN_PERMISSION, 'destroy': ASSET_ADMIN_PERMISSION}
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

    def destroy(self, request, pk=None):
        AssetService.delete(request.user, self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    list=extend_schema(tags=[OpenApiTag.CATALOGO_ACTIVOS], summary='Tipos de activo (vigentes; todos con activo.administrar)'),
    create=extend_schema(tags=[OpenApiTag.CATALOGO_ACTIVOS], request=TipoActivoInputSerializer, responses={201: TipoActivoOutputSerializer}),
    partial_update=extend_schema(tags=[OpenApiTag.CATALOGO_ACTIVOS], request=TipoActivoInputSerializer, responses=TipoActivoOutputSerializer),
    destroy=extend_schema(
        tags=[OpenApiTag.CATALOGO_ACTIVOS], responses={204: None},
        summary='Elimina físicamente un tipo de activo sin activos asignados (409 si los tiene)',
    ),
)
class TipoActivoViewSet(AuditLogMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    Lectura para cualquier usuario autenticado (solo tipos vigentes); con activo.administrar se listan todos y se
    permite crear, editar, activar/desactivar y eliminar (CHG-0039). Un tipo con activos asignados no se elimina.
    """

    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']
    permission_classes = [HasRiesgoTIPermission]
    permission_map = {'create': ASSET_ADMIN_PERMISSION, 'partial_update': ASSET_ADMIN_PERMISSION, 'destroy': ASSET_ADMIN_PERMISSION}
    serializer_class = TipoActivoOutputSerializer
    pagination_class = None
    ordering = ['nombre']
    audit_actions = {'create': AccionAuditoria.CREAR_TIPO_ACTIVO, 'update': AccionAuditoria.ACTUALIZAR_TIPO_ACTIVO}

    def get_queryset(self):
        qs = TipoActivo.objects.annotate(total_activos=Count('activos')).order_by('nombre')
        if not user_has_permission(self.request.user, ASSET_ADMIN_PERMISSION):
            qs = qs.filter(activo=True)
        return qs

    def get_audit_detail(self, instance, action: str) -> str:
        return f'tipo_activo id={instance.pk} nombre={instance.nombre} activo={instance.activo}'

    def resolve_audit_action(self, instance, action: str) -> str | None:
        previo = getattr(self, '_activo_previo', None)
        if action == 'update' and previo is not None and previo != instance.activo:
            return AccionAuditoria.ACTIVAR_TIPO_ACTIVO if instance.activo else AccionAuditoria.DESACTIVAR_TIPO_ACTIVO
        return super().resolve_audit_action(instance, action)

    def _render(self, instance, status_code=status.HTTP_200_OK):
        return Response(TipoActivoOutputSerializer(self.get_queryset().get(pk=instance.pk)).data, status=status_code)

    def create(self, request):
        dto = TipoActivoInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        self.perform_create(dto)
        return self._render(dto.instance, status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        instance = self.get_object()
        self._activo_previo = instance.activo
        dto = TipoActivoInputSerializer(instance, data=request.data, partial=True)
        dto.is_valid(raise_exception=True)
        self.perform_update(dto)
        return self._render(dto.instance)

    def destroy(self, request, pk=None):
        AssetTypeService.delete(request.user, self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)


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
