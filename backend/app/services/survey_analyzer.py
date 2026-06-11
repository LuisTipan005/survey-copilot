import time
import logging
import json
import re  # <--- AÑADE ESTA LÍNEA AQUÍ ARRIBA
from app.models import SurveyAnalyzeRequest, SurveyAnalyzeResponse, GeneratedAnswer, QuestionType
from app.services.ollama_service import ollama_service
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

    # ─── Main Analysis Pipeline ──────────────────────────────────

    async def analyze(self, request: SurveyAnalyzeRequest) -> SurveyAnalyzeResponse:
        start_time = time.time()
        generated_answers = []

        for question in request.questions:
            logger.info(f"Procesando pregunta con RAG Profundo: {question.question_text}")
            
            # 1. Clasificación heurística del contexto de la pregunta
            doc_type_filter = self._determine_doc_type_filter(question.question_text, question.question_type)
            
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
            context_sources = []
            if chunks:
                context_sources = list(set([c.metadata.get("filename", "Desconocido") for c in chunks]))

            # 4. Construcción del Grounded Prompt
            payload = prompt_engine.build_payload(
                question=question,
                user_profile=request.user_profile,
                rag_context=rag_context
            )

            # 5. Pipeline de Generación con Qwen 2.5
            answer_text = ""
            confidence = 0.60  # Baseline por defecto sin contexto
            reasoning = "Respuesta inferida mediante conocimiento general del modelo."
            selected_options = None

            try:
                if payload["format_json"]:
                    response_raw = await ollama_service.generate_response(
                        prompt=payload["prompt"],
                        system_prompt=payload["system_prompt"],
                        format_json=True  # <--- WIRED THROUGH: enables Ollama's JSON grammar constraint
                    )
                    
                    # Guard against None response (Ollama connection error)
                    if response_raw is None:
                        logger.error("Ollama returned None — connection failed or timeout.")
                        raise ValueError("Ollama no respondió (None).")
                    
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
                    
                    # Fallback: if the LLM returned integer indices directly
                    elif isinstance(raw_selected, list):
                        logger.info(f"[DIAG] Using integer fallback for raw_selected: {raw_selected}")
                        selected_options = [int(x) for x in raw_selected if str(x).isdigit() or isinstance(x, int)]
                    
                    logger.info(f"[DIAG] Final selected_options = {selected_options}")
                    
                    # Safety: warn if nothing matched
                    if not selected_options:
                        logger.warning(
                            f"No options matched for question: '{question.question_text[:60]}...'. "
                            f"LLM returned: {raw_selected}. "
                            f"Available options: {question.options}"
                        )

                else:
                    # Respuesta fluida de texto para áreas extensas o cortas
                    answer_text = await ollama_service.generate_response(
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
            model_used=prompt_engine.build_payload(request.questions[0], request.user_profile).get("model", "qwen2.5:7b"),
            processing_time_ms=round(processing_time_ms, 2)
        )

# Exportar singleton de la clase orquestadora
survey_analyzer = SurveyAnalyzer()