from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasRiesgoTIPermission
from apps.accounts.rbac import CodigoPermiso
from apps.ai_config.serializers import (
    AIConfigInputSerializer,
    AIConfigOutputSerializer,
    TestConnectionInputSerializer,
    TestConnectionOutputSerializer,
)
from apps.ai_config.services import AIConfigService, AIConnectionTester
from config.constants import OpenApiTag


def _render_config(config) -> dict:
    context = {'versiones_desfasadas': AIConfigService.find_outdated_versions(config.modelo_embedding)}
    return AIConfigOutputSerializer(config, context=context).data


class AIConfigView(APIView):
    permission_classes = [HasRiesgoTIPermission]
    required_permission = CodigoPermiso.DOCUMENTO_ADMINISTRAR

    @extend_schema(responses={200: AIConfigOutputSerializer}, tags=[OpenApiTag.IA_RAG], summary='Configuración IA/RAG activa')
    def get(self, request):
        return Response(_render_config(AIConfigService.get_active()))

    @extend_schema(
        request=AIConfigInputSerializer,
        responses={200: AIConfigOutputSerializer},
        tags=[OpenApiTag.IA_RAG],
        summary='Publica una nueva versión de la configuración IA/RAG',
    )
    def put(self, request):
        dto = AIConfigInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        config = AIConfigService.update(request.user, dto.validated_data)
        return Response(_render_config(config))


class AIConfigTestConnectionView(APIView):
    permission_classes = [HasRiesgoTIPermission]
    required_permission = CodigoPermiso.DOCUMENTO_ADMINISTRAR

    @extend_schema(
        request=TestConnectionInputSerializer,
        responses={200: TestConnectionOutputSerializer},
        tags=[OpenApiTag.IA_RAG],
        summary='Prueba de conectividad y latencia con los proveedores LLM y de embeddings',
    )
    def post(self, request):
        dto = TestConnectionInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        result = AIConnectionTester.run(request.user, dto.validated_data)
        return Response(TestConnectionOutputSerializer(result).data)
