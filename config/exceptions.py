"""Excepciones HTTP compartidas por los servicios de dominio."""
from django.db.models import ProtectedError, RestrictedError
from rest_framework import status
from rest_framework.exceptions import APIException


class Conflict(APIException):
    """409 Conflict (RFC 9110 §15.5.10): el estado actual del recurso impide la operación solicitada."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = 'El recurso tiene dependencias que impiden la operación.'
    default_code = 'conflict'


def delete_or_conflict(instance, message: str) -> None:
    """
    Elimina físicamente `instance` (con las cascadas del ORM). Si una FK PROTECT lo impide, responde 409 con
    `message` en lugar de un 500. Debe invocarse dentro de transaction.atomic() para revertir cascadas parciales.
    """
    try:
        instance.delete()
    except (ProtectedError, RestrictedError) as exc:
        raise Conflict(message) from exc
