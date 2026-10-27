from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.incidents.services import dispatch_ai_tasks
from apps.risks.constants import EstadoTareaIA
from apps.risks.models import TareaIA


class Command(BaseCommand):
    help = (
        'Re-encola en Celery las TAREA_IA en PENDIENTE (p. ej. creadas antes de existir los workers). '
        'Con --stale-minutes también recupera tareas PROCESANDO abandonadas por un worker caído.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--stale-minutes', type=int, default=None,
                            help='Devuelve a PENDIENTE las tareas PROCESANDO iniciadas hace más de N minutos.')
        parser.add_argument('--dry-run', action='store_true', help='Solo lista las tareas que se re-encolarían.')

    def handle(self, *args, stale_minutes=None, dry_run=False, **options):
        if stale_minutes is not None:
            limite = timezone.now() - timedelta(minutes=stale_minutes)
            stale = TareaIA.objects.filter(estado=EstadoTareaIA.PROCESANDO).filter(iniciada_en__lt=limite) | \
                TareaIA.objects.filter(estado=EstadoTareaIA.PROCESANDO, iniciada_en__isnull=True)
            ids = list(stale.values_list('id', flat=True))
            if ids and not dry_run:
                TareaIA.objects.filter(id__in=ids).update(estado=EstadoTareaIA.PENDIENTE, iniciada_en=None)
            self.stdout.write(f'Tareas PROCESANDO abandonadas devueltas a PENDIENTE: {ids or "ninguna"}')

        pendientes = list(TareaIA.objects.filter(estado=EstadoTareaIA.PENDIENTE).order_by('id').values_list('id', flat=True))
        if pendientes and not dry_run:
            dispatch_ai_tasks(*pendientes)
        accion = 'Se re-encolarían' if dry_run else 'Re-encoladas'
        self.stdout.write(self.style.SUCCESS(f'{accion} {len(pendientes)} TAREA_IA en PENDIENTE: {pendientes or "ninguna"}'))
