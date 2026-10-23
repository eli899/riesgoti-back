from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import RegexValidator
from rest_framework import serializers

from apps.accounts.models import Permiso, Rol, Usuario
from apps.accounts.permissions import get_user_permission_codes


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------
class LoginInputSerializer(serializers.Serializer):
    correo = serializers.EmailField(max_length=150)
    password = serializers.CharField(write_only=True, trim_whitespace=False, max_length=128)

    def validate_correo(self, value: str) -> str:
        return Usuario.objects.normalize_email(value.strip())


class UsuarioSesionOutputSerializer(serializers.Serializer):
    usuario_id = serializers.IntegerField(source='id')
    correo = serializers.EmailField()
    nombres = serializers.CharField()
    apellidos = serializers.CharField()
    nombre_completo = serializers.CharField()
    rol_id = serializers.IntegerField()
    rol_codigo = serializers.CharField(source='rol.codigo')
    rol_nombre = serializers.CharField(source='rol.nombre')
    permisos = serializers.SerializerMethodField()

    def get_permisos(self, obj) -> list[str]:
        return sorted(get_user_permission_codes(obj))


class LoginOutputSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    user = UsuarioSesionOutputSerializer()


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------
class UsuarioInputSerializer(serializers.Serializer):
    """DTO de entrada para alta (POST) y edición parcial (PATCH) de USUARIO."""

    nombres = serializers.CharField(max_length=100)
    apellidos = serializers.CharField(max_length=100)
    correo = serializers.EmailField(max_length=150)
    rol_id = serializers.PrimaryKeyRelatedField(source='rol', queryset=Rol.objects.filter(activo=True))
    password = serializers.CharField(write_only=True, required=False, trim_whitespace=False, min_length=8, max_length=128)
    activo = serializers.BooleanField(required=False)

    def validate_correo(self, value: str) -> str:
        correo = Usuario.objects.normalize_email(value.strip())
        qs = Usuario.objects.filter(correo__iexact=correo)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('Ya existe un usuario con este correo.')
        return correo

    def validate(self, attrs):
        password = attrs.get('password')
        if self.instance is None and not password:
            raise serializers.ValidationError({'password': 'La contraseña es obligatoria al crear un usuario.'})
        if password:
            candidate = self.instance or Usuario(
                correo=attrs.get('correo', ''), nombres=attrs.get('nombres', ''), apellidos=attrs.get('apellidos', ''),
            )
            try:
                validate_password(password, user=candidate)
            except DjangoValidationError as exc:
                raise serializers.ValidationError({'password': exc.messages})
        return attrs


class UsuarioOutputSerializer(serializers.Serializer):
    """Mapper de salida de USUARIO: jamás expone password_hash."""

    id = serializers.IntegerField()
    nombres = serializers.CharField()
    apellidos = serializers.CharField()
    nombre_completo = serializers.CharField()
    correo = serializers.EmailField()
    rol_id = serializers.IntegerField()
    rol_codigo = serializers.CharField(source='rol.codigo')
    rol_nombre = serializers.CharField(source='rol.nombre')
    activo = serializers.BooleanField()
    creado_en = serializers.DateTimeField()
    ultima_modificacion = serializers.DateTimeField()


# ---------------------------------------------------------------------------
# Roles y permisos
# ---------------------------------------------------------------------------
class PermisoOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    codigo = serializers.CharField()
    descripcion = serializers.CharField(allow_null=True)
    activo = serializers.BooleanField()


class RolInputSerializer(serializers.Serializer):
    """DTO de entrada para POST/PUT de ROL. La validación SoD final se ejecuta en RoleService."""

    codigo = serializers.CharField(
        max_length=50,
        validators=[RegexValidator(r'^[A-Z][A-Z0-9_]*$', 'Use MAYÚSCULAS, dígitos y guion bajo (ej. AUDITOR_TI).')],
    )
    nombre = serializers.CharField(max_length=100)
    activo = serializers.BooleanField(default=True)
    permisos = serializers.ListField(child=serializers.CharField(max_length=50), allow_empty=True)

    def validate_codigo(self, value: str) -> str:
        qs = Rol.objects.filter(codigo=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('Ya existe un rol con este código.')
        return value

    def validate_permisos(self, value: list[str]) -> list[str]:
        codigos = set(value)
        existentes = set(Permiso.objects.filter(codigo__in=codigos, activo=True).values_list('codigo', flat=True))
        desconocidos = codigos - existentes
        if desconocidos:
            raise serializers.ValidationError(f'Permisos inexistentes o inactivos: {sorted(desconocidos)}.')
        return sorted(codigos)


class RolOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    activo = serializers.BooleanField()
    permisos = serializers.SerializerMethodField()
    total_usuarios = serializers.SerializerMethodField()
    creado_en = serializers.DateTimeField()
    ultima_modificacion = serializers.DateTimeField()

    def get_permisos(self, obj) -> list[str]:
        return sorted(rp.permiso.codigo for rp in obj.rol_permisos.all())

    def get_total_usuarios(self, obj) -> int:
        return obj.usuarios.count()
