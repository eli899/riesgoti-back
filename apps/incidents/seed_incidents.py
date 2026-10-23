"""
Incidencias semilla 1..17 (seedIncidents de figma/src/data.ts) con historial de estados, tareas IA, orientación
operativa, respuesta del reportante, atención N2 y evidencias reales en disco. Las fechas se reconstruyen
relativas a hoy (ago(d, h) del prototipo). Los análisis estratégicos y vínculos de riesgo se siembran en v0.6.
"""
import hashlib
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Usuario
from apps.ai_config.models import ConfiguracionIARAG
from apps.assets_matrix.models import Activo
from apps.incidents.models import AtencionIncidencia, EvidenciaIncidencia, HistorialEstadoIncidencia, Incidencia
from apps.incidents.services import dispatch_ai_tasks, evidence_absolute_path
from apps.risks.models import OrientacionOperativa, PasoOrientacion, RespuestaOrientacion, TareaIA

USUARIOS = {
    'u1': 'lucia.ramirez@empresa.pe', 'u2': 'jorge.salas@empresa.pe',
    'u3': 'andrea.quispe@empresa.pe', 'u4': 'martin.torres@empresa.pe',
}
ACTIVOS = {f'a{n}': f'ACT-00{n}' for n in range(1, 8)}


SEED_PAST_MARGIN = timedelta(hours=1)


def ago(days: int, hour: int = 9):
    """Fecha del prototipo relativa a hoy, acotada al pasado (si la hora aún no llega hoy, se usa ahora - 1 h)."""
    now = timezone.localtime()
    target = now.replace(hour=hour, minute=15, second=0, microsecond=0) - timedelta(days=days)
    return min(target, now - SEED_PAST_MARGIN)


@dataclass(frozen=True)
class AI:
    tipo: str  # SUGERENCIA | SENSIBLE
    resumen: str
    pasos: tuple[str, ...] = ()
    advertencias: tuple[str, ...] = ()


SLOW_AI = AI(
    'SUGERENCIA', 'Entendemos que el ERP Contable responde con lentitud al abrir o guardar documentos.',
    ('Cierra las pestañas del ERP que no estés usando.', 'Cierra sesión en el ERP y vuelve a ingresar.',
     'Prueba desde otra red o navegador para descartar un problema local.'),
    ('No reinstales el cliente ni cambies configuraciones del sistema.',),
)


@dataclass
class Soporte:
    analista: str
    acciones: str
    nota: str
    inicio: tuple
    cierre: tuple | None = None


@dataclass
class SeedIncident:
    id: int
    titulo: str
    activo: str
    reportante: str
    fecha: tuple
    estado: str
    descripcion: str
    feedback: str | None = 'support'  # resolved -> FUNCIONO, support -> NO_FUNCIONO, None -> sin respuesta
    ai: AI | None = SLOW_AI
    estrategica: str = 'ready'  # ready | failed | pending (lo procesa celery_worker)
    evidencias: list[tuple[str, int]] = field(default_factory=list)
    soporte: Soporte | None = None


