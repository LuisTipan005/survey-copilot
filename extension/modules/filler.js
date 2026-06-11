// extension/modules/filler.js

class SurveyFiller {
    static async fillAnswers(answers, detectedQuestions) {
        console.log("Survey Copilot Filler: Received", answers.length, "answers for", detectedQuestions.length, "questions");

        let filled = 0;
        let skipped = 0;

        for (const ans of answers) {
            // Buscamos la pregunta original en nuestro mapeo
            const qMap = detectedQuestions.find(q => q.question_text === ans.question_text);
            if (!qMap) {
                console.warn(`Survey Copilot Filler: No match for answer "${ans.question_text?.substring(0, 60)}..."`);
                skipped++;
                continue;
            }

            console.log(`Survey Copilot Filler: Matched "${qMap.question_text?.substring(0, 50)}..." | type=${qMap.question_type} | selected_options=`, ans.selected_options);

            // --- Moodle pagination awareness ---
            // Don't interact with elements inside hidden question containers
            const visibilityElement = qMap.element_id 
                ? document.getElementById(qMap.element_id)
                : (qMap.element_ids?.[0] ? document.getElementById(qMap.element_ids[0]) : null);

            if (visibilityElement) {
                const queContainer = visibilityElement.closest('.que');
                if (queContainer && queContainer.offsetParent === null) {
                    console.warn(`Survey Copilot Filler: Skipping hidden question "${ans.question_text?.substring(0, 50)}..."`);
                    skipped++;
                    continue;
                }
            }

            if (qMap.question_type === 'text') {
                const element = document.getElementById(qMap.element_id);
                if (element && ans.answer) {
                    await this.simulateTyping(element, ans.answer);
                    filled++;
                }
            } 
            else if (qMap.question_type === 'single' || qMap.question_type === 'multi') {
                if (ans.selected_options && ans.selected_options.length > 0) {
                    ans.selected_options.forEach(index => {
                        const elementId = qMap.element_ids?.[index];
                        if (elementId) {
                            const radioOrCheck = document.getElementById(elementId);
                            if (radioOrCheck && !radioOrCheck.checked) {
                                radioOrCheck.click();
                                console.log(`Survey Copilot Filler: Clicked ${elementId} (index ${index})`);
                            }
                        } else {
                            console.warn(`Survey Copilot Filler: No element_id at index ${index} for "${qMap.question_text?.substring(0, 40)}..."`);
                        }
                    });
                    filled++;
                } else {
                    console.warn(`Survey Copilot Filler: Empty selected_options for "${qMap.question_text?.substring(0, 50)}..."`);
                    skipped++;
                }
            }
            else if (qMap.question_type === 'dropdown') {
                const element = document.getElementById(qMap.element_id);
                if (element && ans.selected_options && ans.selected_options.length > 0) {
                    let backendIndex = ans.selected_options[0];
                    let domIndex = this._resolveDropdownIndex(element, backendIndex, qMap.options);
                    
                    console.log(`Survey Copilot Filler: Dropdown ${qMap.element_id} -> backendIndex=${backendIndex}, domIndex=${domIndex}`);
                    element.selectedIndex = domIndex;
                    element.dispatchEvent(new Event('change', { bubbles: true }));
                    filled++;
                } else {
                    console.warn(`Survey Copilot Filler: No element or empty selected_options for dropdown "${qMap.question_text?.substring(0, 50)}..."`);
                    skipped++;
                }
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