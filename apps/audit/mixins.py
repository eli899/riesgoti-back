from django.db import transaction

from apps.audit.services import AuditService


class AuditLogMixin:
    """
    Registra automáticamente un EVENTO_AUDITORIA en cada create/update de un ViewSet DRF.

    El ViewSet declara:
      * audit_actions = {'create': AccionAuditoria.CREAR_ACTIVO, 'update': AccionAuditoria.ACTUALIZAR_ACTIVO}
      * get_audit_targets(instance) -> dict con las FKs de EVENTO_AUDITORIA (activo=, rol=, ...)
      * get_audit_detail(instance, action) -> str (opcional)
    La mutación y su evento se confirman en la misma transacción.
    """

    audit_actions: dict[str, str] = {}

    def get_audit_targets(self, instance) -> dict:
        return {}

    def get_audit_detail(self, instance, action: str) -> str:
        return f'{instance._meta.db_table} id={instance.pk}'

    def resolve_audit_action(self, instance, action: str) -> str | None:
        return self.audit_actions.get(action)

    def log_audit(self, instance, action: str) -> None:
        accion = self.resolve_audit_action(instance, action)
        if not accion:
            return
        AuditService.log(
            actor=self.request.user,
            accion=accion,
            detalle=self.get_audit_detail(instance, action),
            **self.get_audit_targets(instance),
        )

    def perform_create(self, serializer):
        with transaction.atomic():
            instance = serializer.save()
            self.log_audit(instance, 'create')

    def perform_update(self, serializer):
        with transaction.atomic():
            instance = serializer.save()
            self.log_audit(instance, 'update')
