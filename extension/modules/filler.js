// extension/modules/filler.js

class SurveyFiller {
    static async fillAnswers(answers, detectedQuestions) {
        console.log("Survey Copilot Filler: Received", answers.length, "answers for", detectedQuestions.length, "questions");

        let filled  = 0;
        let skipped = 0;

        // ── Positional iteration ───────────────────────────────────────────────
        // We iterate over detectedQuestions by index and pair each question with
        // answers[i]. This is the ONLY correct approach for matching (dropdown)
        // questions where multiple rows share identical question_text.
        // DO NOT use .find() on question_text — it always returns the first match.
        //
        // For matching-row <select> elements, detector.js stamps a guaranteed-unique
        // scp-uid-N id onto the DOM element at detection time, so
        // document.getElementById(qMap.element_id) always resolves to exactly the
        // right <select> for this row — never to another row's element.
        const count = Math.min(detectedQuestions.length, answers.length);

        for (let i = 0; i < count; i++) {
            const qMap = detectedQuestions[i];   // detector metadata (element_id, type…)
            const ans  = answers[i];             // backend answer at the same index

            if (!qMap || !ans) {
                console.warn(`Survey Copilot Filler: Missing qMap or answer at index ${i}`);
                skipped++;
                continue;
            }

            console.log(
                `Survey Copilot Filler: [${i}] type=${qMap.question_type}` +
                ` element_id="${qMap.element_id ?? qMap.element_ids?.[0]}"` +
                ` selected_options=`, ans.selected_options
            );

            // ── Moodle pagination awareness ────────────────────────────────────
            // Skip elements inside hidden .que containers (paginated quizzes)
            const anchorEl = qMap.element_id
                ? document.getElementById(qMap.element_id)
                : (qMap.element_ids?.[0] ? document.getElementById(qMap.element_ids[0]) : null);

            if (anchorEl) {
                const queContainer = anchorEl.closest('.que');
                if (queContainer && queContainer.offsetParent === null) {
                    console.warn(`Survey Copilot Filler: Skipping hidden question at index ${i}`);
                    skipped++;
                    continue;
                }
            }

            // ── Dispatch to type-specific injector ────────────────────────────
            if (qMap.question_type === 'text') {
                const element = document.getElementById(qMap.element_id);
                if (element && ans.answer) {
                    const answerText = this._extractTextAnswer(ans.answer);
                    if (answerText) {
                        await this.simulateTyping(element, answerText);
                        console.log(`Survey Copilot Filler: [${i}] text → "${answerText}"`);
                        filled++;
                    } else {
                        console.warn(`Survey Copilot Filler: [${i}] _extractTextAnswer returned empty`);
                        skipped++;
                    }
                } else {
                    console.warn(`Survey Copilot Filler: [${i}] text — element not found or no answer`);
                    skipped++;
                }
            }

            else if (qMap.question_type === 'cloze') {
                // ans.selected_options is an ordered string array: ["ans1", "ans2", …]
                const gapAnswers = ans.selected_options;
                if (!gapAnswers || gapAnswers.length === 0) {
                    console.warn(`Survey Copilot Filler: [${i}] cloze — no gap answers`);
                    skipped++;
                    continue;
                }

                const firstGapEl      = qMap.element_ids?.[0] ? document.getElementById(qMap.element_ids[0]) : null;
                const clozeContainer  = firstGapEl?.closest('.que') ?? null;
                if (!clozeContainer) {
                    console.warn(`Survey Copilot Filler: [${i}] cloze — .que container not found`);
                    skipped++;
                    continue;
                }

                const liveGaps  = Array.from(clozeContainer.querySelectorAll('input[type="text"], select'));
                let   gapsFilled = 0;

                for (let g = 0; g < liveGaps.length; g++) {
                    const gapEl = liveGaps[g];
                    const answer = gapAnswers[g];
                    if (answer === undefined || answer === null) {
                        console.warn(`Survey Copilot Filler: [${i}] cloze [GAP ${g + 1}] — no answer`);
                        continue;
                    }

                    if (gapEl.tagName.toLowerCase() === 'select') {
                        const domOptions  = Array.from(gapEl.options);
                        const targetLower = String(answer).trim().toLowerCase();
                        const matchedOpt  = domOptions.find(o => o.text.trim().toLowerCase() === targetLower)
                                         || domOptions.find(o => o.text.trim().toLowerCase().includes(targetLower));
                        if (matchedOpt) {
                            gapEl.value = matchedOpt.value;
                            gapEl.dispatchEvent(new Event('change', { bubbles: true }));
                            console.log(`Survey Copilot Filler: [${i}] cloze [GAP ${g + 1}] <select> → "${matchedOpt.text}"`);
                            gapsFilled++;
                        } else {
                            console.warn(`Survey Copilot Filler: [${i}] cloze [GAP ${g + 1}] <select> — no match for "${answer}"`);
                        }
                    } else {
                        await this.simulateTyping(gapEl, String(answer));
                        console.log(`Survey Copilot Filler: [${i}] cloze [GAP ${g + 1}] <input> → "${answer}"`);
                        gapsFilled++;
                    }
                }

                if (gapsFilled > 0) filled++;
                else skipped++;
            }

            else if (qMap.question_type === 'single' || qMap.question_type === 'multi') {
                if (ans.selected_options && ans.selected_options.length > 0) {
                    ans.selected_options.forEach(optIndex => {
                        const elementId = qMap.element_ids?.[optIndex];
                        if (elementId) {
                            const radioOrCheck = document.getElementById(elementId);
                            if (radioOrCheck && !radioOrCheck.checked) {
                                radioOrCheck.click();
                                console.log(`Survey Copilot Filler: [${i}] clicked ${elementId} (optIndex ${optIndex})`);
                            }
                        } else {
                            console.warn(`Survey Copilot Filler: [${i}] no element_id at optIndex ${optIndex}`);
                        }
                    });
                    filled++;
                } else {
                    console.warn(`Survey Copilot Filler: [${i}] single/multi — empty selected_options`);
                    skipped++;
                }
            }

            else if (qMap.question_type === 'dropdown') {
                // ── Strict element_id targeting — NO text matching ────────────────
                // detector.js stamps a guaranteed-unique scp-uid-N id onto every
                // matching-row <select> at detection time, so document.getElementById()
                // always resolves to exactly this row's <select> and nothing else.
                // Previous versions used text-based lookup which always returned sub0.
                const element = document.getElementById(qMap.element_id);
                if (!element) {
                    console.warn(
                        `Survey Copilot Filler: [${i}] dropdown — element "${qMap.element_id}" ` +
                        `not found in DOM. The page may have changed since detection.`
                    );
                    skipped++;
                    continue;
                }

                // Diagnostic guard: getElementById should always return an element
                // whose id attribute matches exactly. If it doesn't, something in the
                // page mutated the DOM after detection — log and skip rather than
                // injecting into the wrong element.
                if (element.id !== qMap.element_id) {
                    console.error(
                        `Survey Copilot Filler: [${i}] ID MISMATCH — expected "${qMap.element_id}" ` +
                        `but resolved element has id="${element.id}". Skipping to avoid wrong injection.`
                    );
                    skipped++;
                    continue;
                }

                if (!ans.selected_options || ans.selected_options.length === 0) {
                    console.warn(`Survey Copilot Filler: [${i}] dropdown "${qMap.element_id}" — empty selected_options`);
                    skipped++;
                    continue;
                }

                const backendIndex = ans.selected_options[0];
                const domIndex     = this._resolveDropdownIndex(element, backendIndex, qMap.options);

                console.log(`Survey Copilot Filler: [${i}] dropdown "${qMap.element_id}" → backendIndex=${backendIndex}, domIndex=${domIndex}`);
                element.selectedIndex = domIndex;
                element.dispatchEvent(new Event('change', { bubbles: true }));
                filled++;
            }

            else {
                console.warn(`Survey Copilot Filler: [${i}] unknown question_type "${qMap.question_type}" — skipping`);
                skipped++;
            }
        }

        console.log(`Survey Copilot Filler: Done. Filled=${filled}, Skipped=${skipped}`);
    }


