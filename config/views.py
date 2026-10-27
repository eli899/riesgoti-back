from django.conf import settings
from django.db import DatabaseError, connection
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import HealthcheckOutputSerializer

from config.constants import OpenApiTag

SERVICE_NAME = 'riesgoti-backend'
SERVICE_VERSION = '0.0.0'


class HealthcheckView(APIView):
    """Verifica la conexión a PostgreSQL y la carga de RIESGOTI_MASTER_KEY."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: HealthcheckOutputSerializer, 503: HealthcheckOutputSerializer},
        tags=[OpenApiTag.SISTEMA],
        summary='Estado del servicio backend',
    )
    def get(self, request):
        try:
            connection.ensure_connection()
            database = 'connected'
        except DatabaseError:
            database = 'unavailable'

        master_key_loaded = len(getattr(settings, 'RIESGOTI_MASTER_KEY_BYTES', b'')) == 32
        healthy = database == 'connected' and master_key_loaded

        payload = HealthcheckOutputSerializer({
            'status': 'ok' if healthy else 'degraded',
            'service': SERVICE_NAME,
            'version': SERVICE_VERSION,
            'database': database,
            'master_key_loaded': master_key_loaded,
        }).data
        return Response(
            payload,
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )
