from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.risks.views import RiskDashboardAPIView, RiskVersionViewSet

router = SimpleRouter(trailing_slash=True)
router.register('risk-versions', RiskVersionViewSet, basename='risk-version')

urlpatterns = [
    path('risks/dashboard/', RiskDashboardAPIView.as_view(), name='risk-dashboard'),
    *router.urls,
]
