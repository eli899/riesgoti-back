from rest_framework import serializers


class EventoAuditoriaOutputSerializer(serializers.Serializer):
    """Mapper de salida de solo lectura para EVENTO_AUDITORIA."""

    id = serializers.IntegerField()
    accion = serializers.CharField()
    detalle = serializers.CharField(allow_null=True)
    ocurrido_en = serializers.DateTimeField()
    actor_id = serializers.IntegerField(allow_null=True)
    actor_nombre = serializers.SerializerMethodField()
    actor_correo = serializers.SerializerMethodField()
    incidencia_id = serializers.IntegerField(allow_null=True)
    version_riesgo_id = serializers.IntegerField(allow_null=True)
    version_documento_id = serializers.IntegerField(allow_null=True)
    matriz_id = serializers.IntegerField(allow_null=True)
    activo_id = serializers.IntegerField(allow_null=True)
    usuario_objeto_id = serializers.IntegerField(allow_null=True)
    rol_id = serializers.IntegerField(allow_null=True)

    def get_actor_nombre(self, obj) -> str | None:
        return obj.actor.nombre_completo if obj.actor else None

    def get_actor_correo(self, obj) -> str | None:
        return obj.actor.correo if obj.actor else None