SEED_INCIDENTS = [
    SeedIncident(1, 'ERP muy lento al registrar facturas', 'a1', 'u1', (12,), 'CERRADA',
                 'Desde la mañana el ERP tarda más de un minuto en guardar cada factura.',
                 evidencias=[('captura-erp.png', 284000)],
                 soporte=Soporte('u3', 'Se reinició la sesión del usuario en el servidor de aplicaciones.',
                                 'El usuario recuperó la operatividad. Lentitud general persiste en horas punta.', (12, 10), (12, 11))),
    SeedIncident(2, 'El sistema está lento', 'a1', 'u2', (11,), 'CERRADA',
                 'El sistema contable está lento cuando abro el módulo de cuentas por pagar.', feedback='resolved'),
    SeedIncident(3, 'ERP se congela al generar reporte mensual', 'a1', 'u1', (9,), 'CERRADA',
                 'Al generar el reporte mensual el ERP se queda congelado varios minutos.',
                 soporte=Soporte('u4', 'Se programó el reporte fuera de horario punta.', 'Reporte generado correctamente.', (9, 10), (9, 12))),
    SeedIncident(4, 'Tiempo de espera agotado en el ERP', 'a1', 'u2', (7,), 'PENDIENTE_ATENCION_HUMANA',
                 'Aparece un mensaje de tiempo de espera agotado cuando intento conciliar cuentas.',
                 evidencias=[('error-timeout.log', 12400)]),
    SeedIncident(5, 'Lentitud en módulo de planillas', 'a1', 'u1', (6,), 'EN_ATENCION',
                 'El módulo de planillas del ERP tarda mucho en cargar los listados.',
                 soporte=Soporte('u3', 'Revisión de sesiones activas.', '', (5,))),
    SeedIncident(6, 'ERP no responde por momentos', 'a1', 'u2', (4,), 'CERRADA',
                 'Por momentos el ERP deja de responder y luego vuelve a funcionar.', feedback='resolved'),
    SeedIncident(7, 'Demora al guardar asientos contables', 'a1', 'u1', (3,), 'PENDIENTE_ATENCION_HUMANA',
                 'Guardar un asiento contable demora casi dos minutos.'),
    SeedIncident(8, 'Impresora lenta al imprimir reportes', 'a4', 'u2', (2,), 'CERRADA',
                 'La impresora del piso 3 tarda mucho en imprimir los reportes del ERP.',
                 ai=AI('SUGERENCIA', 'La impresora tarda en procesar trabajos.',
                       ['Verifica que no haya trabajos atascados en la cola.', 'Apaga y enciende la impresora.']),
                 soporte=Soporte('u4', 'Se limpió la cola de impresión.', 'Impresión normalizada.', (2, 10), (2, 11))),
    SeedIncident(9, 'Correo sospechoso solicitando credenciales', 'a2', 'u1', (20,), 'CERRADA',
                 'Recibí un correo que simula ser de TI y pide ingresar mi contraseña en un enlace.', feedback=None,
                 ai=AI('SENSIBLE', 'El reporte menciona una posible suplantación y solicitud de credenciales.', [],
                       ['No hagas clic en el enlace ni respondas el correo.', 'Un analista revisará el caso de inmediato.']),
                 soporte=Soporte('u3', 'Se bloqueó el remitente y se verificó que no se ingresaron credenciales.',
                                 'Caso contenido.', (20, 10), (20, 12))),
    SeedIncident(10, 'Otro correo de phishing con factura falsa', 'a2', 'u2', (1,), 'PENDIENTE_ATENCION_HUMANA',
                 'Llegó un correo con un adjunto llamado factura.zip de un proveedor desconocido.', feedback=None,
                 ai=AI('SENSIBLE', 'El reporte menciona un adjunto sospechoso que podría contener malware.', [],
                       ['No abras el adjunto.', 'Un analista revisará el caso de inmediato.'])),
    SeedIncident(11, 'No puedo conectarme a la VPN', 'a3', 'u1', (25,), 'CERRADA',
                 'La VPN rechaza la conexión desde casa desde ayer.',
                 ai=AI('SUGERENCIA', 'La VPN rechaza la conexión remota.',
                       ['Verifica tu conexión a internet.', 'Cierra el cliente VPN y vuelve a abrirlo.']),
                 soporte=Soporte('u4', 'Se renovó el certificado del cliente.', 'Conexión restablecida.', (25, 10), (25, 11))),
    SeedIncident(12, 'Inicios de sesión VPN desde ubicación desconocida', 'a3', 'u2', (5,), 'EN_ATENCION',
                 'Me llegó una alerta de inicio de sesión en la VPN desde otro país que no reconozco.', feedback=None,
                 ai=AI('SENSIBLE', 'El reporte menciona un posible acceso no autorizado.', [],
                       ['No compartas tu contraseña.', 'Un analista revisará el caso de inmediato.']),
                 soporte=Soporte('u4', 'Se forzó el cambio de contraseña.', '', (4,))),
    SeedIncident(13, 'La impresora imprime hojas en blanco', 'a4', 'u1', (30,), 'CERRADA',
                 'La impresora del piso 3 saca hojas en blanco.',
                 ai=AI('SUGERENCIA', 'La impresora no imprime contenido.', ['Revisa el nivel de tóner en la pantalla del equipo.']),
                 soporte=Soporte('u3', 'Cambio de tóner.', 'Resuelto.', (30, 10), (30, 11))),
    SeedIncident(14, 'No encuentro la copia de respaldo de ayer', 'a5', 'u2', (8,), 'CERRADA',
                 'Necesitaba restaurar un archivo y no aparece la copia de respaldo del día anterior.',
                 ai=AI('SUGERENCIA', 'No se localiza una copia de respaldo.', ['Revisa la carpeta de versiones anteriores del archivo.'],
                       ['No elimines archivos para liberar espacio.']),
                 soporte=Soporte('u3', 'Se restauró desde la copia semanal.',
                                 'Archivo recuperado. Se reportó la falla del respaldo diario.', (8, 10), (8, 13))),
    SeedIncident(15, 'Laptop se reinicia sola', 'a6', 'u1', (0, 8), 'PENDIENTE_ATENCION_HUMANA',
                 'Mi laptop se reinicia sola cada cierto tiempo sin mostrar mensaje.', estrategica='failed',
                 ai=AI('SUGERENCIA', 'La laptop se reinicia de forma inesperada.',
                       ['Guarda tu trabajo con frecuencia.', 'Verifica que el cargador esté bien conectado.'],
                       ['No abras el equipo ni modifiques la BIOS.'])),
    SeedIncident(16, 'Carpeta compartida no abre', 'a5', 'u2', (0, 7), 'EN_ANALISIS',
                 'La carpeta compartida de Finanzas muestra acceso denegado.', feedback=None, ai=None, estrategica='pending'),
    SeedIncident(17, 'Error 504 al consultar el libro mayor', 'a1', 'u2', (2, 16), 'CERRADA',
                 'El ERP muestra error 504 y demora al consultar el libro mayor durante el cierre contable.',
                 soporte=Soporte('u3', 'Se liberaron sesiones bloqueadas y se reintentó la consulta.',
                                 'Consulta restablecida; se mantiene el análisis de capacidad.', (2, 17), (2, 18))),
]


