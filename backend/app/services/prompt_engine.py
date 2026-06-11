import random
from typing import Dict, Any
from app.models import DetectedQuestion, QuestionType

class PromptEngine:
    def __init__(self):
        # Fase 2: El contexto es la ley absoluta
        self.base_system_prompt = (
            "You are an intelligent assistant answering a university survey. "
            "You have access to excerpts from the student's personal study materials and notes.\n\n"
            "CRITICAL RULES:\n"
            "1. Base ALL your answers strictly on the provided DOCUMENT CONTEXT.\n"
            "2. If the context contains the answer, use that information directly.\n"
            "3. IMPORTANTE: Si el contexto es la revisión de un examen de Moodle, IGNORA las opciones marcadas por el estudiante y busca SIEMPRE la frase 'La respuesta correcta es:' para extraer la verdad absoluta.\n" # <-- ¡LA NUEVA REGLA MÁGICA!
            "4. If the context does NOT contain relevant information, provide a brief, logical answer but subtly indicate that you are inferring it.\n"
            "5. NEVER invent facts, definitions, or technical configurations not supported by the context.\n"
            "6. Always respond in Spanish.\n"
            "7. Do not mention you are an AI."
        )

    def _format_options(self, options: list[str]) -> str:
        if not options:
            return ""
        return "\n".join([f"[{i}] {opt}" for i, opt in enumerate(options)])

    def build_payload(self, question: DetectedQuestion, user_profile: str, rag_context: str = None) -> Dict[str, Any]:
        """
        Construye el prompt evaluando si hay contexto recuperado (RAG) o no.
        Aplica un comportamiento híbrido: estricto con el contexto si existe, 
        pero permite usar conocimiento general (fallback) si el contexto no ayuda.
        """
        system_prompt = self.base_system_prompt
        
        # --- LÓGICA DE COMPORTAMIENTO HÍBRIDO ---
        if rag_context:
            context_block = f"=== DOCUMENT CONTEXT ===\n{rag_context}\n=== END CONTEXT ===\n\n"
            behavior = "prioritizing the DOCUMENT CONTEXT. If the context does not contain the exact answer, act as an expert and deduce the correct technical answer"
        else:
            context_block = "No specific document context available for this question.\n\n"
            behavior = "using your general expert knowledge in Computer Science and Networking"

        prompt = ""
        format_json = False

        if question.question_type == QuestionType.TEXT:
            prompt = (
                f"{context_block}"
                f"Question: {question.question_text}\n"
                f"Context from survey (if any): {question.context or 'None'}\n\n"
                f"Task: Write a direct, natural response {behavior}. "
                "Do not use prefixes like 'Answer:'."
            )
            format_json = False

        elif question.question_type in [QuestionType.SINGLE_CHOICE, QuestionType.DROPDOWN]:
            options_text = self._format_options(question.options)
            prompt = (
                f"{context_block}"
                f"Question: {question.question_text}\n"
                f"Options:\n{options_text}\n\n"
                f"Task: Select the single correct option {behavior}.\n"
                "CRITICAL: Respond ONLY with a valid JSON object. No intro text, no markdown format. The 'selected' field MUST be a list containing the EXACT STRING TEXT of the correct option. Example:\n"
                '{"selected": ["Exact text of the correct option"], "reasoning": "Brief technical explanation"}'
            )
            format_json = True

        elif question.question_type == QuestionType.MULTIPLE_CHOICE:
            options_text = self._format_options(question.options)
            prompt = (
                f"{context_block}"
                f"Question: {question.question_text}\n"
                f"Options:\n{options_text}\n\n"
                f"Task: Select the correct options {behavior}.\n"
                "CRITICAL: Respond ONLY with a valid JSON object. No intro text. The 'selected' field MUST be a list containing the EXACT STRING TEXT of the correct options. Example:\n"
                '{"selected": ["Exact text of option 1", "Exact text of option 2"], "reasoning": "Brief technical explanation"}'
            )
            format_json = True

        return {
            "prompt": prompt,
            "system_prompt": system_prompt,
            "format_json": format_json
        }

prompt_engine = PromptEngine()