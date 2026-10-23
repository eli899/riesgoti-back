from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.assets_matrix.views import ActiveMatrixView, ActivoViewSet, PublishMatrixView, TipoActivoViewSet

router = SimpleRouter(trailing_slash=True)
router.register('assets', ActivoViewSet, basename='asset')
router.register('asset-types', TipoActivoViewSet, basename='asset-type')

urlpatterns = [
    path('matrices/active/', ActiveMatrixView.as_view(), name='matrix-active'),
    path('admin/matrices/publish/', PublishMatrixView.as_view(), name='admin-matrix-publish'),
    *router.urls,
]
