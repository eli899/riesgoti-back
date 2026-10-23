from rest_framework.routers import SimpleRouter

from apps.documents_rag.views import DocumentVersionViewSet

router = SimpleRouter(trailing_slash=True)
router.register('admin/document-versions', DocumentVersionViewSet, basename='admin-document-version')

urlpatterns = router.urls
