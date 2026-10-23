from django.db import migrations

TABLAS = [
    'TIPO_ACTIVO', 'ACTIVO', 'NIVEL_RIESGO', 'CONFIGURACION_MATRIZ',
    'CRITERIO_PROBABILIDAD', 'CRITERIO_IMPACTO', 'CELDA_MATRIZ',
]

# FKs compuestas de bd.sql que el ORM de Django no puede declarar.
FKS_COMPUESTAS = [
    ('FK_CELDA_MATRIZ_PROB', 'probabilidad', 'CRITERIO_PROBABILIDAD'),
    ('FK_CELDA_MATRIZ_IMP', 'impacto', 'CRITERIO_IMPACTO'),
]


def fk_sql(nombre, columna, tabla_ref):
    return (
        f'ALTER TABLE "CELDA_MATRIZ" ADD CONSTRAINT "{nombre}" '
        f'FOREIGN KEY (matriz_id, {columna}) REFERENCES "{tabla_ref}" (matriz_id, valor) '
        f'DEFERRABLE INITIALLY DEFERRED;'
    )


def trigger_sql(tabla):
    return (
        f'CREATE TRIGGER "trg_{tabla}_ultima_modificacion" BEFORE UPDATE ON "{tabla}" '
        f'FOR EACH ROW EXECUTE FUNCTION update_ultima_modificacion_column();'
    )


def drop_trigger_sql(tabla):
    return f'DROP TRIGGER IF EXISTS "trg_{tabla}_ultima_modificacion" ON "{tabla}";'


class Migration(migrations.Migration):

    dependencies = [
        ('assets_matrix', '0001_initial'),
        ('accounts', '0002_bd_sql_triggers_y_columna_generada'),
    ]

    operations = [
        *[
            migrations.RunSQL(fk_sql(nombre, columna, tabla_ref), f'ALTER TABLE "CELDA_MATRIZ" DROP CONSTRAINT IF EXISTS "{nombre}";')
            for nombre, columna, tabla_ref in FKS_COMPUESTAS
        ],
        *[migrations.RunSQL(trigger_sql(tabla), drop_trigger_sql(tabla)) for tabla in TABLAS],
    ]
