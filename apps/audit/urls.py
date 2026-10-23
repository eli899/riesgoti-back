from rest_framework.routers import SimpleRouter

from apps.audit.views import AuditEventViewSet

router = SimpleRouter(trailing_slash=True)
router.register('admin/audit-events', AuditEventViewSet, basename='audit-event')

urlpatterns = router.urls