    /**
     * Resolve the backend's filtered index to the actual DOM <select> index.
     * The detector filtered out placeholder options, so index 0 from backend
     * might be index 1 in the DOM (if "Elegir..." was at index 0).
     * 
     * Strategy: count how many DOM options before the target are placeholders.
     */
    static _resolveDropdownIndex(selectElement, filteredIndex, filteredOptions) {
        const domOptions = Array.from(selectElement.options);
        let filteredCount = 0;

        for (let i = 0; i < domOptions.length; i++) {
            const opt = domOptions[i];
            const isPlaceholder = TextSanitizer.isPlaceholderOption(opt.text, opt.value);

            if (!isPlaceholder) {
                if (filteredCount === filteredIndex) {
                    return i; // This is the real DOM index
                }
                filteredCount++;
            }
        }

        // Fallback: if resolution fails, try a simple offset heuristic
        if (domOptions.length > 0 && TextSanitizer.isPlaceholderOption(domOptions[0].text, domOptions[0].value)) {
            return filteredIndex + 1;
        }
        return filteredIndex;
    }

    /**
     * Safely extract a plain text answer from whatever the backend sends.
     *
     * The LLM pipeline stores the raw model response in `ans.answer`. For text
     * questions the prompt instructs the model to reply in plain text, but some
     * models wrap their reply in a JSON envelope anyway:
     *
     *   {"selected": ["tweet"]}          ← JSON object with selected array
     *   {"selected": "tweet"}            ← JSON object with string value
     *   "tweet"                          ← plain string (ideal)
     *   'tweet'                          ← single-quoted string (rare)
     *
     * Resolution order:
     *   1. Try JSON.parse(). If it succeeds and the object has a `selected`
     *      field, return selected[0] (or the value itself if it's a string).
     *   2. If JSON.parse() fails, treat the input as a raw string.
     *   3. In both cases, strip any surrounding quotes or array brackets.
     *
     * @param {string} raw - The raw answer string from ans.answer.
     * @returns {string} The clean answer text ready to inject.
     */
    static _extractTextAnswer(raw) {
        if (!raw || typeof raw !== 'string') return String(raw ?? '').trim();

        const trimmed = raw.trim();

        // ── Attempt JSON parse ─────────────────────────────────────────────
        if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
            try {
                const parsed = JSON.parse(trimmed);

                // {"selected": ["answer", ...]} — most common LLM JSON format
                if (parsed && typeof parsed === 'object' && 'selected' in parsed) {
                    const sel = parsed.selected;
                    if (Array.isArray(sel) && sel.length > 0) {
                        return String(sel[0]).trim();
                    }
                    if (typeof sel === 'string') {
                        return sel.trim();
                    }
                }

                // ["answer"] — bare array
                if (Array.isArray(parsed) && parsed.length > 0) {
                    return String(parsed[0]).trim();
                }

                // {"answer": "..."}  or any single-value object
                const values = Object.values(parsed);
                if (values.length > 0) {
                    const first = values[0];
                    return Array.isArray(first)
                        ? String(first[0] ?? '').trim()
                        : String(first).trim();
                }
            } catch (jsonErr) {
                // JSON.parse failed — fall through to plain-text handling
                console.debug('Survey Copilot Filler: _extractTextAnswer JSON parse failed — treating as plain text.', jsonErr.message);
            }
        }

        // ── Plain-text path ─────────────────────────────────────────────
        // Strip surrounding quotes (single or double) and lone brackets
        return trimmed
            .replace(/^[\"\'\\[\\(]+/, '')
            .replace(/[\"\'\\]\\)]+$/, '')
            .trim();
    }

    // Efecto visual para que no aparezca de golpe
    static async simulateTyping(element, text) {
        element.value = '';
        element.focus();
        for (let i = 0; i < text.length; i++) {
            element.value += text.charAt(i);
            element.dispatchEvent(new Event('input', { bubbles: true }));
            await new Promise(r => setTimeout(r, 10)); // 10ms por caracter
        }
        element.dispatchEvent(new Event('change', { bubbles: true }));
        element.blur();
    }
}

window.SurveyFiller = SurveyFiller;