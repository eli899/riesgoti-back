"""
Documentos semilla d1..d6 (prototipo figma/src/data.ts). Se generan PDFs reales con PyMuPDF cuyas páginas
coinciden con las citas del prototipo y se procesan con el pipeline productivo (PyMuPDF4LLM -> chunks -> FAISS).
"""
import math
from dataclasses import dataclass, field

import pymupdf
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.documents_rag.models import Documento
from apps.documents_rag.services import DocumentIngestionService

PAGE_WIDTH, PAGE_HEIGHT = 595, 842  # A4 en puntos
MARGIN = 64
HEADING_SIZES = {'h1': 20, 'h2': 15}
BODY_SIZE = 11

FILLER_TOPICS = [
    'gobierno y responsabilidades', 'alcance', 'definiciones', 'roles del personal', 'revisión periódica',
    'gestión de cambios', 'registros y evidencias', 'relación con proveedores', 'cumplimiento normativo',
    'indicadores de desempeño', 'excepciones autorizadas', 'capacitación', 'comunicación', 'mejora continua',
]


def build_pdf_bytes(pages: dict[int, list[tuple[str, str]]], total_pages: int) -> bytes:
    """pages: {número_de_página (base 1): [(tipo 'h1'|'h2'|'p', texto), ...]}. Páginas omitidas quedan en blanco."""
    doc = pymupdf.open()
    for number in range(1, total_pages + 1):
        page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        y = MARGIN
        for kind, text in pages.get(number, []):
            size = HEADING_SIZES.get(kind, BODY_SIZE)
            lines = max(1, math.ceil(len(text) * size * 0.5 / (PAGE_WIDTH - 2 * MARGIN))) + 1
            height = lines * size * 1.4
            page.insert_textbox(pymupdf.Rect(MARGIN, y, PAGE_WIDTH - MARGIN, y + height), text, fontsize=size, fontname='helv')
            y += height + 8
    data = doc.tobytes()
    doc.close()
    return data


@dataclass
class SeedDocument:
    key: str
    codigo: str
    titulo: str
    version: str
    finalidad: str
    estado: str  # AUTORIZADO | INACTIVA | PENDIENTE_AUTORIZACION | PROCESANDO | ERROR
    total_pages: int
    citas: dict[int, tuple[str, str]] = field(default_factory=dict)  # página -> (encabezado, texto)
    sin_texto: bool = False

    def pages(self) -> dict[int, list[tuple[str, str]]]:
        if self.sin_texto:
            return {}
        pages = {1: [('h1', self.titulo), ('p', f'Documento normativo {self.codigo} {self.version}. '
                                                f'Alineado con ISO/IEC 27001:2022 e ISO/IEC 27002:2022.')]}
        for number in range(2, self.total_pages + 1):
            if number in self.citas:
                heading, text = self.citas[number]
                if heading is None:
                    pages[number] = [('p', text)]  # Continuación de la sección de la página anterior.
                else:
                    pages[number] = [('h2', heading), ('p', text)]
            else:
                topic = FILLER_TOPICS[(number - 2) % len(FILLER_TOPICS)]
                pages[number] = [
                    ('h2', f'{number}. {topic.capitalize()}'),
                    ('p', f'Esta sección de {self.codigo} establece lineamientos de {topic} aplicables a los '
                          f'servicios de TI de la organización y a su sistema de gestión de seguridad de la información.'),
                ]
        return pages


