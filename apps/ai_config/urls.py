from django.urls import path

from apps.ai_config.views import AIConfigTestConnectionView, AIConfigView

urlpatterns = [
    path('admin/ai-config/', AIConfigView.as_view(), name='admin-ai-config'),
    path('admin/ai-config/test-connection/', AIConfigTestConnectionView.as_view(), name='admin-ai-config-test'),
]
