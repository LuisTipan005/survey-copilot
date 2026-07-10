import os
import re
import logging
import chromadb
from typing import List, Dict, Any, Optional
from app.config import settings
from app.models import DocumentSection, RetrievedChunk
from app.utils.pdf_loader import extract_structured_pdf

logger = logging.getLogger(__name__)

class SmartChunker:
    """Multi-strategy text chunking for optimal RAG retrieval."""
    
    CHUNK_SIZE = 800        
    CHUNK_OVERLAP = 150
    MIN_CHUNK_SIZE = 100    
    
    def chunk_document(self, full_text: str, sections: list[DocumentSection]) -> list[dict]:
        chunks = []
        for section in sections:
            section_chunks = self._chunk_section(section)
            chunks.extend(section_chunks)
        
        if not chunks:
            chunks = self._sliding_window_chunks(full_text)
        return chunks
    
    def _chunk_section(self, section: DocumentSection) -> list[dict]:
        content = section.content
        if len(content) <= self.CHUNK_SIZE:
            return [{
                "text": content,
                "metadata": {
                    "section_heading": section.heading,
                    "doc_type": section.doc_type,
                    "chunk_strategy": "section",
                    "parent_context": f"Sección: {section.heading}",
                    "position": "complete"
                }
            }]
        
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        chunks = []
        current_text = ""
        
        for i, para in enumerate(paragraphs):
            if len(current_text) + len(para) + 2 <= self.CHUNK_SIZE:
                current_text = f"{current_text}\n\n{para}" if current_text else para
            else:
                if current_text and len(current_text) >= self.MIN_CHUNK_SIZE:
                    position = "start" if not chunks else "middle"
                    chunks.append({
                        "text": current_text.strip(),
                        "metadata": {
                            "section_heading": section.heading,
                            "doc_type": section.doc_type,
                            "chunk_strategy": "paragraph",
                            "parent_context": f"Sección: {section.heading}",
                            "position": position
                        }
                    })
                current_text = para
        
        if current_text and len(current_text) >= self.MIN_CHUNK_SIZE:
            chunks.append({
                "text": current_text.strip(),
                "metadata": {
                    "section_heading": section.heading,
                    "doc_type": section.doc_type,
                    "chunk_strategy": "paragraph",
                    "parent_context": f"Sección: {section.heading}",
                    "position": "end" if chunks else "complete"
                }
            })
        return chunks
    
    def _sliding_window_chunks(self, text: str) -> list[dict]:
        chunks = []
        start = 0
        while start < len(text):
            end = start + self.CHUNK_SIZE
            chunk_text = text[start:end].strip()
            if chunk_text and len(chunk_text) >= self.MIN_CHUNK_SIZE:
                chunks.append({
                    "text": chunk_text,
                    "metadata": {
                        "section_heading": "General",
                        "doc_type": "other",
                        "chunk_strategy": "sliding_window",
                        "parent_context": "",
                        "position": "middle"
                    }
                })
            start += self.CHUNK_SIZE - self.CHUNK_OVERLAP
        return chunks

