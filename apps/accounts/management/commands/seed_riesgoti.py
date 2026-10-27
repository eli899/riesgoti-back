from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Permiso, Rol, RolPermiso, Usuario
from apps.accounts.rbac import SOD_RISK_PERMISSIONS, CodigoPermiso, RolCodigo
from apps.ai_config.constants import ProveedorEmbedding, ProveedorLlm
from apps.ai_config.models import ConfiguracionIARAG
from apps.assets_matrix.models import (
    Activo,
    CeldaMatriz,
    ConfiguracionMatriz,
    CriterioImpacto,
    CriterioProbabilidad,
    NivelRiesgo,
    TipoActivo,
)
from apps.documents_rag.seed_documents import seed_documents
from apps.incidents.seed_incidents import seed_incidents
from apps.risks.seed_risks import seed_risks

SEED_PASSWORD = 'RiesgoTI2026!'

ROLES = [
    (RolCodigo.REPORTANTE, 'Reportante'),
    (RolCodigo.ANALISTA, 'Analista'),
    (RolCodigo.ADMIN, 'Administrador'),
]

PERMISOS = [
    (CodigoPermiso.INCIDENCIA_CREAR, 'Registrar nuevas incidencias'),
    (CodigoPermiso.INCIDENCIA_VER_PROPIAS, 'Consultar las incidencias reportadas por el propio usuario'),
    (CodigoPermiso.INCIDENCIA_VER_TODAS, 'Consultar todas las incidencias'),
    (CodigoPermiso.INCIDENCIA_CERRAR_PROPIAS_POR_FEEDBACK, 'Cerrar incidencias propias al confirmar que la orientación funcionó'),
    (CodigoPermiso.ATENCION_VER_COLA, 'Consultar la cola de atención humana (N2)'),
    (CodigoPermiso.ATENCION_ATENDER, 'Atender incidencias derivadas a N2'),
    (CodigoPermiso.RIESGO_REVISAR_AGRUPACION, 'Revisar agrupaciones de incidencias en versiones de riesgo'),
    (CodigoPermiso.RIESGO_EVALUAR, 'Evaluar riesgos en la matriz 5x5'),
    (CodigoPermiso.RIESGO_VALIDAR, 'Emitir decisiones sobre versiones de riesgo'),
    (CodigoPermiso.RIESGO_CONSULTAR, 'Consultar riesgos y tablero de indicadores'),
    (CodigoPermiso.ACTIVO_ADMINISTRAR, 'Administrar el catálogo de activos'),
    (CodigoPermiso.DOCUMENTO_ADMINISTRAR, 'Administrar y autorizar documentos normativos'),
    (CodigoPermiso.MATRIZ_ADMINISTRAR, 'Administrar la configuración de la matriz de riesgo'),
    (CodigoPermiso.USUARIO_ADMINISTRAR, 'Administrar usuarios'),
    (CodigoPermiso.ROL_ADMINISTRAR, 'Administrar roles y permisos'),
]

# Segregación de Funciones (ISO/IEC 27001): ADMIN jamás recibe permisos de evaluación/decisión de riesgos.
PERMISOS_PROHIBIDOS_ADMIN = SOD_RISK_PERMISSIONS

ROL_PERMISOS = {
    RolCodigo.REPORTANTE: [CodigoPermiso.INCIDENCIA_CREAR, CodigoPermiso.INCIDENCIA_VER_PROPIAS, CodigoPermiso.INCIDENCIA_CERRAR_PROPIAS_POR_FEEDBACK],
    RolCodigo.ANALISTA: [
        CodigoPermiso.INCIDENCIA_VER_PROPIAS, CodigoPermiso.INCIDENCIA_VER_TODAS, CodigoPermiso.ATENCION_VER_COLA, CodigoPermiso.ATENCION_ATENDER,
        CodigoPermiso.RIESGO_REVISAR_AGRUPACION, CodigoPermiso.RIESGO_EVALUAR, CodigoPermiso.RIESGO_VALIDAR, CodigoPermiso.RIESGO_CONSULTAR,
    ],
    RolCodigo.ADMIN: [
        CodigoPermiso.INCIDENCIA_VER_PROPIAS, CodigoPermiso.INCIDENCIA_VER_TODAS, CodigoPermiso.RIESGO_CONSULTAR, CodigoPermiso.ACTIVO_ADMINISTRAR,
        CodigoPermiso.DOCUMENTO_ADMINISTRAR, CodigoPermiso.MATRIZ_ADMINISTRAR, CodigoPermiso.USUARIO_ADMINISTRAR, CodigoPermiso.ROL_ADMINISTRAR,
    ],
}

