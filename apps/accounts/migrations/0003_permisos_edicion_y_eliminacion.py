"""
Permisos de edición y eliminación física (CHG-0035) para bases ya pobladas. En una base vacía no hay roles
y la migración no hace nada: seed_riesgoti crea el catálogo completo.
"""
from django.db import migrations

PERMISOS = [
    ('incidencia.editar_propias', 'Editar incidencias propias que aún no están cerradas', 'REPORTANTE'),
    ('incidencia.eliminar', 'Eliminar físicamente incidencias sin evidencia de riesgo decidida', 'ADMIN'),
    ('riesgo.eliminar', 'Eliminar físicamente versiones de riesgo sin evaluación ni decisión', 'ADMIN'),
]


def agregar_permisos(apps, schema_editor):
    Rol = apps.get_model('accounts', 'Rol')
    Permiso = apps.get_model('accounts', 'Permiso')
    RolPermiso = apps.get_model('accounts', 'RolPermiso')
    if not Rol.objects.exists():
        return
    for codigo, descripcion, rol_codigo in PERMISOS:
        permiso, _ = Permiso.objects.get_or_create(codigo=codigo, defaults={'descripcion': descripcion, 'activo': True})
        rol = Rol.objects.filter(codigo=rol_codigo).first()
        if rol is not None:
            RolPermiso.objects.get_or_create(rol=rol, permiso=permiso)


def quitar_permisos(apps, schema_editor):
    Permiso = apps.get_model('accounts', 'Permiso')
    Permiso.objects.filter(codigo__in=[codigo for codigo, _, _ in PERMISOS]).delete()


class Migration(migrations.Migration):
    dependencies = [('accounts', '0002_bd_sql_triggers_y_columna_generada')]

    operations = [migrations.RunPython(agregar_permisos, quitar_permisos)]
