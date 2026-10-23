from django.db import migrations

TABLAS = ['DOCUMENTO', 'VERSION_DOCUMENTO', 'FRAGMENTO_DOCUMENTO']


def trigger_sql(tabla):
    return (
        f'CREATE TRIGGER "trg_{tabla}_ultima_modificacion" BEFORE UPDATE ON "{tabla}" '
        f'FOR EACH ROW EXECUTE FUNCTION update_ultima_modificacion_column();'
    )


def drop_trigger_sql(tabla):
    return f'DROP TRIGGER IF EXISTS "trg_{tabla}_ultima_modificacion" ON "{tabla}";'


class Migration(migrations.Migration):

    dependencies = [
        ('documents_rag', '0001_initial'),
        ('accounts', '0002_bd_sql_triggers_y_columna_generada'),
    ]

    operations = [migrations.RunSQL(trigger_sql(tabla), drop_trigger_sql(tabla)) for tabla in TABLAS]
