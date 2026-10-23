from rest_framework import serializers

from apps.assets_matrix.models import Activo, NivelRiesgo, TipoActivo

MATRIX_SIZE = 5


# ---------------------------------------------------------------------------
# Catálogo de activos
# ---------------------------------------------------------------------------
class TipoActivoOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nombre = serializers.CharField()
    activo = serializers.BooleanField()


class ActivoInputSerializer(serializers.Serializer):
    """DTO de entrada de ACTIVO (POST completo / PATCH parcial). Nunca se elimina: se desactiva."""

    tipo_id = serializers.PrimaryKeyRelatedField(source='tipo', queryset=TipoActivo.objects.filter(activo=True))
    codigo = serializers.CharField(max_length=50)
    nombre = serializers.CharField(max_length=150)
    descripcion = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    criticidad = serializers.IntegerField(min_value=1, max_value=4, required=False, allow_null=True)
    activo = serializers.BooleanField(required=False, default=True)

    def validate_codigo(self, value: str) -> str:
        codigo = value.strip().upper()
        qs = Activo.objects.filter(codigo__iexact=codigo)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('Ya existe un activo con este código.')
        return codigo

    def create(self, validated_data):
        return Activo.objects.create(**validated_data)

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        return instance


class ActivoOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    tipo_id = serializers.IntegerField()
    tipo_nombre = serializers.CharField(source='tipo.nombre')
    codigo = serializers.CharField()
    nombre = serializers.CharField()
    descripcion = serializers.CharField(allow_null=True)
    criticidad = serializers.IntegerField(allow_null=True)
    activo = serializers.BooleanField()
    creado_en = serializers.DateTimeField()
    ultima_modificacion = serializers.DateTimeField()


# ---------------------------------------------------------------------------
# Matriz de riesgo 5x5
# ---------------------------------------------------------------------------
class NivelRiesgoOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    codigo = serializers.CharField()
    orden = serializers.IntegerField()


class CriterioOutputSerializer(serializers.Serializer):
    valor = serializers.IntegerField()
    nombre = serializers.CharField()
    descripcion = serializers.CharField(allow_null=True)


class CeldaOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    probabilidad = serializers.IntegerField()
    impacto = serializers.IntegerField()
    nivel_id = serializers.IntegerField()
    nivel_codigo = serializers.CharField(source='nivel.codigo')
    nivel_orden = serializers.IntegerField(source='nivel.orden')


class MatrizActivaOutputSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    nombre = serializers.CharField()
    version = serializers.CharField()
    estado = serializers.CharField()
    activa = serializers.BooleanField()
    creada_por_id = serializers.IntegerField()
    creada_por_nombre = serializers.CharField(source='creada_por.nombre_completo')
    creada_en = serializers.DateTimeField()
    niveles = serializers.SerializerMethodField()
    criterios_probabilidad = CriterioOutputSerializer(many=True)
    criterios_impacto = CriterioOutputSerializer(many=True)
    celdas = CeldaOutputSerializer(many=True)

    def get_niveles(self, obj) -> list[dict]:
        return NivelRiesgoOutputSerializer(NivelRiesgo.objects.order_by('orden'), many=True).data


class CriterioInputSerializer(serializers.Serializer):
    valor = serializers.IntegerField(min_value=1, max_value=MATRIX_SIZE)
    nombre = serializers.CharField(max_length=100)
    descripcion = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class CeldaInputSerializer(serializers.Serializer):
    probabilidad = serializers.IntegerField(min_value=1, max_value=MATRIX_SIZE)
    impacto = serializers.IntegerField(min_value=1, max_value=MATRIX_SIZE)
    nivel_codigo = serializers.SlugRelatedField(source='nivel', slug_field='codigo', queryset=NivelRiesgo.objects.all())


def _validate_criterios(value: list[dict]) -> list[dict]:
    valores = sorted(c['valor'] for c in value)
    if valores != list(range(1, MATRIX_SIZE + 1)):
        raise serializers.ValidationError(f'Debe definir exactamente los valores 1..{MATRIX_SIZE} sin repetir.')
    return sorted(value, key=lambda c: c['valor'])


class PublishMatrixInputSerializer(serializers.Serializer):
    """
    DTO de publicación de una nueva CONFIGURACION_MATRIZ. Exige las 25 coordenadas (probabilidad, impacto)
    únicas en rango 1..5. Los criterios son opcionales: si se omiten se clonan desde la matriz activa.
    """

    nombre = serializers.CharField(max_length=100, required=False)
    criterios_probabilidad = CriterioInputSerializer(many=True, required=False)
    criterios_impacto = CriterioInputSerializer(many=True, required=False)
    celdas = CeldaInputSerializer(many=True)

    def validate_criterios_probabilidad(self, value):
        return _validate_criterios(value)

    def validate_criterios_impacto(self, value):
        return _validate_criterios(value)

    def validate_celdas(self, value):
        coordenadas = {(c['probabilidad'], c['impacto']) for c in value}
        if len(value) != MATRIX_SIZE ** 2 or len(coordenadas) != MATRIX_SIZE ** 2:
            raise serializers.ValidationError(
                f'La grilla debe contener exactamente {MATRIX_SIZE ** 2} celdas con coordenadas (probabilidad, impacto) únicas.'
            )
        return value