class RagService:
    def __init__(self):
        # Inicializar base de datos vectorial local
        db_path = getattr(settings, "CHROMA_DB_PATH", "./data/chroma_db")
        os.makedirs(db_path, exist_ok=True)
        self._client = chromadb.PersistentClient(path=db_path)
        # No embedding_function specified — ChromaDB uses its built-in
        # sentence-transformers/all-MiniLM-L6-v2 by default.
        # The sentence-transformers package must be installed.
        self._collection = self._client.get_or_create_collection(name="survey_docs")
        self.chunker = SmartChunker()
        self.is_ready = True

    async def ingest_document(self, file_path: str, doc_id: str, filename: str) -> bool:
        """Extrae, divide y vectoriza un PDF en ChromaDB."""
        try:
            logger.info(f"Ingestando documento: {filename}")
            md_text, sections = extract_structured_pdf(file_path)
            chunks = self.chunker.chunk_document(md_text, sections)
            
            texts = [c["text"] for c in chunks]
            chunk_ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
            
            # ChromaDB auto-embeds the documents using its default
            # sentence-transformers embedding function.
            # No manual embedding generation needed.
            self._collection.add(
                ids=chunk_ids,
                documents=texts,
                metadatas=[
                    {
                        "document_id": doc_id,
                        "filename": filename,
                        "chunk_index": i,
                        "section_heading": c["metadata"]["section_heading"],
                        "doc_type": c["metadata"]["doc_type"],
                        "chunk_strategy": c["metadata"]["chunk_strategy"],
                        "parent_context": c["metadata"]["parent_context"],
                        "position": c["metadata"]["position"],
                        "char_count": len(c["text"]),
                    }
                    for i, c in enumerate(chunks)
                ]
            )
            logger.info(f"Ingestión exitosa. {len(chunks)} fragmentos guardados.")
            return True
        except Exception as e:
            logger.error(f"Error ingestando documento: {e}")
            return False

    async def query_hybrid(self, question: str, n_results: int = 5, doc_type_filter: str | None = None) -> list[RetrievedChunk]:
        """Hybrid retrieval: semantic + keyword + metadata filtering."""
        if self._collection.count() == 0:
            return []
        
        where_filter = {"doc_type": doc_type_filter} if doc_type_filter else None
        
        # 1. Búsqueda semántica — ChromaDB auto-embeds the query text
        # using its default sentence-transformers embedding function.
        semantic_results = self._collection.query(
            query_texts=[question],
            n_results=min(n_results * 2, self._collection.count()),
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )
        
        # 2. Búsqueda por palabra clave exacta
        keywords = self._extract_keywords(question)
        keyword_results = None
        if keywords:
            keyword_results = self._collection.get(
                where_document={"$contains": keywords[0]},
                include=["documents", "metadatas"],
            )
        
        # 3. Mezclar y re-clasificar
        chunks = self._merge_and_rerank(semantic_results, keyword_results, n_results)
        return chunks

    def _extract_keywords(self, question: str) -> list[str]:
        """Extrae palabras clave ignorando las 'stop words' en español."""
        stop_words = {
            "el", "la", "los", "las", "un", "una", "de", "del", "en", "y", 
            "que", "es", "por", "con", "para", "como", "más", "al", "se",
            "su", "qué", "cómo", "cuál", "tu", "tus", "te", "ti", "nos",
            "lo", "le", "les", "no", "sí", "muy", "este", "esta", "esto",
        }
        words = re.findall(r'\b\w{3,}\b', question.lower())
        keywords = [w for w in words if w not in stop_words]
        return keywords[:3] 

    def _merge_and_rerank(self, semantic_results: dict, keyword_results: dict | None, n_results: int) -> list[RetrievedChunk]:
        """Combina y asigna puntajes a los fragmentos encontrados."""
        seen_ids = set()
        scored_chunks = []
        
        for i, (doc_list, meta_list, dist_list) in enumerate(zip(
            semantic_results.get("documents", [[]]),
            semantic_results.get("metadatas", [[]]),
            semantic_results.get("distances", [[]]),
        )):
            for doc, meta, dist in zip(doc_list, meta_list, dist_list):
                chunk_id = f"{meta.get('document_id')}_{meta.get('chunk_index')}"
                if chunk_id in seen_ids:
                    continue
                seen_ids.add(chunk_id)
                
                semantic_score = max(0, 1.0 - dist)
                type_boost = 0.1 if meta.get("doc_type") == "opinion" else 0.0
                
                scored_chunks.append(RetrievedChunk(
                    text=doc,
                    metadata=meta,
                    score=semantic_score + type_boost,
                    source="semantic",
                ))
        
        if keyword_results and keyword_results.get("ids"):
            for doc, meta in zip(
                keyword_results.get("documents", []),
                keyword_results.get("metadatas", []),
            ):
                chunk_id = f"{meta.get('document_id')}_{meta.get('chunk_index')}"
                if chunk_id in seen_ids:
                    for sc in scored_chunks:
                        if f"{sc.metadata.get('document_id')}_{sc.metadata.get('chunk_index')}" == chunk_id:
                            sc.score += 0.15  
                            sc.source = "hybrid"
                    continue
                seen_ids.add(chunk_id)
                
                scored_chunks.append(RetrievedChunk(
                    text=doc,
                    metadata=meta,
                    score=0.5,  
                    source="keyword",
                ))
        
        scored_chunks.sort(key=lambda c: c.score, reverse=True)
        return scored_chunks[:n_results]

# Exportar singleton
rag_service = RagService()