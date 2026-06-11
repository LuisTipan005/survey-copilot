import pymupdf4llm
import fitz
import re
import logging
from app.models import DocumentSection

logger = logging.getLogger(__name__)

def extract_structured_pdf(file_path: str) -> tuple[str, list[DocumentSection]]:
    """Extrae el texto Y la estructura de un PDF usando pymupdf4llm."""
    logger.info(f"Extrayendo estructura de: {file_path}")
    
    # Obtener markdown con estructura preservada
    md_text = pymupdf4llm.to_markdown(file_path)
    
    # Parsear en secciones lógicas
    sections = _parse_sections(md_text)
    
    # Clasificar el tipo de documento automáticamente
    for section in sections:
        section.doc_type = _classify_section(section.content)
    
    return md_text, sections

def _parse_sections(markdown: str) -> list[DocumentSection]:
    """Divide el markdown en secciones basándose en los encabezados (headings)."""
    lines = markdown.split('\n')
    sections = []
    current_heading = "Introducción"
    current_content = []
    current_level = 0
    
    for line in lines:
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading_match:
            # Guardar la sección anterior antes de empezar la nueva
            if current_content:
                sections.append(DocumentSection(
                    heading=current_heading,
                    content='\n'.join(current_content).strip(),
                    level=current_level,
                    page_numbers=[],
                    doc_type="other"
                ))
            current_heading = heading_match.group(2).strip()
            current_level = len(heading_match.group(1))
            current_content = []
        else:
            current_content.append(line)
    
    # No olvidar la última sección
    if current_content:
        sections.append(DocumentSection(
            heading=current_heading,
            content='\n'.join(current_content).strip(),
            level=current_level,
            page_numbers=[],
            doc_type="other"
        ))
    
    return [s for s in sections if s.content.strip()]

def _classify_section(content: str) -> str:
    """Clasifica el tipo de sección basándose en patrones de palabras clave."""
    content_lower = content.lower()
    
    opinion_words = ["creo que", "opino", "considero", "pienso que", 
                     "me parece", "en mi opinión", "prefiero", "me gusta"]
    if any(w in content_lower for w in opinion_words):
        return "opinion"
    
    technical_words = ["algoritmo", "función", "variable", "código",
                       "implementar", "framework", "api", "base de datos"]
    if any(w in content_lower for w in technical_words):
        return "technical"
    
    if content_lower.count("- ") > 3 or content_lower.count("* ") > 3:
        return "notes"
    
    if len(content) > 500:
        return "essay"
    
    return "other"