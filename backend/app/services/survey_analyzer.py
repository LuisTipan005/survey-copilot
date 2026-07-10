import os
import time
import logging
import json
import re
import difflib
from app.config import settings
from app.models import SurveyAnalyzeRequest, SurveyAnalyzeResponse, GeneratedAnswer, QuestionType
from app.services.llm_service import llm_service
from app.services.rag_service import rag_service
from app.services.context_assembler import context_assembler
from app.services.prompt_engine import prompt_engine
from app.services.answer_matcher import answer_matcher

logger = logging.getLogger(__name__)

class SurveyAnalyzer:
    def __init__(self):
        pass

    def _determine_doc_type_filter(self, question_text: str, question_type: QuestionType) -> str | None:
        """
        [Fase 2] Determina dinámicamente si la pregunta busca fundamentos
        técnicos o de opinión para filtrar en ChromaDB.
        """
        text_lower = question_text.lower()
        
        # Indicadores para buscar en apuntes personales/opiniones
        opinion_indicators = ["opin", "cree", "piensa", "considera", "prefer", "gust", "experiencia", "voto"]
        if any(ind in text_lower for ind in opinion_indicators):
            return "opinion"
            
        # Indicadores para exámenes puramente teóricos o prácticos
        technical_indicators = [
            "configur", "protocol", "comand", "interfaz", "vlan", "router", 
            "switch", "ip", "base de datos", "código", "algoritmo", "clase", "patrón"
        ]
        if any(ind in text_lower for ind in technical_indicators) or question_type in [QuestionType.SINGLE_CHOICE, QuestionType.DROPDOWN]:
            return "technical"
            
        return None

    # ─── JSON Extraction & Repair ────────────────────────────────

    @staticmethod
    def _extract_json_block(raw_text: str) -> str | None:
        """
        Bracket-balanced JSON extraction.
        
        Finds the first '{' and tracks nesting depth to find the matching '}'.
        This is much more reliable than greedy regex when the LLM adds
        conversational text or multiple JSON-like fragments.
        """
        if not raw_text:
            return None
        
        start = raw_text.find('{')
        if start == -1:
            return None
        
        depth = 0
        in_string = False
        escape_next = False
        
        for i in range(start, len(raw_text)):
            char = raw_text[i]
            
            if escape_next:
                escape_next = False
                continue
            
            if char == '\\':
                escape_next = True
                continue
            
            if char == '"':
                in_string = not in_string
                continue
            
            if in_string:
                continue
            
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    return raw_text[start:i + 1]
        
        # Unbalanced — try to salvage by appending closing braces
        if depth > 0:
            return raw_text[start:] + ('}' * depth)
        
        return None

    @staticmethod
    def _repair_json(json_str: str) -> str:
        """
        Fix common LLM JSON errors before json.loads:
        1. Single quotes → double quotes (outside of already-double-quoted strings)
        2. Trailing commas before } or ]
        3. Unquoted string values after colons
        4. Remove markdown code fence markers
        """
        if not json_str:
            return json_str
        
        # Remove markdown code fences: ```json ... ``` or ``` ... ```
        json_str = re.sub(r'```(?:json)?\s*', '', json_str)
        
        # Replace single quotes with double quotes (naive but effective for LLM output)
        # Only do this if there are no double quotes (to avoid corrupting valid JSON)
        if '"' not in json_str and "'" in json_str:
            json_str = json_str.replace("'", '"')
        
        # Remove trailing commas: ,} or ,]
        json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
        
        # Remove any BOM or zero-width chars
        json_str = json_str.replace('\ufeff', '').replace('\u200b', '')
        
        return json_str.strip()

    # ─── Defensive Fuzzy Fallback ─────────────────────────────────

    @staticmethod
    def _fuzzy_match_options(raw_selected: list[str], options: list[str], cutoff: float = 0.2) -> list[int]:
        """
        Last-resort fallback using difflib.get_close_matches with a permissive
        cutoff threshold. Maps LLM string responses back to the actual HTML
        element indices from the question options payload.
        
        Cloud models (70B+) may paraphrase more aggressively than local models,
        so a low cutoff (0.2) ensures we still match despite heavy rephrasing.
        
        Args:
            raw_selected: List of text strings returned by the LLM.
            options: List of original option texts from the HTML form.
            cutoff: Minimum similarity ratio (0.0–1.0). Lower = more permissive.
            
        Returns:
            List of matched option indices.
        """
        if not raw_selected or not options:
            return []
        
        # Normalize options for comparison
        normalized_options = [opt.strip().lower() for opt in options]
        matched_indices = []
        
        for llm_text in raw_selected:
            normalized_llm = llm_text.strip().lower()
            
            # Use difflib.get_close_matches against the normalized option list
            close = difflib.get_close_matches(
                normalized_llm,
                normalized_options,
                n=1,
                cutoff=cutoff,
            )
            
            if close:
                # Find the index of the matched option
                idx = normalized_options.index(close[0])
                if idx not in matched_indices:
                    matched_indices.append(idx)
                    logger.info(
                        f"Fuzzy fallback matched '{llm_text[:60]}...' → "
                        f"option[{idx}] (similarity with '{options[idx][:60]}...')"
                    )
            else:
                logger.warning(
                    f"Fuzzy fallback: no match for '{llm_text[:80]}...' "
                    f"(cutoff={cutoff})"
                )
        
        return matched_indices

    # ─── Main Analysis Pipeline ──────────────────────────────────

    async def analyze(self, request: SurveyAnalyzeRequest) -> SurveyAnalyzeResponse:
        start_time = time.time()
        generated_answers = []
        
        # Check for Context: scan data/documents/ folder
        UPLOAD_DIR = "data/documents"
        has_pdfs = False
        if os.path.exists(UPLOAD_DIR) and any(f.endswith(".pdf") for f in os.listdir(UPLOAD_DIR)):
            has_pdfs = True

        for question in request.questions:
            logger.info(f"Procesando pregunta con RAG Profundo: {question.question_text}")
            
            # 1. Clasificación heurística del contexto de la pregunta
            doc_type_filter = self._determine_doc_type_filter(question.question_text, question.question_type)
            
            chunks = []
            rag_context = None
            context_used = False
            context_sources = []
            
            if has_pdfs:
                # 2. Pipeline de Recuperación Híbrida (Vectores + Keywords)
                chunks = await rag_service.query_hybrid(
                    question=question.question_text,
                    n_results=4,
                    doc_type_filter=doc_type_filter
                )
                
                # 3. Ensamblado Estructurado del Contexto (Límite estricto de caracteres)
                rag_context = context_assembler.assemble(chunks, question.question_text)
                context_used = rag_context is not None
                
                # Extraer las fuentes únicas en formato de lista para el payload de respuesta
                if chunks:
                    context_sources = list(set([c.metadata.get("filename", "Desconocido") for c in chunks]))
            else:
                logger.info("Directorio de documentos vacío o sin PDFs. Omitiendo RAG (Bypass).")

            # 4. Construcción del Grounded Prompt
            payload = prompt_engine.build_payload(
                question=question,
                user_profile=request.user_profile,
                rag_context=rag_context
            )

            # 5. Pipeline de Generación con OpenRouter
            answer_text = ""
            confidence = 0.60  # Baseline por defecto sin contexto
            reasoning = "Respuesta inferida mediante conocimiento general del modelo."
            selected_options = None

            try:
                if payload["format_json"]:
                    response_raw = await llm_service.generate_response(
                        prompt=payload["prompt"],
                        system_prompt=payload["system_prompt"],
                        require_json=True,  # Enables OpenRouter's native JSON structured output
                    )
                    
                    # Guard against None response (API connection error)
                    if response_raw is None:
                        logger.error("LLM returned None — connection failed or timeout.")
                        raise ValueError("El LLM no respondió (None).")
                    
                    logger.info(f"[DIAG] LLM raw response ({len(response_raw)} chars): {response_raw[:300]}")
                    
                    # --- BRACKET-BALANCED JSON EXTRACTION + REPAIR ---
                    json_block = self._extract_json_block(response_raw)
                    
                    if not json_block:
                        logger.error(f"LLM no devolvió JSON. Raw: {response_raw}")
                        raise ValueError("El modelo no generó un JSON válido.")
                    
                    # Attempt parse, repair on failure
                    data = None
                    try:
                        data = json.loads(json_block)
                    except json.JSONDecodeError:
                        logger.warning("JSON parse failed, attempting repair...")
                        repaired = self._repair_json(json_block)
                        try:
                            data = json.loads(repaired)
                            logger.info("JSON repair succeeded.")
                        except json.JSONDecodeError as e2:
                            logger.error(f"JSON repair also failed: {e2}. Repaired text: {repaired}")
                            raise ValueError(f"JSON irrecuperable: {e2}")
                    
                    logger.info(f"[DIAG] Parsed JSON keys: {list(data.keys())}")
                    
                    raw_selected = data.get("selected", [])
                    reasoning = data.get("reasoning", "Opción determinada por el motor de inferencia.")
                    
                    logger.info(f"[DIAG] raw_selected = {raw_selected}")
                    logger.info(f"[DIAG] question.options = {question.options}")
                    
                    selected_options = []
                    
                    # STRATEGY: Map LLM text answers to indices using the 3-tier matcher
                    if isinstance(raw_selected, list) and len(raw_selected) > 0 and isinstance(raw_selected[0], str):
                        logger.info(f"[DIAG] Using text matcher: {len(raw_selected)} items to match against {len(question.options) if question.options else 0} options")
                        selected_options = answer_matcher.match_many(raw_selected, question.options)
                        
                        # Defensive fallback: if the 3-tier matcher failed to match anything,
                        # try a permissive difflib fuzzy match (cutoff=0.2) as a last resort.
                        # Cloud models (70B+) may paraphrase more aggressively than local ones.
                        if not selected_options and question.options:
                            logger.warning("3-tier matcher returned empty — trying fuzzy fallback (cutoff=0.2)...")
                            selected_options = self._fuzzy_match_options(
                                raw_selected, question.options, cutoff=0.2
                            )
                    
                    # Fallback: if the LLM returned integer indices directly
                    elif isinstance(raw_selected, list):
                        logger.info(f"[DIAG] Using integer fallback for raw_selected: {raw_selected}")
                        selected_options = [int(x) for x in raw_selected if str(x).isdigit() or isinstance(x, int)]
                    
                    logger.info(f"[DIAG] Final selected_options = {selected_options}")
                    
                    # --- Review Mode Visual Block ---
                    print("\n=========================")
                    q_text_trunc = question.question_text[:80] + ("..." if len(question.question_text) > 80 else "")
                    print(f"🧠 {q_text_trunc}")
                    
                    if selected_options and question.options:
                        matched_texts = []
                        for idx in selected_options:
                            if 0 <= idx < len(question.options):
                                matched_texts.append(question.options[idx])
                        
                        if matched_texts:
                            print(f"✅ {' | '.join(matched_texts)}")
                        else:
                            print("❌ No match found (indices out of bounds)")
                    else:
                        print("❌ No match found for this question")
                    print("=========================\n")
                    
                    # Safety: warn if nothing matched
                    if not selected_options:
                        logger.warning(
                            f"No options matched for question: '{question.question_text[:60]}...'. "
                            f"LLM returned: {raw_selected}. "
                            f"Available options: {question.options}"
                        )

                else:
                    # Respuesta fluida de texto para áreas extensas o cortas
                    answer_text = await llm_service.generate_response(
                        prompt=payload["prompt"],
                        system_prompt=payload["system_prompt"]
                    )
                    reasoning = "Texto redactado utilizando la base de conocimientos provista." if context_used else "Redactado bajo aproximación analítica general."

                # 6. Calibración del Scoring de Confianza (Grounded vs Fallback)
                if context_used and chunks:
                    top_score = chunks[0].score
                    # Si la correlación vectorial/keyword es robusta, incrementamos el peso
                    if top_score > 0.65:
                        confidence = min(0.95 + (top_score * 0.05), 1.0)
                    else:
                        confidence = 0.85
                else:
                    # Castigo leve de confianza al no poseer material oficial del usuario
                    confidence = 0.60

            except Exception as e:
                logger.error(f"Fallo crítico en pipeline de orquestación de la IA: {e}")
                answer_text = "Omitido automáticamente para evitar respuestas erróneas."
                confidence = 0.0

            # 7. Mapear al nuevo modelo extendido de la Fase 2
            generated_answers.append(GeneratedAnswer(
                question_text=question.question_text,
                answer=answer_text,
                confidence=round(confidence, 2),
                reasoning=reasoning,
                selected_options=selected_options,
                context_used=context_used,
                context_sources=context_sources if context_used else None
            ))

        processing_time_ms = (time.time() - start_time) * 1000

        return SurveyAnalyzeResponse(
            answers=generated_answers,
            model_used=settings.LLM_MODEL,
            processing_time_ms=round(processing_time_ms, 2)
        )

# Exportar singleton de la clase orquestadora
survey_analyzer = SurveyAnalyzer()