"""
Extracción PDF -> Markdown por página (PyMuPDF4LLM) y chunking jerárquico con trazabilidad de páginas.

Las páginas se concatenan intercalando marcadores `<<<RIESGOTI_PAGE:n>>>` que atraviesan el
MarkdownHeaderTextSplitter; dentro de cada sección se reconstruye el mapa offset -> página y el
RecursiveCharacterTextSplitter (add_start_index=True) permite calcular pagina_inicio = min(paginas)
y pagina_fin = max(paginas) a partir del texto real de cada fragmento, aunque cruce páginas.
"""
import re
from dataclasses import dataclass

import pymupdf4llm
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

SEGMENTATION_VERSION = 'md-v1'
# Los parámetros de CONFIGURACION_IA_RAG se expresan en tokens; se aproxima 1 token ~= 4 caracteres.
CHARS_PER_TOKEN = 4
MIN_TEXT_CHARS = 30

PAGE_MARKER = '<<<RIESGOTI_PAGE:{}>>>'
PAGE_MARKER_RE = re.compile(r'\s*<<<RIESGOTI_PAGE:(\d+)>>>\s*')


@dataclass(frozen=True)
class PageMarkdownChunk:
    orden: int
    pagina_inicio: int
    pagina_fin: int
    contenido: str


def build_segmentation_label(chunk_size: int, chunk_overlap: int) -> str:
    return f'{SEGMENTATION_VERSION}-cs{chunk_size}-co{chunk_overlap}'


def _version_label(version: str) -> str:
    return version if version.lower().startswith('v') else f'v{version}'


class StructuredMarkdownPDFChunker:
    HEADERS_TO_SPLIT_ON = [('#', 'H1'), ('##', 'H2'), ('###', 'H3')]

    @staticmethod
    def extract_pages(pdf_path: str) -> list[tuple[int, str]]:
        raw_pages = pymupdf4llm.to_markdown(pdf_path, page_chunks=True)
        pages = []
        for idx, page in enumerate(raw_pages or [], start=1):
            meta = page.get('metadata') or {}
            # pymupdf4llm >= 1.0 expone page_number (base 1); versiones previas usaban page.
            try:
                number = int(meta.get('page_number') or meta.get('page') or idx)
            except (TypeError, ValueError):
                number = idx
            pages.append((number if number >= 1 else idx, (page.get('text') or '').strip()))
        if not pages:
            raise ValueError('El archivo PDF no contiene páginas legibles.')
        return pages

    @classmethod
    def chunk_pages(
        cls,
        pages: list[tuple[int, str]],
        *,
        doc_codigo: str,
        doc_version: str,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
    ) -> list[PageMarkdownChunk]:
        if sum(len(text) for _, text in pages) < MIN_TEXT_CHARS:
            raise ValueError(
                'El PDF no posee capa de texto extraíble (posible documento escaneado sin OCR o archivo vacío).'
            )

        header_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=cls.HEADERS_TO_SPLIT_ON, strip_headers=False)
        char_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size * CHARS_PER_TOKEN,
            chunk_overlap=chunk_overlap * CHARS_PER_TOKEN,
            separators=['\n\n', '\n', ' ', ''],
            add_start_index=True,
        )

        document = '\n'.join(f'{PAGE_MARKER.format(number)}\n{text}' for number, text in pages if text)
        prefix_version = _version_label(doc_version)
        current_page = pages[0][0]
        results: list[PageMarkdownChunk] = []

        for section in header_splitter.split_text(document):
            meta = section.metadata or {}
            hierarchy = ' > '.join(meta[k] for k in ('H1', 'H2', 'H3') if meta.get(k)) or 'General'

            # re.split con grupo de captura -> [texto, página, texto, página, texto, ...]
            parts = PAGE_MARKER_RE.split(section.page_content)
            segments: list[tuple[int, str]] = []
            for position, part in enumerate(parts):
                if position % 2 == 1:
                    current_page = int(part)
                elif part.strip():
                    segments.append((current_page, part.strip()))
            if not segments:
                continue

            section_text, spans, cursor = '', [], 0
            for page_number, text in segments:
                if section_text:
                    section_text += '\n\n'
                    cursor += 2
                spans.append((cursor, cursor + len(text), page_number))
                section_text += text
                cursor += len(text)

            for piece in char_splitter.create_documents([section_text]):
                body = piece.page_content.strip()
                if not body:
                    continue
                start = piece.metadata.get('start_index', 0)
                end = start + len(piece.page_content)
                involved = {page for s, e, page in spans if s < end and e > start} or {spans[0][2]}
                results.append(PageMarkdownChunk(
                    orden=len(results) + 1,
                    pagina_inicio=min(involved),
                    pagina_fin=max(involved),
                    contenido=f'[Documento: {doc_codigo} {prefix_version} | Sección: {hierarchy}]\n{body}',
                ))

        if not results:
            raise ValueError('El PDF no produjo fragmentos de texto utilizables.')
        return results

    @classmethod
    def extract_and_chunk(
        cls,
        *,
        pdf_path: str,
        doc_codigo: str,
        doc_version: str,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
    ) -> list[PageMarkdownChunk]:
        return cls.chunk_pages(
            cls.extract_pages(pdf_path),
            doc_codigo=doc_codigo,
            doc_version=doc_version,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
