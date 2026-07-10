import re
from typing import Dict, Any
from app.models import DetectedQuestion, QuestionType

class PromptEngine:
    def __init__(self):
        # ── Core reasoning protocol shared by both system prompts ──────────────
        _REASONING_PROTOCOL = (
            "You are a specialized academic quiz-answering engine. "
            "You follow a strict thought process depending on the question type.\n\n"

            "══ THOUGHT PROCESS BY QUESTION TYPE ══\n\n"

            "1. SINGLE ANSWER (radio / single-choice)\n"
            "   - Read the base question and discard all noise.\n"
            "   - Assign a probability of accuracy to EACH provided option.\n"
            "   - Select the ONE option with the highest logical probability.\n"
            "   - Output: the EXACT text string of the winning option — zero variations.\n\n"

            "2. MULTIPLE SELECTION (checkboxes / multi-choice)\n"
            "   - Read the base question.\n"
            "   - Evaluate each option COMPLETELY INDEPENDENTLY against ground truth.\n"
            "   - Identify ALL statements that are technically correct.\n"
            "   - Output: an array with the EXACT text strings of all correct options.\n\n"

            "3. MATCHING (selectbox / dropdown)\n"
            "   - A large block of text is given. Go directly to the END of the instruction.\n"
            "   - Locate the SPECIFIC target item (usually marked with ' -> ' or at the very end).\n"
            "   - Determine which option from the dropdown corresponds EXCLUSIVELY to that target.\n"
            "   - Output: the EXACT text of the dropdown option (e.g., 'A', 'Tyler', 'Layer 3').\n"
            "   - NEVER fabricate text that is not in the provided options list.\n\n"

            "4. OPEN-ENDED (text / textarea / fill-in-the-blank)\n"
            "   - Identify if the question asks for a specific term, number, or short phrase.\n"
            "   - Synthesize the answer to its purest, most direct form.\n"
            "   - No greetings. Do not restate the question.\n"
            "   - Output: the answer directly (e.g., 'FTP Protocol', '192.168.1.1').\n\n"

            "══ IRONCLAD JSON OUTPUT RULE ══\n"
            "Your output MUST always be a valid JSON object: {\"selected\": [\"answer\"]}.\n"
            "NEVER return numeric indices unless the original option text IS literally a number.\n"
            "ALWAYS return the EXACT STRING from the options list. NEVER paraphrase or shorten.\n"
            "An empty 'selected' list is NEVER acceptable — always pick the best answer.\n"
        )

        # System prompt when RAG context IS available — strict, grounded
        self.grounded_system_prompt = (
            _REASONING_PROTOCOL +
            "\n══ CONTEXT RULES ══\n"
            "You have access to excerpts from the student's personal study materials.\n"
            "1. Base your answers on the provided DOCUMENT CONTEXT when it is relevant.\n"
            "2. If the context contains the answer, use that information directly.\n"
            "3. IMPORTANTE: Si el contexto es la revisión de un examen de Moodle, IGNORA las "
            "opciones marcadas por el estudiante y busca SIEMPRE la frase 'La respuesta correcta es:' "
            "para extraer la verdad absoluta.\n"
            "4. If the context does NOT contain the answer, fall back to your general knowledge.\n"
            "5. Always respond in Spanish. Do not mention you are an AI."
        )

        # System prompt when NO RAG context — fully permissive, use general knowledge
        self.fallback_system_prompt = (
            _REASONING_PROTOCOL +
            "\n══ CONTEXT RULES ══\n"
            "No study materials are available — use your broad general knowledge.\n"
            "1. Always pick the BEST option even if you are not 100% certain.\n"
            "2. If unsure, make your best educated guess — an empty answer is NEVER acceptable.\n"
            "3. Always respond in Spanish. Do not mention you are an AI."
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

        elif question.question_type == QuestionType.SINGLE_CHOICE:
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

        elif question.question_type == QuestionType.DROPDOWN:
            options_text = self._format_options(question.options)
            raw_options_list = ", ".join([f'"{o}"' for o in (question.options or [])])

            # Detect the Moodle matching pattern: "Main question -> specific target item"
            question_text = question.question_text
            is_matching = " -> " in question_text
            if is_matching:
                parts = question_text.rsplit(" -> ", 1)
                main_question = parts[0].strip()
                target_item = parts[1].strip()
                matching_guidance = (
                    f"\n\nMOODLE MATCHING QUESTION RULES:\n"
                    f"- The main question is: \"{main_question}\"\n"
                    f"- The SPECIFIC item you must match is: \"{target_item}\"\n"
                    f"- Your job is to select which option from the list below correctly corresponds to: \"{target_item}\"\n"
                    f"- The available options are: [{raw_options_list}]\n"
                    f"- You MUST return EXACTLY one of those option strings, verbatim. "
                    f"Do NOT return the target item text (\"{target_item}\") — that is NOT a valid option.\n"
                    f"- If the options are single letters (A, B, C...) or short labels, return the correct letter/label as-is."
                )
            else:
                matching_guidance = ""

            prompt = (
                f"{context_block}"
                f"Question: {question_text}\n"
                f"Options:\n{options_text}\n"
                f"{matching_guidance}\n\n"
                f"Task: Select the single correct option {behavior}.\n"
                "CRITICAL: Respond ONLY with a valid JSON object. No intro text, no markdown format.\n"
                "The 'selected' field MUST contain the EXACT STRING from the Options list above — "
                "copied VERBATIM. Do NOT invent text, do NOT return the question text, do NOT paraphrase.\n\n"
                "CORRECT example (if options were letters): "
                '{"selected": ["B"], "reasoning": "B matches because..."}\n'
                "CORRECT example (if options were phrases): "
                '{"selected": ["Exact phrase from the list"], "reasoning": "..."}\n\n'
                "WRONG examples (DO NOT DO THIS):\n"
                '{"selected": ["1"], "reasoning": "..."} — WRONG: returning the target item, not an option\n'
                '{"selected": ["Some invented text"], "reasoning": "..."} — WRONG: not from the options list\n'
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