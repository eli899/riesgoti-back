from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.models import Permiso, Rol, RolPermiso, Usuario
from apps.accounts.permissions import HasRiesgoTIPermission
from apps.accounts.rbac import CodigoPermiso
from apps.accounts.serializers import (
    LoginInputSerializer,
    LoginOutputSerializer,
    PermisoOutputSerializer,
    RolInputSerializer,
    RolOutputSerializer,
    UsuarioInputSerializer,
    UsuarioOutputSerializer,
    UsuarioSesionOutputSerializer,
)
from apps.accounts.services import AuthService, RoleService, UserService
from config.constants import OpenApiTag


# ---------------------------------------------------------------------------
# Autenticación JWT
# ---------------------------------------------------------------------------
class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'login'

    def get_authenticate_header(self, request):
        # Sin clases de autenticación DRF degradaría AuthenticationFailed a 403; el contrato exige 401.
        return 'Bearer realm="api"'

    @extend_schema(
        request=LoginInputSerializer,
        responses={200: LoginOutputSerializer},
        tags=[OpenApiTag.AUTENTICACION],
        summary='Inicio de sesión con correo y contraseña (JWT)',
    )
    def post(self, request):
        dto = LoginInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        session = AuthService.login(request, **dto.validated_data)
        return Response(LoginOutputSerializer(session).data, status=status.HTTP_200_OK)


@extend_schema(tags=[OpenApiTag.AUTENTICACION], summary='Renovación del token de acceso')
class RefreshView(TokenRefreshView):
    pass


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: UsuarioSesionOutputSerializer},
        tags=[OpenApiTag.AUTENTICACION],
        summary='Perfil y permisos efectivos del usuario en sesión',
    )
    def get(self, request):
        return Response(UsuarioSesionOutputSerializer(request.user).data)


# ---------------------------------------------------------------------------
# Administración de usuarios
# ---------------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(tags=[OpenApiTag.USUARIOS], responses=UsuarioOutputSerializer(many=True)),
    retrieve=extend_schema(tags=[OpenApiTag.USUARIOS], responses=UsuarioOutputSerializer),
    create=extend_schema(tags=[OpenApiTag.USUARIOS], request=UsuarioInputSerializer, responses={201: UsuarioOutputSerializer}),
    partial_update=extend_schema(tags=[OpenApiTag.USUARIOS], request=UsuarioInputSerializer, responses=UsuarioOutputSerializer),
)
class UserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    http_method_names = ['get', 'post', 'patch', 'head', 'options']
    permission_classes = [HasRiesgoTIPermission]
    required_permission = CodigoPermiso.USUARIO_ADMINISTRAR
    serializer_class = UsuarioOutputSerializer
    filterset_fields = ['activo', 'rol_id']
    search_fields = ['nombres', 'apellidos', 'correo']
    ordering_fields = ['id', 'apellidos', 'correo', 'creado_en']
    ordering = ['apellidos', 'nombres']

    def get_queryset(self):
        return Usuario.objects.select_related('rol').all()

    def create(self, request):
        dto = UsuarioInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        user = UserService.create_user(request.user, dto.validated_data)
        return Response(UsuarioOutputSerializer(user).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        instance = self.get_object()
        dto = UsuarioInputSerializer(instance, data=request.data, partial=True)
        dto.is_valid(raise_exception=True)
        user = UserService.update_user(request.user, instance, dto.validated_data)
        return Response(UsuarioOutputSerializer(user).data)


# ---------------------------------------------------------------------------
# Administración de roles y catálogo de permisos
# ---------------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(tags=[OpenApiTag.ROLES], responses=RolOutputSerializer(many=True)),
    retrieve=extend_schema(tags=[OpenApiTag.ROLES], responses=RolOutputSerializer),
    create=extend_schema(tags=[OpenApiTag.ROLES], request=RolInputSerializer, responses={201: RolOutputSerializer}),
    update=extend_schema(tags=[OpenApiTag.ROLES], request=RolInputSerializer, responses=RolOutputSerializer),
)
class RoleViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    http_method_names = ['get', 'post', 'put', 'head', 'options']
    permission_classes = [HasRiesgoTIPermission]
    required_permission = CodigoPermiso.ROL_ADMINISTRAR
    serializer_class = RolOutputSerializer
    ordering = ['id']

    def get_queryset(self):
        return Rol.objects.prefetch_related(
            Prefetch('rol_permisos', queryset=RolPermiso.objects.select_related('permiso')),
        ).all()

    def _reload(self, rol: Rol) -> Rol:
        return self.get_queryset().get(pk=rol.pk)

    def create(self, request):
        dto = RolInputSerializer(data=request.data)
        dto.is_valid(raise_exception=True)
        rol = RoleService.create_role(request.user, dto.validated_data)
        return Response(RolOutputSerializer(self._reload(rol)).data, status=status.HTTP_201_CREATED)

    def update(self, request, pk=None):
        instance = self.get_object()
        dto = RolInputSerializer(instance, data=request.data)
        dto.is_valid(raise_exception=True)
        rol = RoleService.update_role(request.user, instance, dto.validated_data)
        return Response(RolOutputSerializer(self._reload(rol)).data)


@extend_schema_view(
    list=extend_schema(tags=[OpenApiTag.ROLES], summary='Catálogo de permisos'),
    retrieve=extend_schema(tags=[OpenApiTag.ROLES]),
)
class PermissionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [HasRiesgoTIPermission]
    required_permission = CodigoPermiso.ROL_ADMINISTRAR
    serializer_class = PermisoOutputSerializer
    pagination_class = None
    ordering = ['codigo']

    def get_queryset(self):
        return Permiso.objects.all()
