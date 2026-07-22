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

            "5. VISUAL ANALYSIS (image is attached alongside this message)\n"
            "   - An image has been included as part of this question.\n"
            "   - Study the image carefully before answering (diagrams, charts, screenshots, etc.).\n"
            "   - Combine what you observe in the image with the written question text.\n"
            "   - If the question has options, evaluate each option against the visual evidence.\n"
            "   - Output follows the same rules as the corresponding question type above.\n\n"

            "6. MULTI-GAP FILL-IN-THE-BLANK (Cloze)\n"
            "   - The question text contains numbered placeholders: [GAP 1], [GAP 2], etc.\n"
            "   - Each placeholder represents a MISSING word, number, or short phrase.\n"
            "   - Calculate the exact answer for EACH gap in strict sequential order.\n"
            "   - Typical use-cases: chemical equations, mathematical expressions, ordered sequences.\n"
            "   - Output: a JSON array in the 'selected' field, one string per gap, in order.\n"
            "   - Example: if there are 3 gaps → {\"selected\": [\"2\", \"H₂O\", \"1\"]}.\n"
            "   - The array length MUST equal the total number of [GAP n] markers.\n\n"

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

        # --- VISUAL HINT: Prepend a notice when the question carries an image ---
        image_notice = (
            "[IMAGE ATTACHED] This question includes an image. "
            "Analyze it carefully as part of your answer.\n\n"
        ) if question.image_base64 else ""

        # --- MANDATORY SELECTION RULE (appended to all choice prompts) ---
        mandatory_rule = (
            "\n\nMANDATORY: The 'selected' list must contain at least one option. "
            "An empty list is NEVER valid. If you are unsure, pick the most likely answer."
        )

        if question.question_type == QuestionType.TEXT:
            prompt = (
                f"{image_notice}"
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
                f"{image_notice}"
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
                f"{image_notice}"
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
                f"{image_notice}"
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

        elif question.question_type == QuestionType.CLOZE:
            gap_count = question.gap_count or question.question_text.count('[GAP ')
            prompt = (
                f"{image_notice}"
                f"{context_block}"
                f"Question (with gaps marked as [GAP 1], [GAP 2], …):\n"
                f"{question.question_text}\n\n"
                f"Task: Fill in EVERY gap, in order, {behavior}.\n"
                f"There are {gap_count} gap(s) to fill.\n\n"
                "CRITICAL RULES:\n"
                "1. Return ONLY a valid JSON object — no markdown, no prose.\n"
                "2. The 'selected' field must be an ARRAY with exactly one string per gap, "
                "listed in the same order as the [GAP n] placeholders.\n"
                "3. Each value must be the shortest exact answer (a number, chemical symbol, "
                "word, or brief phrase). Do NOT use full sentences.\n"
                f"4. The array must have exactly {gap_count} element(s).\n\n"
                "CORRECT example (3 gaps): "
                '{"selected": ["2", "H₂O", "1"], "reasoning": "Brief justification"}\n'
                "WRONG examples:\n"
                '{"selected": ["2 H₂O 1"], "reasoning": "..."} — WRONG: all answers in one element\n'
                '{"selected": [], "reasoning": "..."} — WRONG: empty array is never valid'
            )
            format_json = True

        return {
            "prompt": prompt,
            "system_prompt": system_prompt,
            "format_json": format_json
        }

prompt_engine = PromptEngine()