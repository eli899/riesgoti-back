"""Escala de la matriz de riesgo y del catálogo de activos."""

# Matriz de evaluación 5x5 (CELDA_MATRIZ): probabilidad e impacto de MATRIX_MIN_LEVEL a MATRIX_SIZE.
MATRIX_SIZE = 5
MATRIX_MIN_LEVEL = 1

# ACTIVO.criticidad en la escala de NIVEL_RIESGO (1 = BAJO .. 4 = CRITICO).
CRITICIDAD_MIN, CRITICIDAD_MAX = 1, 4