SEED_DOCUMENTS = [
    SeedDocument(
        key='d1', codigo='POL-CONT-01', titulo='Política de continuidad de servicios TI', version='v2.1',
        finalidad='AMBAS', estado='AUTORIZADO', total_pages=16,
        citas={
            12: ('12. Monitoreo de capacidad', 'Los servicios críticos deben contar con monitoreo de capacidad y umbrales '
                 'de alerta que permitan anticipar degradaciones de rendimiento.'),
            14: ('14. Gestión de degradaciones recurrentes', 'Ante degradaciones recurrentes se debe realizar un análisis '
                 'de causa raíz'),
            15: (None, 'y planificar la ampliación de recursos o la redistribución de cargas.'),
        },
    ),
    SeedDocument(
        key='d2', codigo='PRO-ACC-01', titulo='Procedimiento de gestión de accesos y autenticación', version='v1.4',
        finalidad='AMBAS', estado='AUTORIZADO', total_pages=18,
        citas={
            7: ('7. Acceso remoto', 'El acceso remoto a la red corporativa requiere autenticación multifactor para todas '
                'las cuentas de usuario.'),
            9: ('9. Monitoreo de accesos', 'Los intentos de acceso desde ubicaciones no habituales deben generar alerta y '
                'revisión por el área de seguridad.'),
            18: ('18. Concienciación del personal', 'El personal debe recibir capacitación periódica sobre identificación '
                 'de correos de suplantación.'),
        },
    ),
    SeedDocument(
        key='d3', codigo='LIN-RESP-01', titulo='Lineamientos de copias de respaldo', version='v1.0',
        finalidad='OPERATIVA', estado='PENDIENTE_AUTORIZACION', total_pages=3,
        citas={3: ('3. Verificación de respaldos', 'Las copias diarias deben verificarse mediante restauraciones de prueba.')},
    ),
    SeedDocument(
        key='d4', codigo='MAN-EST-01', titulo='Manual de seguridad de estaciones de trabajo', version='v0.9',
        finalidad='OPERATIVA', estado='INACTIVA', total_pages=4,
        citas={4: ('4. Protección antimalware', 'Las estaciones deben mantener el antivirus corporativo actualizado.')},
    ),
    SeedDocument(
        key='d5', codigo='GUI-CLAS-01', titulo='Guía de clasificación de la información', version='v1.0',
        finalidad='ESTRATEGICA', estado='PROCESANDO', total_pages=2,
        citas={2: ('2. Niveles de clasificación', 'La información se clasifica en pública, interna, confidencial y restringida.')},
    ),
    SeedDocument(
        key='d6', codigo='PLN-INC-01', titulo='Plan de respuesta ante incidentes', version='v3.0',
        finalidad='AMBAS', estado='ERROR', total_pages=5, sin_texto=True,
    ),
]


def seed_documents(admin, stdout) -> None:
    resumen = []
    for seed in SEED_DOCUMENTS:
        if Documento.objects.filter(codigo=seed.codigo).exists():
            resumen.append(f'{seed.key}=existente')
            continue

        pdf = SimpleUploadedFile(f'{seed.codigo.lower()}.pdf', build_pdf_bytes(seed.pages(), seed.total_pages),
                                 content_type='application/pdf')
        version = DocumentIngestionService.upload(admin, {
            'codigo': seed.codigo, 'titulo': seed.titulo, 'descripcion': None,
            'version': seed.version, 'finalidad': seed.finalidad, 'archivo': pdf,
        }, enqueue=False)

        if seed.estado == 'PROCESANDO':
            DocumentIngestionService.enqueue_processing(version)  # Lo procesa celery_worker tras el commit.
            resumen.append(f'{seed.key}=PROCESANDO')
            continue

        result = DocumentIngestionService.process_version(version.id)
        if seed.estado == 'ERROR' or result['status'] != 'ok':
            if result['status'] != 'ok' and seed.estado != 'ERROR':
                stdout.write(f'  ADVERTENCIA {seed.codigo}: {result.get("error")}')
            resumen.append(f'{seed.key}=ERROR')
            continue

        if seed.estado in ('AUTORIZADO', 'INACTIVA'):
            version = DocumentIngestionService.authorize(admin, version)
        if seed.estado == 'INACTIVA':
            DocumentIngestionService.deactivate(admin, version)
        resumen.append(f'{seed.key}={seed.estado}({result["chunks"]} fragmentos)')

    stdout.write(f'  DOCUMENTO/VERSION_DOCUMENTO: {" | ".join(resumen)}')
