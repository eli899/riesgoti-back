"""Constantes transversales del backend (constants-no-magic-strings)."""


class OpenApiTag:
    """Etiquetas de agrupación del esquema OpenAPI (drf-spectacular). Cadenas planas: se serializan tal cual en YAML."""

    SISTEMA = 'Sistema'
    AUTENTICACION = 'Autenticación'
    USUARIOS = 'Administración: Usuarios'
    ROLES = 'Administración: Roles'
    IA_RAG = 'Administración: IA/RAG'
    BASE_DOCUMENTAL = 'Administración: Base Documental'
    AUDITORIA = 'Auditoría'
    CATALOGO_ACTIVOS = 'Catálogo de Activos'
    MATRIZ_RIESGO = 'Matriz de Riesgo'
    INCIDENCIAS = 'Incidencias'
    GOBIERNO_RIESGOS = 'Gobierno de Riesgos'


# Tamaño de bloque para copiar y calcular el hash de archivos subidos (64 KiB).
IO_BLOCK_BYTES = 64 * 1024

# Longitud máxima del detalle de error persistido (VERSION_DOCUMENTO.error_procesamiento, TAREA_IA.error_detalle).
MAX_ERROR_CHARS = 2000

BYTES_PER_MB = 1024 * 1024


def column_max_length(model, field_name: str) -> int:
    """max_length de una columna CharField del modelo (espejo de bd.sql), para no repetirlo en los serializers."""
    return model._meta.get_field(field_name).max_length
