"""Mensajes de error de negocio de la base documental."""

CODIGO_FORMATO = 'Use letras, dígitos, punto, guion o guion bajo (ej. POL-SGSI-01).'
PDF_DEMASIADO_GRANDE = 'El PDF supera el tamaño máximo de {mb} MB.'
SOLO_PDF = 'Solo se permiten archivos .pdf.'
PDF_INVALIDO = 'El archivo no es un PDF válido (firma %PDF- ausente).'
VERSION_DUPLICADA = 'El documento {codigo} ya tiene la versión {version}.'
PDF_DUPLICADO = 'Este PDF ya fue cargado como la versión {version}.'
AUTORIZAR_NO_PROCESADA = 'Solo se autorizan versiones procesadas; estado actual: {estado}.'
REACTIVAR_NO_AUTORIZADA = 'Solo una versión AUTORIZADA puede reactivarse.'
REPROCESAR_ESTADO_INVALIDO = (
    'Solo se re-procesan versiones en ERROR o PENDIENTE_AUTORIZACION '
    '(una versión autorizada se re-indexa, nunca se re-segmenta).'
)
REPROCESAR_AUTORIZADA = 'Una versión que ya fue autorizada no puede re-segmentarse (INV-04).'
REINDEXAR_NO_PROCESADA = 'Solo se re-indexan versiones procesadas (PENDIENTE_AUTORIZACION o AUTORIZADO).'
