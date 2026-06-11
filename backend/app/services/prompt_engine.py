import re
from typing import Dict, Any
from app.models import DetectedQuestion, QuestionType

class PromptEngine:
    def __init__(self):
        # System prompt when RAG context IS available — strict, grounded
        self.grounded_system_prompt = (
            "You are an intelligent assistant answering a university quiz. "
            "You have access to excerpts from the student's personal study materials.\n\n"
            "CRITICAL RULES:\n"
            "1. Base your answers on the provided DOCUMENT CONTEXT when it is relevant.\n"
            "2. If the context contains the answer, use that information directly.\n"
            "3. IMPORTANTE: Si el contexto es la revisión de un examen de Moodle, IGNORA las opciones marcadas por el estudiante y busca SIEMPRE la frase 'La respuesta correcta es:' para extraer la verdad absoluta.\n"
            "4. If the context does NOT contain the answer, use your general knowledge to pick the best option.\n"
            "5. Always respond in Spanish.\n"
            "6. Do not mention you are an AI.\n"
            "7. You MUST always select at least one option. NEVER return an empty 'selected' list."
        )

        # System prompt when NO RAG context — fully permissive, use general knowledge
        self.fallback_system_prompt = (
            "You are an intelligent assistant answering a university quiz. "
            "No study materials are available, so use your general knowledge.\n\n"
            "CRITICAL RULES:\n"
            "1. Use your broad general knowledge to answer the question.\n"
            "2. Always pick the BEST option even if you are not 100% certain.\n"
            "3. Always respond in Spanish.\n"
            "4. Do not mention you are an AI.\n"
            "5. You MUST always select at least one option. NEVER return an empty 'selected' list.\n"
            "6. If unsure, make your best educated guess — an empty answer is NEVER acceptable."
        )

    def _strip_option_prefix(self, text: str) -> str:
        """Strip option letter prefixes (a. b) c: etc.) for consistency with JS side."""
        if not text:
            return text
        return re.sub(r'^[a-zA-Z0-9][.):\-]\s*', '', text).strip()

    def _format_options(self, options: list[str]) -> str:
        if not options:
            return ""
        # Strip any remaining prefixes and present options with clean index labels
        cleaned = [self._strip_option_prefix(opt) for opt in options]
        return "\n".join([f"[{i}] {opt}" for i, opt in enumerate(cleaned)])

    def build_payload(self, question: DetectedQuestion, user_profile: str, rag_context: str = None) -> Dict[str, Any]:
        """
        Construye el prompt evaluando si hay contexto recuperado (RAG) o no.
        Aplica un comportamiento híbrido: estricto con el contexto si existe, 
        pero permite usar conocimiento general (fallback) si el contexto no ayuda.
        """
        
        # --- SELECT SYSTEM PROMPT BASED ON CONTEXT AVAILABILITY ---
        if rag_context:
            system_prompt = self.grounded_system_prompt
            context_block = f"=== DOCUMENT CONTEXT ===\n{rag_context}\n=== END CONTEXT ===\n\n"
            behavior = "prioritizing the DOCUMENT CONTEXT above. If the context does not contain the exact answer, use your general knowledge to deduce the best answer"
        else:
            system_prompt = self.fallback_system_prompt
            context_block = ""
            behavior = "using your general knowledge. You MUST pick the best answer — do NOT leave 'selected' empty"

        prompt = ""
        format_json = False

        # --- MANDATORY SELECTION RULE (appended to all choice prompts) ---
        mandatory_rule = (
            "\n\nMANDATORY: The 'selected' list must contain at least one option. "
            "An empty list is NEVER valid. If you are unsure, pick the most likely answer."
        )

        if question.question_type == QuestionType.TEXT:
            prompt = (
                f"{context_block}"
                f"Question: {question.question_text}\n"
                f"Context from survey (if any): {question.context or 'None'}\n\n"
                f"Task: Write a direct, natural response {behavior}.\n"
                "CRITICAL RULES FOR TEXT ANSWERS:\n"
                "1. Answer ONLY the specific question asked. Do NOT add unrelated information.\n"
                "2. If the DOCUMENT CONTEXT is about a completely different subject than the question, IGNORE IT ENTIRELY and use general knowledge instead.\n"
                "3. Keep your answer concise and directly relevant to the question.\n"
                "4. Do not use prefixes like 'Answer:'.\n"
                "5. Do not generate lists of unrelated questions or examples."
            )
            format_json = False

        elif question.question_type in [QuestionType.SINGLE_CHOICE, QuestionType.DROPDOWN]:
            options_text = self._format_options(question.options)
            prompt = (
                f"{context_block}"
                f"Question: {question.question_text}\n"
                f"Options:\n{options_text}\n\n"
                f"Task: Select the single correct option {behavior}.\n"
                "CRITICAL: Respond ONLY with a valid JSON object. No intro text, no markdown format.\n"
                "The 'selected' field MUST be a list containing the EXACT STRING TEXT of the correct option, "
                "copied VERBATIM from the options above. Do NOT paraphrase, summarize, or shorten the text.\n\n"
                "CORRECT example:\n"
                '{"selected": ["Un dispositivo que determina la mejor ruta para reenviar paquetes"], "reasoning": "Brief explanation"}\n\n'
                "WRONG examples (DO NOT DO THIS):\n"
                '{"selected": ["Determina mejor ruta"], "reasoning": "..."} — WRONG: summarized instead of copying\n'
                '{"selected": [], "reasoning": "..."} — WRONG: empty list is NEVER allowed'
                f"{mandatory_rule}"
            )
            format_json = True

        elif question.question_type == QuestionType.MULTIPLE_CHOICE:
            options_text = self._format_options(question.options)
            prompt = (
                f"{context_block}"
                f"Question: {question.question_text}\n"
                f"Options:\n{options_text}\n\n"
                f"Task: Select the correct options {behavior}.\n"
                "CRITICAL: Respond ONLY with a valid JSON object. No intro text.\n"
                "The 'selected' field MUST be a list containing the EXACT STRING TEXT of the correct options, "
                "copied VERBATIM from the options above. Do NOT paraphrase, summarize, or shorten the text.\n\n"
                "CORRECT example:\n"
                '{"selected": ["Exact text of option 1", "Exact text of option 2"], "reasoning": "Brief explanation"}\n\n'
                "WRONG examples (DO NOT DO THIS):\n"
                '{"selected": ["Option 1 summary"], "reasoning": "..."} — WRONG: summarized instead of copying\n'
                '{"selected": [], "reasoning": "..."} — WRONG: empty list is NEVER allowed'
                f"{mandatory_rule}"
            )
            format_json = True

        return {
            "prompt": prompt,
            "system_prompt": system_prompt,
            "format_json": format_json
        }

prompt_engine = PromptEngine()