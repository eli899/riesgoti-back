"""Mensajes de error de negocio del gobierno de riesgos."""

OBSERVACION_CORTA = 'Para {verbo} la propuesta debe registrar una observación de al menos {minimo} caracteres.'
SIN_CAMPO_CORREGIDO = 'Indique al menos un campo corregido para la nueva versión.'
REINTENTO_FUERA_DE_ESTADO = 'Solo se reintenta un análisis estratégico en ERROR (estado actual: {estado}).'
VERSION_YA_DECIDIDA = 'Esta versión de riesgo ya cuenta con una decisión registrada y es inmutable.'
INCIDENCIA_NO_VINCULADA = 'La incidencia no está vinculada a esta versión de riesgo.'
INCIDENCIA_YA_RETIRADA = 'La incidencia ya fue retirada de la agrupación.'
SOLO_RESTAURAR_RETIRADAS = 'Solo se restauran incidencias retiradas de la agrupación.'
AGRUPACION_VACIA = 'No hay incidencias incluidas en la agrupación; no puede confirmarse.'
CAMBIO_ACTIVO_SIN_JUSTIFICAR = (
    'El activo confirmado difiere del reportado en las incidencias; justifique el cambio (mínimo {minimo} caracteres).'
)
SIN_MATRIZ_ACTIVA = 'No existe una configuración de matriz activa.'
CELDA_NO_ENCONTRADA = 'No se encontró la celda correspondiente en la matriz activa.'
VALIDAR_SIN_AGRUPACION = 'Para validar la versión de riesgo debe confirmar primero el activo y la agrupación de incidencias.'
VALIDAR_SIN_EVALUACION = 'Para validar el riesgo debe existir una evaluación en matriz con su justificación.'
VALIDAR_SIN_FUENTES = (
    'La versión no posee fuentes documentales estratégicas citadas. '
    'Debe registrar justificacion_sin_fuentes (mínimo {minimo} caracteres).'
)

ACTIVO_INEXISTENTE = 'El activo seleccionado no existe o está inactivo.'
