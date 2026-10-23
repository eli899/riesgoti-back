from django.urls import path
from rest_framework.routers import SimpleRouter

from apps.accounts.views import LoginView, MeView, PermissionViewSet, RefreshView, RoleViewSet, UserViewSet

router = SimpleRouter(trailing_slash=True)
router.register('admin/users', UserViewSet, basename='admin-user')
router.register('admin/roles', RoleViewSet, basename='admin-role')
router.register('admin/permissions', PermissionViewSet, basename='admin-permission')

urlpatterns = [
    path('auth/login/', LoginView.as_view(), name='auth-login'),
    path('auth/refresh/', RefreshView.as_view(), name='auth-refresh'),
    path('auth/me/', MeView.as_view(), name='auth-me'),
    *router.urls,
]
