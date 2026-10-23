from rest_framework.routers import SimpleRouter

from apps.incidents.views import IncidentViewSet

router = SimpleRouter(trailing_slash=True)
router.register('incidents', IncidentViewSet, basename='incident')

urlpatterns = router.urls
