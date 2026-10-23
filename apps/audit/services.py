from apps.audit.models import EventoAuditoria


class AuditService:
    """Registro transversal de mutaciones críticas en EVENTO_AUDITORIA (ISO/IEC 27001 A.8.15)."""

    @staticmethod
    def log(
        *,
        actor=None,
        accion: str,
        detalle: str = '',
        incidencia=None,
        version_riesgo=None,
        version_documento=None,
        matriz=None,
        activo=None,
        usuario_objeto=None,
        rol=None,
    ) -> EventoAuditoria:
        actor_instance = actor if (actor and getattr(actor, 'is_authenticated', False)) else None
        return EventoAuditoria.objects.create(
            actor=actor_instance,
            accion=accion,
            detalle=detalle,
            incidencia=incidencia,
            version_riesgo=version_riesgo,
            version_documento=version_documento,
            matriz=matriz,
            activo=activo,
            usuario_objeto=usuario_objeto,
            rol=rol,
        )
