from django.db.models import Count, Prefetch
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.permissions import HasRiesgoTIPermission
from apps.accounts.rbac import CodigoPermiso
from apps.documents_rag.embeddings import resolve_embedding_settings
from apps.documents_rag.models import FragmentoDocumento, VersionDocumento
from apps.documents_rag.serializers import (
    DocumentPreviewOutputSerializer,
    DocumentUploadInputSerializer,
    VersionDocumentoOutputSerializer,
)
from apps.documents_rag.services import DocumentIngestionService, get_active_ai_config
from config.constants import OpenApiTag


@extend_schema_view(
    list=extend_schema(tags=[OpenApiTag.BASE_DOCUMENTAL], summary='Versiones documentales y su estado de procesamiento'),
    retrieve=extend_schema(tags=[OpenApiTag.BASE_DOCUMENTAL]),
)
class DocumentVersionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [HasRiesgoTIPermission]
    required_permission = CodigoPermiso.DOCUMENTO_ADMINISTRAR
    serializer_class = VersionDocumentoOutputSerializer
    pagination_class = None
    filterset_fields = ['procesamiento', 'activa', 'finalidad', 'documento_id']
    search_fields = ['documento__codigo', 'documento__titulo', 'version']
    ordering_fields = ['cargada_en', 'id']
    ordering = ['-cargada_en', '-id']

    def get_queryset(self):
        return VersionDocumento.objects.select_related('documento', 'cargada_por', 'autorizada_por').annotate(
            total_fragmentos=Count('fragmentos'),
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['modelo_embedding_actual'] = resolve_embedding_settings(get_active_ai_config())[1]
        return context

    def _render(self, version, status_code=status.HTTP_200_OK):
        fresh = self.get_queryset().get(pk=version.pk)
        return Response(VersionDocumentoOutputSerializer(fresh, context=self.get_serializer_context()).data, status=status_code)

    @extend_schema(
        tags=[OpenApiTag.BASE_DOCUMENTAL], request={'multipart/form-data': DocumentUploadInputSerializer},
        responses={201: VersionDocumentoOutputSerializer}, summary='Carga un PDF como nueva versión y lo encola para su procesamiento',
    )
    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def upload(self, request):
        dto = DocumentUploadInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        version = DocumentIngestionService.upload(request.user, dto.validated_data)
        return self._render(version, status.HTTP_201_CREATED)

    @extend_schema(tags=[OpenApiTag.BASE_DOCUMENTAL], responses={200: DocumentPreviewOutputSerializer}, summary='Previsualización de fragmentos Markdown')
    @action(detail=True, methods=['get'])
    def preview(self, request, pk=None):
        version = (
            VersionDocumento.objects.select_related('documento')
            .prefetch_related(Prefetch('fragmentos', queryset=FragmentoDocumento.objects.order_by('orden')))
            .get(pk=self.get_object().pk)
        )
        return Response(DocumentPreviewOutputSerializer(version).data)

    @extend_schema(tags=[OpenApiTag.BASE_DOCUMENTAL], request=None, responses={200: VersionDocumentoOutputSerializer}, summary='Autoriza y activa la versión')
    @action(detail=True, methods=['post'])
    def authorize(self, request, pk=None):
        return self._render(DocumentIngestionService.authorize(request.user, self.get_object()))

    @extend_schema(tags=[OpenApiTag.BASE_DOCUMENTAL], request=None, responses={200: VersionDocumentoOutputSerializer}, summary='Reactiva una versión autorizada')
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        return self._render(DocumentIngestionService.activate(request.user, self.get_object()))

    @extend_schema(
        tags=[OpenApiTag.BASE_DOCUMENTAL], request=None, responses={200: VersionDocumentoOutputSerializer},
        summary='Desactiva la versión para nuevas consultas RAG (fragmentos y citas preservados)',
    )
    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        return self._render(DocumentIngestionService.deactivate(request.user, self.get_object()))

    @extend_schema(tags=[OpenApiTag.BASE_DOCUMENTAL], request=None, responses={202: VersionDocumentoOutputSerializer}, summary='Re-procesa una versión en ERROR')
    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        return self._render(DocumentIngestionService.retry(request.user, self.get_object()), status.HTTP_202_ACCEPTED)

    @extend_schema(
        tags=[OpenApiTag.BASE_DOCUMENTAL], request=None, responses={202: VersionDocumentoOutputSerializer},
        summary='Re-vectoriza los fragmentos con el modelo de embeddings vigente',
    )
    @action(detail=True, methods=['post'])
    def reindex(self, request, pk=None):
        return self._render(DocumentIngestionService.request_reindex(request.user, self.get_object()), status.HTTP_202_ACCEPTED)
