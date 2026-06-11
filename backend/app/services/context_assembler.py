import logging
from app.models import RetrievedChunk

logger = logging.getLogger(__name__)

class ContextAssembler:
    """Organiza los fragmentos recuperados en un contexto coherente para el LLM."""
    
    MAX_CONTEXT_CHARS = 3000  # Dejamos espacio para la pregunta y el system prompt
    
    def assemble(self, chunks: list[RetrievedChunk], question: str) -> str | None:
        """
        Construye un string de contexto estructurado a partir de los fragmentos.
        Agrupa por sección, ordena por relevancia y añade la fuente.
        """
        if not chunks:
            return None
        
        # Agrupar fragmentos por el título de la sección
        sections: dict[str, list[RetrievedChunk]] = {}
        for chunk in chunks:
            heading = chunk.metadata.get("section_heading", "General")
            sections.setdefault(heading, []).append(chunk)
        
        # Construir el string final con encabezados
        parts = []
        total_chars = 0
        
        for heading, section_chunks in sections.items():
            # Ordenar internamente por score de relevancia
            section_chunks.sort(key=lambda c: c.score, reverse=True)
            
            section_text = f"[Fuente: {heading}]\n"
            for chunk in section_chunks:
                candidate = section_text + chunk.text + "\n"
                if total_chars + len(candidate) > self.MAX_CONTEXT_CHARS:
                    break
                section_text = candidate
                total_chars += len(chunk.text)
            
            # Si se añadió texto real más allá del título
            if section_text.strip() != f"[Fuente: {heading}]":
                parts.append(section_text.strip())
        
        if not parts:
            return None
        
        return "\n\n---\n\n".join(parts)

# Singleton
context_assembler = ContextAssembler()