USUARIOS = [
    ('lucia.ramirez@empresa.pe', 'Lucía', 'Ramírez', RolCodigo.REPORTANTE),
    ('jorge.salas@empresa.pe', 'Jorge', 'Salas', RolCodigo.REPORTANTE),
    ('andrea.quispe@empresa.pe', 'Andrea', 'Quispe', RolCodigo.ANALISTA),
    ('martin.torres@empresa.pe', 'Martín', 'Torres', RolCodigo.ANALISTA),
    ('carla.mendoza@empresa.pe', 'Carla', 'Mendoza', RolCodigo.ADMIN),
    ('diego.vargas@empresa.pe', 'Diego', 'Vargas', RolCodigo.ADMIN),
]

TIPOS_ACTIVO = ['Aplicación', 'Servicio', 'Infraestructura de red', 'Equipo', 'Servidor', 'Estación de trabajo']

ACTIVOS = [
    ('ACT-001', 'ERP Contable', 'Aplicación', 4, True),
    ('ACT-002', 'Correo corporativo', 'Servicio', 3, True),
    ('ACT-003', 'VPN corporativa', 'Infraestructura de red', 3, True),
    ('ACT-004', 'Impresora multifunción piso 3', 'Equipo', 1, True),
    ('ACT-005', 'Servidor de archivos', 'Servidor', 3, True),
    ('ACT-006', 'Laptop asignada', 'Estación de trabajo', 2, True),
    ('ACT-007', 'Intranet antigua', 'Aplicación', 2, False),
]

NIVELES = [('BAJO', 1), ('MEDIO', 2), ('ALTO', 3), ('CRITICO', 4)]

CRITERIOS_PROBABILIDAD = {1: 'Rara', 2: 'Improbable', 3: 'Posible', 4: 'Probable', 5: 'Casi segura'}
CRITERIOS_IMPACTO = {1: 'Insignificante', 2: 'Menor', 3: 'Moderado', 4: 'Mayor', 5: 'Severo'}


def nivel_por_score(score: int) -> str:
    if score >= 15:
        return 'CRITICO'
    if score >= 9:
        return 'ALTO'
    if score >= 4:
        return 'MEDIO'
    return 'BAJO'


