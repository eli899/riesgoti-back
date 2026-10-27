"""Publicación inmutable de CONFIGURACION_MATRIZ (INV-04: los celda_id históricos jamás se alteran)."""
from django.db import transaction
from django.db.models import Prefetch
from rest_framework.exceptions import NotFound, ValidationError

from apps.assets_matrix import messages as msg
from apps.assets_matrix.models import CeldaMatriz, ConfiguracionMatriz, CriterioImpacto, CriterioProbabilidad
from apps.audit.constants import AccionAuditoria
from apps.audit.services import AuditService

ESTADO_PUBLICADA = 'PUBLICADA'


class MatrixService:
    @staticmethod
    def _with_structure(queryset):
        return queryset.select_related('creada_por').prefetch_related(
            'criterios_probabilidad',
            'criterios_impacto',
            Prefetch('celdas', queryset=CeldaMatriz.objects.select_related('nivel').order_by('probabilidad', 'impacto')),
        )

    @classmethod
    def get_active(cls) -> ConfiguracionMatriz:
        matriz = cls._with_structure(ConfiguracionMatriz.objects.filter(activa=True)).order_by('-creada_en', '-id').first()
        if matriz is None:
            raise NotFound(msg.SIN_MATRIZ_ACTIVA)
        return matriz

    @staticmethod
    def _criterios_from(model, matriz: ConfiguracionMatriz | None) -> list[dict]:
        if matriz is None:
            return []
        return [
            {'valor': c.valor, 'nombre': c.nombre, 'descripcion': c.descripcion}
            for c in model.objects.filter(matriz=matriz).order_by('valor')
        ]

    @classmethod
    @transaction.atomic
    def publish(cls, actor, data: dict) -> ConfiguracionMatriz:
        anteriores = list(ConfiguracionMatriz.objects.select_for_update().filter(activa=True))
        anterior = max(anteriores, key=lambda m: (m.creada_en, m.id), default=None)

        criterios_prob = data.get('criterios_probabilidad') or cls._criterios_from(CriterioProbabilidad, anterior)
        criterios_imp = data.get('criterios_impacto') or cls._criterios_from(CriterioImpacto, anterior)
        if not criterios_prob or not criterios_imp:
            raise ValidationError({'criterios': msg.SIN_MATRIZ_PARA_CLONAR})

        total = ConfiguracionMatriz.objects.count()
        ConfiguracionMatriz.objects.filter(pk__in=[m.pk for m in anteriores]).update(activa=False)
        matriz = ConfiguracionMatriz.objects.create(
            nombre=data.get('nombre') or (anterior.nombre if anterior else 'Matriz de riesgo'),
            version=f'v{total + 1}.0',
            estado=ESTADO_PUBLICADA,
            activa=True,
            creada_por=actor,
        )
        for criterio in criterios_prob:
            CriterioProbabilidad.objects.create(matriz=matriz, **criterio)
        for criterio in criterios_imp:
            CriterioImpacto.objects.create(matriz=matriz, **criterio)
        CeldaMatriz.objects.bulk_create([
            CeldaMatriz(matriz=matriz, probabilidad=c['probabilidad'], impacto=c['impacto'], nivel=c['nivel'])
            for c in data['celdas']
        ])

        AuditService.log(
            actor=actor,
            accion=AccionAuditoria.PUBLICAR_CONFIGURACION_MATRIZ,
            matriz=matriz,
            detalle=f'version={matriz.version} anterior={anterior.version if anterior else "-"} celdas={len(data["celdas"])}',
        )
        return cls._with_structure(ConfiguracionMatriz.objects.filter(pk=matriz.pk)).get()
