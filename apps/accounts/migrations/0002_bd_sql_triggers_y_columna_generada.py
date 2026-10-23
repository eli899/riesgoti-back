from django.db import migrations

TABLAS = ['ROL', 'PERMISO', 'ROL_PERMISO', 'USUARIO']

CREAR_FUNCION = """
CREATE OR REPLACE FUNCTION update_ultima_modificacion_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.ultima_modificacion = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# CONCAT() es STABLE en PostgreSQL y no se admite en columnas generadas; || es equivalente
# porque nombres y apellidos son NOT NULL.
CREAR_NOMBRE_COMPLETO = """
ALTER TABLE "USUARIO" ADD COLUMN IF NOT EXISTS nombre_completo VARCHAR(200)
    GENERATED ALWAYS AS (nombres || ' ' || apellidos) STORED;
"""


def trigger_sql(tabla):
    return (
        f'CREATE TRIGGER "trg_{tabla}_ultima_modificacion" BEFORE UPDATE ON "{tabla}" '
        f'FOR EACH ROW EXECUTE FUNCTION update_ultima_modificacion_column();'
    )


def drop_trigger_sql(tabla):
    return f'DROP TRIGGER IF EXISTS "trg_{tabla}_ultima_modificacion" ON "{tabla}";'


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(CREAR_FUNCION, 'DROP FUNCTION IF EXISTS update_ultima_modificacion_column() CASCADE;'),
        migrations.RunSQL(CREAR_NOMBRE_COMPLETO, 'ALTER TABLE "USUARIO" DROP COLUMN IF EXISTS nombre_completo;'),
        *[migrations.RunSQL(trigger_sql(tabla), drop_trigger_sql(tabla)) for tabla in TABLAS],
    ]