def _evidence_bytes(nombre: str, size: int) -> bytes:
    if nombre.endswith('.png'):
        header = b'\x89PNG\r\n\x1a\n'
        return header + bytes((i * 31) % 251 for i in range(size - len(header)))
    line = b'2026-10-01 09:15:00 ERROR erp.conciliacion TimeoutException: tiempo de espera agotado (60s)\n'
    return (line * (size // len(line) + 1))[:size]


class _Seeder:
    def __init__(self):
        self.users = {key: Usuario.objects.get(correo=correo) for key, correo in USUARIOS.items()}
        self.assets = {key: Activo.objects.get(codigo=codigo) for key, codigo in ACTIVOS.items()}
        self.cfg = ConfiguracionIARAG.objects.filter(activa=True).order_by('-creado_en', '-id').first()

    def transition(self, incidencia, estado, actor, motivo, when):
        entry = HistorialEstadoIncidencia.objects.create(incidencia=incidencia, estado=estado, actor=actor, motivo=motivo)
        HistorialEstadoIncidencia.objects.filter(pk=entry.pk).update(ocurrido_en=when)

    def task(self, incidencia, rama, estado, reportante, t0, **extra):
        sufijo = 'op' if rama == 'OPERATIVA' else 'est'
        tarea = TareaIA.objects.create(
            incidencia=incidencia, rama=rama, intento=1, clave_idempotencia=f'inc-{incidencia.id}-{sufijo}-v1',
            estado=estado, proveedor=getattr(self.cfg, 'proveedor_llm', None), modelo=getattr(self.cfg, 'modelo_llm', None),
            version_configuracion=getattr(self.cfg, 'version_configuracion', None), solicitada_por=reportante,
            iniciada_en=None if estado == 'PENDIENTE' else t0 + timedelta(seconds=2),
            terminada_en=extra.pop('terminada_en', None), **extra,
        )
        TareaIA.objects.filter(pk=tarea.pk).update(creada_en=t0 + timedelta(seconds=1))
        return tarea

    def seed(self, spec: SeedIncident) -> Incidencia:
        reportante = self.users[spec.reportante]
        t0 = ago(*spec.fecha)
        incidencia = Incidencia.objects.create(
            reportante=reportante, activo_reportado=self.assets[spec.activo], titulo=spec.titulo, descripcion=spec.descripcion,
        )
        Incidencia.objects.filter(pk=incidencia.pk).update(registrada_en=t0)

        for nombre, size in spec.evidencias:
            content = _evidence_bytes(nombre, size)
            sha256 = hashlib.sha256(content).hexdigest()
            clave = f'inc_{incidencia.id}/{sha256[:12]}_{nombre}'
            path = evidence_absolute_path(clave)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            evidencia = EvidenciaIncidencia.objects.create(
                incidencia=incidencia, nombre_original=nombre, clave_archivo=clave,
                tipo_mime='image/png' if nombre.endswith('.png') else 'text/plain', bytes=size, sha256=sha256,
            )
            EvidenciaIncidencia.objects.filter(pk=evidencia.pk).update(creada_en=t0)

        self.transition(incidencia, 'REGISTRADA', reportante, 'Registro inicial de incidencia por el reportante.', t0)
        self.transition(incidencia, 'EN_ANALISIS', reportante,
                        'Incidencia en análisis automático (ramas Operativa y Estratégica).', t0 + timedelta(seconds=1))

        # Rama operativa
        guidance_at = t0 + timedelta(seconds=8)
        if spec.ai is None:
            self.task(incidencia, 'OPERATIVA', 'PENDIENTE', reportante, t0)
        else:
            tarea_op = self.task(incidencia, 'OPERATIVA', 'COMPLETADA', reportante, t0, terminada_en=guidance_at)
            orientacion = OrientacionOperativa.objects.create(
                tarea=tarea_op, tipo=spec.ai.tipo, resumen=spec.ai.resumen,
                advertencia='\n'.join(spec.ai.advertencias) or None,
            )
            OrientacionOperativa.objects.filter(pk=orientacion.pk).update(creada_en=guidance_at)
            for orden, instruccion in enumerate(spec.ai.pasos, start=1):
                PasoOrientacion.objects.create(orientacion=orientacion, orden=orden, instruccion=instruccion)

            if spec.ai.tipo == 'SENSIBLE':
                self.transition(incidencia, 'PENDIENTE_ATENCION_HUMANA', reportante,
                                'Derivación automática: reporte sensible de seguridad que requiere contención por un analista.',
                                guidance_at)
            elif spec.feedback:
                respondida_en = t0 + timedelta(minutes=30)
                resultado = 'FUNCIONO' if spec.feedback == 'resolved' else 'NO_FUNCIONO'
                respuesta = RespuestaOrientacion.objects.create(orientacion=orientacion, resultado=resultado)
                RespuestaOrientacion.objects.filter(pk=respuesta.pk).update(respondida_en=respondida_en)
                if resultado == 'FUNCIONO':
                    self.transition(incidencia, 'CERRADA', reportante,
                                    'Resuelta mediante orientación operativa automática (confirmado por reportante).', respondida_en)
                else:
                    self.transition(incidencia, 'PENDIENTE_ATENCION_HUMANA', reportante,
                                    'La orientación operativa no resolvió el incidente; escalado a Analista N2.', respondida_en)

        # Rama estratégica (independiente de la operativa, INV-02)
        if spec.estrategica == 'ready':
            self.task(incidencia, 'ESTRATEGICA', 'COMPLETADA', reportante, t0, terminada_en=t0 + timedelta(seconds=20))
        elif spec.estrategica == 'failed':
            self.task(incidencia, 'ESTRATEGICA', 'ERROR', reportante, t0, terminada_en=t0 + timedelta(seconds=60),
                      error_codigo='PROVEEDOR_TIMEOUT', error_detalle='El proveedor de IA no respondió dentro del tiempo límite.')
        else:
            self.task(incidencia, 'ESTRATEGICA', 'PENDIENTE', reportante, t0)

        # Atención humana N2
        if spec.soporte:
            analista = self.users[spec.soporte.analista]
            inicio = ago(*spec.soporte.inicio)
            cierre = ago(*spec.soporte.cierre) if spec.soporte.cierre else None
            atencion = AtencionIncidencia.objects.create(
                incidencia=incidencia, analista=analista, acciones=spec.soporte.acciones,
                nota_resolucion=spec.soporte.nota or None, cerrada_en=cierre,
            )
            AtencionIncidencia.objects.filter(pk=atencion.pk).update(iniciada_en=inicio)
            self.transition(incidencia, 'EN_ATENCION', analista, f'Atención humana N2 iniciada por {analista.nombre_completo}.', inicio)
            if cierre:
                self.transition(incidencia, 'CERRADA', analista, 'Incidencia cerrada por el Analista N2 tras la atención humana.', cierre)

        actual = incidencia.historial_estados.order_by('-ocurrido_en', '-id').first().estado
        if actual != spec.estado:
            raise RuntimeError(f'Semilla INC-{spec.id:04d}: estado calculado {actual} != esperado {spec.estado}.')
        return incidencia


def seed_incidents(stdout) -> None:
    if Incidencia.objects.exists():
        stdout.write(f'  INCIDENCIA existentes conservadas ({Incidencia.objects.count()})')
        return
    seeder = _Seeder()
    created = [seeder.seed(spec) for spec in SEED_INCIDENTS]
    # Las tareas PENDIENTE (INC-0016) las procesan los workers reales de v0.5 tras el commit.
    pendientes = list(TareaIA.objects.filter(incidencia__in=created, estado='PENDIENTE').values_list('id', flat=True))
    transaction.on_commit(lambda: dispatch_ai_tasks(*pendientes))
    estados = {}
    for spec in SEED_INCIDENTS:
        estados[spec.estado] = estados.get(spec.estado, 0) + 1
    stdout.write(
        f'  INCIDENCIA: {len(created)} (ids {created[0].id}..{created[-1].id}) | '
        + ', '.join(f'{estado} {total}' for estado, total in sorted(estados.items()))
    )
