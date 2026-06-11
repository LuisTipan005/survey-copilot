import time
import logging
import json
import re  # <--- AÑADE ESTA LÍNEA AQUÍ ARRIBA
import difflib
from app.models import SurveyAnalyzeRequest, SurveyAnalyzeResponse, GeneratedAnswer, QuestionType
from app.services.ollama_service import ollama_service
from app.services.rag_service import rag_service
from app.services.context_assembler import context_assembler
from app.services.prompt_engine import prompt_engine

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
                        system_prompt=payload["system_prompt"]
                    )
                    
                    # --- EXTRACCIÓN AGRESIVA DE JSON (REGEX) ---
                    # Busca el primer bloque que empiece con { y termine con } sin importar qué haya antes o después
                    json_match = re.search(r'\{[\s\S]*\}', response_raw)
                    
                    if not json_match:
                        logger.error(f"LLM no devolvió JSON. Raw: {response_raw}")
                        raise ValueError("El modelo no generó un JSON válido.")
                        
                    clean_json = json_match.group(0)
                    data = json.loads(clean_json)
                    # -------------------------------------------
                    
                    raw_selected = data.get("selected", [])
                    reasoning = data.get("reasoning", "Opción determinada por el motor de inferencia.")
                    
                    raw_selected = data.get("selected", [])
                    reasoning = data.get("reasoning", "Opción determinada por el motor de inferencia.")
                    
                    selected_options = []
                    
                    # NUEVA ESTRATEGIA: Mapeo de texto a índice usando difflib
                    if isinstance(raw_selected, list) and len(raw_selected) > 0 and isinstance(raw_selected[0], str):
                        for text_ans in raw_selected:
                            # Comparamos el texto devuelto por Qwen con las opciones originales (precisión del 30% como mínimo)
                            matches = difflib.get_close_matches(text_ans, question.options, n=1, cutoff=0.3)
                            if matches:
                                idx = question.options.index(matches[0])
                                selected_options.append(idx)
                    
                    # Fallback de seguridad por si de todos modos devuelve un entero
                    elif isinstance(raw_selected, list):
                        selected_options = [int(x) for x in raw_selected if str(x).isdigit() or isinstance(x, int)]
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