class Command(BaseCommand):
    help = 'Puebla de forma idempotente los catálogos base, usuarios semilla, matriz 5x5 y configuración IA/RAG de RiesgoTI.'

    @transaction.atomic
    def handle(self, *args, **options):
        roles = self._seed_roles_y_permisos()
        usuarios = self._seed_usuarios(roles)
        self._seed_activos()
        admin = usuarios['carla.mendoza@empresa.pe']
        self._seed_matriz(admin)
        self._seed_configuracion_ia(admin)
        # Documentos d1..d6: PDFs generados y procesados con el pipeline real (PyMuPDF4LLM -> chunks -> FAISS).
        seed_documents(admin, self.stdout)
        # Incidencias 1..17 del prototipo con historial, orientación, feedback y atención N2.
        seed_incidents(self.stdout)
        # Riesgos RSG-0001..0005 del prototipo con versiones, citas, vínculos, evaluaciones y decisiones.
        seed_risks(self.stdout)
        self.stdout.write(self.style.SUCCESS('Semillas de RiesgoTI aplicadas correctamente.'))

    def _seed_roles_y_permisos(self):
        roles = {
            codigo: Rol.objects.update_or_create(codigo=codigo, defaults={'nombre': nombre, 'activo': True})[0]
            for codigo, nombre in ROLES
        }
        permisos = {
            codigo: Permiso.objects.update_or_create(codigo=codigo, defaults={'descripcion': descripcion, 'activo': True})[0]
            for codigo, descripcion in PERMISOS
        }

        prohibidos = PERMISOS_PROHIBIDOS_ADMIN.intersection(ROL_PERMISOS[RolCodigo.ADMIN])
        if prohibidos:
            raise RuntimeError(f'Violación de SoD: ADMIN no puede recibir {sorted(prohibidos)}')

        for rol_codigo, permiso_codigos in ROL_PERMISOS.items():
            rol = roles[rol_codigo]
            for permiso_codigo in permiso_codigos:
                RolPermiso.objects.get_or_create(rol=rol, permiso=permisos[permiso_codigo])
            # Retira asignaciones que ya no forman parte de la definición (p. ej. corrige SoD).
            RolPermiso.objects.filter(rol=rol).exclude(permiso__codigo__in=permiso_codigos).delete()

        self.stdout.write(f'  ROL: {len(roles)} | PERMISO: {len(permisos)} | ROL_PERMISO: {RolPermiso.objects.count()}')
        return roles

    def _seed_usuarios(self, roles):
        usuarios = {}
        for correo, nombres, apellidos, rol_codigo in USUARIOS:
            usuario = Usuario.objects.filter(correo=correo).first()
            if usuario is None:
                usuario = Usuario.objects.create_user(
                    correo=correo, nombres=nombres, apellidos=apellidos, rol=roles[rol_codigo], password=SEED_PASSWORD,
                )
            else:
                usuario.nombres, usuario.apellidos, usuario.rol, usuario.activo = nombres, apellidos, roles[rol_codigo], True
                usuario.save(update_fields=['nombres', 'apellidos', 'rol', 'activo', 'ultima_modificacion'])
            usuarios[correo] = usuario
        self.stdout.write(f'  USUARIO: {len(usuarios)}')
        return usuarios

    def _seed_activos(self):
        tipos = {
            nombre: TipoActivo.objects.update_or_create(nombre=nombre, defaults={'activo': True})[0]
            for nombre in TIPOS_ACTIVO
        }
        for codigo, nombre, tipo, criticidad, activo in ACTIVOS:
            Activo.objects.update_or_create(
                codigo=codigo,
                defaults={'nombre': nombre, 'tipo': tipos[tipo], 'criticidad': criticidad, 'activo': activo},
            )
        self.stdout.write(f'  TIPO_ACTIVO: {len(tipos)} | ACTIVO: {len(ACTIVOS)}')

    def _seed_matriz(self, admin):
        niveles = {
            codigo: NivelRiesgo.objects.update_or_create(codigo=codigo, defaults={'orden': orden})[0]
            for codigo, orden in NIVELES
        }
        # INV-04: una matriz publicada es inmutable y su activación la gobierna POST /admin/matrices/publish/.
        # La matriz semilla solo se crea sobre una base sin matrices; nunca se reactiva ni se reescribe.
        if ConfiguracionMatriz.objects.exists():
            activa = ConfiguracionMatriz.objects.filter(activa=True).order_by('-creada_en', '-id').first()
            self.stdout.write(
                f'  NIVEL_RIESGO: {len(niveles)} | CONFIGURACION_MATRIZ existente conservada '
                f'(activa: {activa.version if activa else "ninguna"})'
            )
            return

        matriz = ConfiguracionMatriz.objects.create(
            nombre='Matriz corporativa ISO 27005',
            version='v1.0',
            estado='PUBLICADA',
            activa=True,
            creada_por=admin,
        )
        for valor, nombre in CRITERIOS_PROBABILIDAD.items():
            CriterioProbabilidad.objects.create(matriz=matriz, valor=valor, nombre=nombre)
        for valor, nombre in CRITERIOS_IMPACTO.items():
            CriterioImpacto.objects.create(matriz=matriz, valor=valor, nombre=nombre)
        CeldaMatriz.objects.bulk_create([
            CeldaMatriz(
                matriz=matriz,
                probabilidad=probabilidad,
                impacto=impacto,
                nivel=niveles[nivel_por_score(probabilidad * impacto)],
            )
            for probabilidad in range(1, 6)
            for impacto in range(1, 6)
        ])
        self.stdout.write(f'  NIVEL_RIESGO: {len(niveles)} | CELDA_MATRIZ: {matriz.celdas.count()}')

    def _seed_configuracion_ia(self, admin):
        # El versionado de CONFIGURACION_IA_RAG lo gobierna PUT /admin/ai-config/: la semilla solo
        # se crea sobre una base sin configuraciones para no duplicar la versión activa.
        if ConfiguracionIARAG.objects.exists():
            activa = ConfiguracionIARAG.objects.filter(activa=True).order_by('-creado_en', '-id').first()
            self.stdout.write(
                f'  CONFIGURACION_IA_RAG existente conservada '
                f'(activa: {activa.version_configuracion if activa else "ninguna"})'
            )
            return

        ConfiguracionIARAG.objects.create(
            version_configuracion='v1.0-default',
            proveedor_llm=ProveedorLlm.GEMINI,
            modelo_llm='gemini-2.5-flash',
            proveedor_embedding=ProveedorEmbedding.SENTENCE_TRANSFORMERS,
            modelo_embedding='sentence-transformers/paraphrase-multilingual-mpnet-base-v2',
            chunk_size=800,
            chunk_overlap=120,
            top_k=4,
            umbral_similitud=Decimal('0.400'),
            activa=True,
            actualizada_por=admin,
        )
        self.stdout.write('  CONFIGURACION_IA_RAG: v1.0-default')
