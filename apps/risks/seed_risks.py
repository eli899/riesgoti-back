"""
Riesgos semilla RSG-0001..0005 (seedRisks de figma/src/data.ts): ANALISIS_INCIDENCIA de las incidencias semilla,
VERSION_RIESGO con citas a FRAGMENTO_DOCUMENTO reales, VERSION_INCIDENCIA, EVALUACION_RIESGO y DECISION_RIESGO.

Desviación deliberada: INC-0008 (impresora, falso positivo de RSG-0001) queda SUGERIDA en lugar de RETIRADA para
que el flujo QA #4 del frontend (retiro de falso positivo) pueda ejecutarse sobre los datos semilla.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from apps.accounts.models import Usuario
from apps.assets_matrix.models import Activo, CeldaMatriz, ConfiguracionMatriz
from apps.documents_rag.models import FragmentoDocumento
from apps.incidents.models import Incidencia
from apps.incidents.seed_incidents import SEED_INCIDENTS, ago
from apps.risks.llm_schemas import NO_DETERMINADO
from apps.risks.models import (
    AnalisisIncidencia,
    CitaVersionRiesgo,
    DecisionRiesgo,
    EvaluacionRiesgo,
    Riesgo,
    TareaIA,
    VersionIncidencia,
    VersionRiesgo,
)

ANALISTAS = {'u3': 'andrea.quispe@empresa.pe', 'u4': 'martin.torres@empresa.pe'}
DOCS = {'d1': 'POL-CONT-01', 'd2': 'PRO-ACC-01', 'd4': 'MAN-EST-01'}
SLOW_REASON = 'Mismo activo identificado y amenaza de interrupción del servicio en los últimos 14 días.'


def D(days: int):
    return ago(days, 14)


@dataclass
class Link:
    inc: int
    estado: str
    similitud: str
    motivo: str
    extracto: str
    motivo_retiro: str | None = None


@dataclass
class Version:
    numero: int
    titulo: str
    creada: int
    descripcion: str
    amenaza: str | None
    vulnerabilidad: str | None
    consecuencia: str | None
    activo_identificado: str
    recomendacion: str | None = None
    origen: str = 'IA'
    creador: str | None = None  # analista (origen ANALISTA); si es None, el reportante de la incidencia de origen
    fuentes: list[tuple[str, int]] = field(default_factory=list)
    activo_confirmado: str | None = None
    links: list[Link] = field(default_factory=list)
    evaluacion: tuple | None = None  # (p, i, justificacion, analista, dias)
    decision: tuple | None = None  # (accion, analista, dias, observacion)


@dataclass
class Risk:
    numero: int
    creado: int
    versiones: list[Version]


ERP_FIELDS = dict(
    descripcion='Reportes recurrentes de lentitud, congelamiento y tiempos de espera en el ERP Contable que afectan procesos financieros.',
    amenaza='Posible interrupción o denegación de servicio',
    vulnerabilidad='Capacidad insuficiente del servidor de aplicaciones en horas punta',
    consecuencia='Retraso en el registro contable y cierre de periodo',
    activo_identificado='ERP Contable / sistema contable',
)
PHISHING_REC = 'Reforzar la capacitación periódica sobre identificación de correos de suplantación [1].'

SEED_RISKS = [
    Risk(1, 12, [Version(
        1, 'Degradación del servicio del ERP Contable', 2, **ERP_FIELDS,
        recomendacion='Implementar monitoreo de capacidad con umbrales de alerta [1] y realizar un análisis de causa raíz '
                      'para planificar la ampliación de recursos [2].',
        fuentes=[('d1', 12), ('d1', 14)],
        links=[
            Link(1, 'SUGERIDA', '0.91', SLOW_REASON, 'tarda más de un minuto en guardar cada factura'),
            Link(2, 'SUGERIDA', '0.88', SLOW_REASON, 'El sistema contable está lento'),
            Link(3, 'SUGERIDA', '0.84', SLOW_REASON, 'se queda congelado varios minutos'),
            Link(4, 'SUGERIDA', '0.82', 'Mismo activo; consecuencia similar (tiempo de espera agotado).', 'tiempo de espera agotado'),
            Link(5, 'SUGERIDA', '0.86', SLOW_REASON, 'tarda mucho en cargar los listados'),
            Link(6, 'SUGERIDA', '0.79', 'Mismo activo; el servicio deja de responder de forma intermitente.', 'deja de responder y luego vuelve'),
            Link(7, 'SUGERIDA', '0.87', SLOW_REASON, 'demora casi dos minutos'),
            Link(17, 'SUGERIDA', '0.89', SLOW_REASON, 'error 504 y demora al consultar el libro mayor'),
            Link(8, 'SUGERIDA', '0.58', 'Coincidencia semántica por "lenta" en la descripción del reporte.',
                 'tarda mucho en imprimir los reportes del ERP'),
        ],
    )]),
    Risk(2, 20, [
        Version(
            1, 'Suplantación de identidad por correo electrónico', 19,
            'Correos que simulan comunicaciones internas para obtener credenciales.',
            'Suplantación de identidad (phishing)', 'Falta de concienciación del personal ante correos fraudulentos',
            'Compromiso de credenciales corporativas', 'Correo corporativo', recomendacion=PHISHING_REC,
            fuentes=[('d2', 18)], activo_confirmado='ACT-002',
            links=[Link(9, 'CONFIRMADA', '1.0000', 'Incidencia de origen.', 'pide ingresar mi contraseña en un enlace')],
            evaluacion=(4, 4, 'Recurrencia observada y posible compromiso de cuentas con acceso a información financiera.', 'u3', 18),
            decision=('VALIDADA', 'u3', 18, 'Contenido revisado y coherente con la fuente.'),
        ),
        Version(
            2, 'Suplantación de identidad por correo con adjuntos maliciosos', 1,
            'Nueva incidencia con adjunto comprimido de remitente desconocido; posible recurrencia.',
            'Suplantación de identidad y distribución de malware', 'Falta de concienciación del personal ante correos fraudulentos',
            'Compromiso de credenciales o infección de equipos', 'Correo corporativo', recomendacion=PHISHING_REC,
            fuentes=[('d2', 18)],
            links=[Link(10, 'SUGERIDA', '0.81', 'Coincide con un riesgo validado: misma amenaza y activo.', 'adjunto llamado factura.zip')],
        ),
    ]),
    Risk(3, 25, [
        Version(
            1, 'Acceso remoto no autorizado', 24, 'Fallas de conexión a la VPN.', 'Acceso no autorizado', 'Certificados vencidos',
            'Pérdida de conectividad remota', 'VPN', recomendacion='Renovar certificados de clientes.',
            links=[
                Link(11, 'SUGERIDA', '1.0000', 'Incidencia de origen.', 'rechaza la conexión'),
                Link(12, 'SUGERIDA', '0.83', 'Mismo activo y amenaza de acceso.', 'inicio de sesión desde otro país'),
            ],
            decision=('CORREGIDA', 'u4', 4, 'La vulnerabilidad real es la ausencia de MFA, evidenciada en INC-0012.'),
        ),
        Version(
            2, 'Acceso remoto no autorizado a la VPN', 4, 'Inicios de sesión en la VPN desde ubicaciones no reconocidas.',
            'Acceso no autorizado', 'Ausencia de autenticación multifactor en la VPN', 'Exposición de información interna', 'VPN',
            recomendacion='Exigir autenticación multifactor para el acceso remoto [1] y alertar accesos desde ubicaciones no habituales [2].',
            origen='ANALISTA', creador='u4', fuentes=[('d2', 7), ('d2', 9)], activo_confirmado='ACT-003',
            links=[
                Link(11, 'CONFIRMADA', '1.0000', 'Incidencia de origen.', 'rechaza la conexión'),
                Link(12, 'CONFIRMADA', '0.83', 'Mismo activo y amenaza de acceso.', 'inicio de sesión desde otro país'),
            ],
            evaluacion=(3, 5, 'Acceso detectado desde el extranjero; la VPN da acceso a sistemas críticos.', 'u4', 4),
            decision=('VALIDADA', 'u4', 4, 'Validada tras corrección de vulnerabilidad.'),
        ),
    ]),
    Risk(4, 30, [Version(
        1, 'Falla de impresión en equipo del piso 3', 29, 'Hojas en blanco al imprimir.', 'Falla de equipo', None,
        'Interrupción menor de impresión', 'Impresora',
        recomendacion='Mantener actualizada la protección de las estaciones y equipos asociados [1].', fuentes=[('d4', 4)],
        links=[Link(13, 'RETIRADA', '1.0000', 'Incidencia de origen.', 'hojas en blanco',
                    motivo_retiro='Falla operativa por consumible agotado; no representa un riesgo de seguridad de la información.')],
        decision=('RECHAZADA', 'u3', 28, 'Falla operativa por consumible agotado; no representa un riesgo de seguridad de la información.'),
    )]),
    Risk(5, 8, [Version(
        1, 'Pérdida de información por falla en copias de respaldo', 8,
        'No se generó la copia de respaldo diaria del servidor de archivos.', 'Pérdida de datos', None,
        'Imposibilidad de restaurar información reciente', 'Servidor de archivos',
        links=[Link(14, 'SUGERIDA', '1.0000', 'Incidencia de origen. Sin coincidencias con otras incidencias.',
                    'no aparece la copia de respaldo')],
    )]),
]


class _Seeder:
    def __init__(self, stdout):
        self.stdout = stdout
        self.analistas = {k: Usuario.objects.get(correo=v) for k, v in ANALISTAS.items()}
        titulos = {spec.id: spec.titulo for spec in SEED_INCIDENTS}
        por_titulo = {i.titulo: i for i in Incidencia.objects.filter(titulo__in=titulos.values()).select_related('reportante')}
        self.incidencias = {n: por_titulo[t] for n, t in titulos.items() if t in por_titulo}
        self.matriz = ConfiguracionMatriz.objects.filter(activa=True).order_by('-creada_en', '-id').first()
        self.analisis: dict[int, AnalisisIncidencia] = {}

    def fragmento(self, doc: str, pagina: int):
        frag = FragmentoDocumento.objects.filter(
            version_documento__documento__codigo=DOCS[doc], pagina_inicio=pagina,
        ).order_by('orden').first()
        if frag is None:
            self.stdout.write(f'  ADVERTENCIA: sin fragmento {DOCS[doc]} p{pagina}; se omite la cita.')
        return frag

    def analisis_de(self, inc: int, version: Version) -> AnalisisIncidencia:
        if inc in self.analisis:
            return self.analisis[inc]
        incidencia = self.incidencias[inc]
        tarea = TareaIA.objects.filter(incidencia=incidencia, rama='ESTRATEGICA', estado='COMPLETADA').order_by('-intento').first()
        analisis = AnalisisIncidencia.objects.create(
            tarea=tarea, activo_identificado=version.activo_identificado,
            amenaza=version.amenaza or NO_DETERMINADO, vulnerabilidad=version.vulnerabilidad or NO_DETERMINADO,
            consecuencia=version.consecuencia or NO_DETERMINADO, riesgo_candidato=version.titulo,
        )
        AnalisisIncidencia.objects.filter(pk=analisis.pk).update(creado_en=incidencia.registrada_en)
        self.analisis[inc] = analisis
        return analisis

    def seed_risk(self, spec: Risk) -> Riesgo:
        riesgo = Riesgo.objects.create(codigo='RSG-PENDIENTE')
        riesgo.codigo = f'RSG-{riesgo.id:04d}'
        riesgo.save(update_fields=['codigo'])
        Riesgo.objects.filter(pk=riesgo.pk).update(creado_en=D(spec.creado))

        for v in spec.versiones:
            origen_inc = self.incidencias[v.links[0].inc]
            creador = self.analistas[v.creador] if v.creador else origen_inc.reportante
            decision_analista = self.analistas[v.decision[1]] if v.decision else None
            confirmada = v.activo_confirmado is not None
            version = VersionRiesgo.objects.create(
                riesgo=riesgo, numero=v.numero, origen=v.origen, creada_por=creador, titulo=v.titulo, descripcion=v.descripcion,
                amenaza=v.amenaza, vulnerabilidad=v.vulnerabilidad, consecuencia=v.consecuencia, recomendacion=v.recomendacion,
                origen_recomendacion=('NORMATIVA_INTERNA' if v.fuentes else v.origen) if v.recomendacion else None,
                activo_confirmado=Activo.objects.get(codigo=v.activo_confirmado) if confirmada else None,
                agrupacion_confirmada_por=decision_analista if confirmada else None,
                agrupacion_confirmada_en=D(v.decision[2]) if confirmada and v.decision else None,
            )
            VersionRiesgo.objects.filter(pk=version.pk).update(creada_en=D(v.creada))

            for numero, (doc, pagina) in enumerate(v.fuentes, start=1):
                fragmento = self.fragmento(doc, pagina)
                if fragmento:
                    CitaVersionRiesgo.objects.create(version=version, numero=numero, fragmento=fragmento)

            for link in v.links:
                revisor = decision_analista if link.estado in ('CONFIRMADA', 'RETIRADA') else None
                VersionIncidencia.objects.create(
                    version=version, analisis=self.analisis_de(link.inc, v), estado=link.estado,
                    similitud=Decimal(link.similitud), motivo_similitud=link.motivo, extracto_reporte=link.extracto,
                    revisada_por=revisor, revisada_en=D(v.decision[2]) if revisor else None, motivo_retiro=link.motivo_retiro,
                )

            if v.evaluacion:
                p, i, justificacion, analista, dias = v.evaluacion
                celda = CeldaMatriz.objects.get(matriz=self.matriz, probabilidad=p, impacto=i)
                evaluacion = EvaluacionRiesgo.objects.create(
                    version=version, celda=celda, evaluador=self.analistas[analista], justificacion=justificacion,
                )
                EvaluacionRiesgo.objects.filter(pk=evaluacion.pk).update(evaluada_en=D(dias))
            if v.decision:
                accion, analista, dias, observacion = v.decision
                decision = DecisionRiesgo.objects.create(
                    version=version, accion=accion, analista=self.analistas[analista], observacion=observacion,
                )
                DecisionRiesgo.objects.filter(pk=decision.pk).update(decidida_en=D(dias))
        return riesgo


def seed_risks(stdout) -> None:
    if Riesgo.objects.exists():
        stdout.write(f'  RIESGO existentes conservados ({Riesgo.objects.count()})')
        return
    seeder = _Seeder(stdout)
    faltantes = {link.inc for r in SEED_RISKS for v in r.versiones for link in v.links} - set(seeder.incidencias)
    if faltantes or seeder.matriz is None:
        stdout.write(f'  ADVERTENCIA: no se siembran riesgos (incidencias semilla faltantes: {sorted(faltantes)} '
                     f'o sin matriz activa).')
        return
    riesgos = [seeder.seed_risk(spec) for spec in SEED_RISKS]
    stdout.write(
        f'  RIESGO: {len(riesgos)} ({riesgos[0].codigo}..{riesgos[-1].codigo}) | VERSION_RIESGO: '
        f'{VersionRiesgo.objects.filter(riesgo__in=riesgos).count()} | ANALISIS_INCIDENCIA: {len(seeder.analisis)} | '
        f'CITA_VERSION_RIESGO: {CitaVersionRiesgo.objects.filter(version__riesgo__in=riesgos).count()}'
    )
