from rest_framework import serializers


class HealthcheckOutputSerializer(serializers.Serializer):
    status = serializers.CharField()
    service = serializers.CharField()
    version = serializers.CharField()
    database = serializers.CharField()
    master_key_loaded = serializers.BooleanField()
