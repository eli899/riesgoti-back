from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from .views import HealthcheckView

api_v1_patterns = [
    path('health/', HealthcheckView.as_view(), name='health'),
    path('', include('apps.accounts.urls')),
    path('', include('apps.ai_config.urls')),
    path('', include('apps.assets_matrix.urls')),
    path('', include('apps.documents_rag.urls')),
    path('', include('apps.incidents.urls')),
    path('', include('apps.risks.urls')),
    path('', include('apps.audit.urls')),
]

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/', include(api_v1_patterns)),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]
