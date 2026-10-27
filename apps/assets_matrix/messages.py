"""Mensajes de error de negocio del catálogo de activos y de la matriz de riesgo."""

ACTIVO_CODIGO_DUPLICADO = 'Ya existe un activo con este código.'
CRITERIOS_INCOMPLETOS = 'Debe definir exactamente los valores 1..{maximo} sin repetir.'
GRILLA_INCOMPLETA = 'La grilla debe contener exactamente {celdas} celdas con coordenadas (probabilidad, impacto) únicas.'
SIN_MATRIZ_ACTIVA = 'No existe una matriz de riesgo activa.'
SIN_MATRIZ_PARA_CLONAR = 'No hay matriz activa de la cual clonar criterios; envíelos explícitamente.'
