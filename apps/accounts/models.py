from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Now


class Rol(models.Model):
    id = models.AutoField(primary_key=True, db_column='id')
    codigo = models.CharField(max_length=50, db_column='codigo')
    nombre = models.CharField(max_length=100, db_column='nombre')
    activo = models.BooleanField(default=True, db_default=True, db_column='activo')
    creado_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creado_en')
    ultima_modificacion = models.DateTimeField(auto_now=True, db_default=Now(), db_column='ultima_modificacion')

    class Meta:
        db_table = 'ROL'

    def __str__(self):
        return self.codigo


class Permiso(models.Model):
    id = models.AutoField(primary_key=True, db_column='id')
    codigo = models.CharField(max_length=50, db_column='codigo')
    descripcion = models.TextField(null=True, blank=True, db_column='descripcion')
    activo = models.BooleanField(default=True, db_default=True, db_column='activo')
    creado_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creado_en')
    ultima_modificacion = models.DateTimeField(auto_now=True, db_default=Now(), db_column='ultima_modificacion')

    class Meta:
        db_table = 'PERMISO'

    def __str__(self):
        return self.codigo


class RolPermiso(models.Model):
    pk = models.CompositePrimaryKey('rol_id', 'permiso_id')
    rol = models.ForeignKey(Rol, on_delete=models.CASCADE, db_column='rol_id', related_name='rol_permisos')
    permiso = models.ForeignKey(Permiso, on_delete=models.CASCADE, db_column='permiso_id', related_name='permiso_roles')
    creado_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creado_en')
    ultima_modificacion = models.DateTimeField(auto_now=True, db_default=Now(), db_column='ultima_modificacion')

    class Meta:
        db_table = 'ROL_PERMISO'


class UsuarioManager(BaseUserManager):
    def create_user(self, correo: str, nombres: str, apellidos: str, rol: Rol, password: str | None = None):
        if not correo:
            raise ValueError('El usuario debe tener un correo electrónico')
        correo = self.normalize_email(correo)
        user = self.model(correo=correo, nombres=nombres, apellidos=apellidos, rol=rol, activo=True)
        user.set_password(password)
        user.save(using=self._db)
        return user


class Usuario(AbstractBaseUser):
    id = models.AutoField(primary_key=True, db_column='id')
    rol = models.ForeignKey(Rol, on_delete=models.PROTECT, db_column='rol_id', related_name='usuarios')
    nombres = models.CharField(max_length=100, db_column='nombres')
    apellidos = models.CharField(max_length=100, db_column='apellidos')
    # nombre_completo es una columna GENERATED ALWAYS en PostgreSQL (migración accounts.0002);
    # el ORM no la escribe y se expone mediante la propiedad homónima.
    correo = models.EmailField(max_length=150, unique=True, db_column='correo')
    password = models.CharField(max_length=255, db_column='password_hash')
    activo = models.BooleanField(default=True, db_default=True, db_column='activo')
    creado_en = models.DateTimeField(auto_now_add=True, db_default=Now(), db_column='creado_en')
    ultima_modificacion = models.DateTimeField(auto_now=True, db_default=Now(), db_column='ultima_modificacion')

    # bd.sql no define last_login.
    last_login = None

    USERNAME_FIELD = 'correo'
    EMAIL_FIELD = 'correo'
    REQUIRED_FIELDS = ['nombres', 'apellidos']

    objects = UsuarioManager()

    class Meta:
        db_table = 'USUARIO'

    def __str__(self):
        return self.correo

    @property
    def nombre_completo(self) -> str:
        return f'{self.nombres} {self.apellidos}'.strip()

    @property
    def is_active(self) -> bool:
        return self.activo
