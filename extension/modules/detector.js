class SurveyDetector {
    // Moodle containers that hold quiz questions
    static QUIZ_SCOPES = [
        '#responseform',            // Moodle's main quiz form
        '.que',                     // Individual question blocks
        'form[action*="attempt"]',  // Quiz attempt form
        'form[action*="survey"]',   // Survey forms
        '.quiz-content',            // Alternative quiz wrapper
    ];

    // Containers that should NEVER be scanned (Moodle chrome / UI)
    static EXCLUDED_ANCESTORS = [
        '#nav-drawer',              // Left navigation drawer
        '#page-header',             // Top navigation bar
        '.block',                   // Moodle sidebar blocks
        '.messaging-area',          // Messaging panel
        '#message-drawer',          // Message drawer
        '.usermenu',                // User menu dropdown
        '#search-input-container',  // Search bar container
        'nav',                      // Any nav element
        'header',                   // Page header
        'footer',                   // Page footer
        '.modal',                   // Modals / dialogs
        '.drawer',                  // Generic drawers
    ];

    // Moodle UI options that aren't real answers
    static NOISE_OPTION_PATTERNS = [
        /^clear my choice$/i,
        /^limpiar mi elecci[oó]n$/i,
        /^borrar mi elecci[oó]n$/i,
        /^reset my choice$/i,
    ];

    static scanPage() {
        const questions = [];

        // --- STEP 0: Determine scan scope ---
        // Try to find a quiz container first. If none exists, fall back to the full document.
        let scanRoot = null;
        for (const selector of this.QUIZ_SCOPES) {
            scanRoot = document.querySelector(selector);
            if (scanRoot) break;
        }
        // Fallback: if no quiz container found, scan document body
        // but exclusion filters below will still protect against noise
        if (!scanRoot) {
            scanRoot = document.body;
        }

        const inputs = scanRoot.querySelectorAll('input[type="text"], input[type="radio"], input[type="checkbox"], textarea, select');
        
        inputs.forEach((input, index) => {
            // --- SKIP: Elements inside excluded Moodle UI containers ---
            if (this.EXCLUDED_ANCESTORS.some(sel => input.closest(sel))) {
                return;
            }

            const type = input.type;
            const name = input.name || `unnamed_${index}`;
            const id = input.id || `auto_id_${index}`;
            if (!input.id) input.id = id;

            // --- SKIP HIDDEN QUESTIONS ---
            // Moodle pagination hides non-active questions with display:none on .que
            const queContainer = input.closest('.que');
            if (queContainer && queContainer.offsetParent === null) {
                return;
            }

            // --- SKIP: Inputs that are clearly not quiz questions ---
            // If the input is NOT inside a .que (Moodle question) and NOT inside a
            // form/fieldset, it's likely a Moodle UI element (search, messaging, etc.)
            if (!input.closest('.que') && !input.closest('fieldset') && !input.closest('.question') && !input.closest('.form-group')) {
                // Only allow if inside a form that looks like a quiz/survey
                const form = input.closest('form');
                if (!form || (!form.action.includes('attempt') && !form.action.includes('survey') && !form.id?.includes('responseform'))) {
                    return;
                }
            }

            let questionText = "Pregunta sin título";
            let optionLabel = "";

            // --- 1. EXTRAER TEXTOS (Heurística Avanzada + TextSanitizer) ---
            
            // Caso A: Tablas de emparejamiento (Moodle)
            if (input.tagName.toLowerCase() === 'select' && input.closest('tr')) {
                const row = input.closest('tr');
                const firstCell = row.querySelector('td:first-child');
                const mainQuestionContainer = input.closest('.que');
                
                if (firstCell && mainQuestionContainer) {
                    const qtextEl = mainQuestionContainer.querySelector('.qtext');
                    const mainText = TextSanitizer.sanitize(qtextEl);
                    const cellText = TextSanitizer.extractCleanText(firstCell);
                    questionText = `${mainText} -> ${cellText}`;
                }
            } 
            // Caso B: Opciones Múltiples (Radios / Checkboxes)
            else if (type === 'radio' || type === 'checkbox') {
                // --- SKIP: "Clear my choice" / "Limpiar mi elección" ---
                // Moodle adds a radio with value=-1 as a reset button
                if (input.value === '-1') {
                    return; // Not a real answer option
                }

                // Extract the OPTION label using sanitizer
                const optNode = document.querySelector(`label[for="${id}"]`) || input.parentElement;
                let rawLabel = '';
                if (optNode) {
                    rawLabel = TextSanitizer.sanitizeOption(optNode);
                } else {
                    rawLabel = TextSanitizer.normalizeWhitespace(input.value);
                }

                // Filter out noise options by text pattern
                if (this.NOISE_OPTION_PATTERNS.some(p => p.test(rawLabel))) {
                    return;
                }

                optionLabel = rawLabel;

                // Climb the DOM to extract the actual QUESTION text
                const mainContainer = input.closest('.que');      // Estructura Moodle
                const fieldset = input.closest('fieldset');       // Estructura HTML estándar
                
                if (mainContainer && mainContainer.querySelector('.qtext')) {
                    questionText = TextSanitizer.sanitize(mainContainer.querySelector('.qtext'));
                } else if (fieldset && fieldset.querySelector('legend')) {
                    questionText = TextSanitizer.sanitize(fieldset.querySelector('legend'));
                } else {
                    // Fallback
                    const parentText = input.closest('.question, .form-group');
                    if (parentText) {
                        const cleanParent = TextSanitizer.extractCleanText(parentText);
                        questionText = cleanParent.split('\n')[0].trim() || questionText;
                    }
                }
            }
            // Caso C: Texto libre y Selectboxes normales
            else {
                let label = document.querySelector(`label[for="${id}"]`);
                if (label) {
                    questionText = TextSanitizer.sanitize(label);
                } else {
                    const mainContainer = input.closest('.que');
                    if (mainContainer && mainContainer.querySelector('.qtext')) {
                        questionText = TextSanitizer.sanitize(mainContainer.querySelector('.qtext'));
                    }
                }
            }

            // --- FINAL GUARD: Skip questions with no meaningful text ---
            if (questionText === "Pregunta sin título") {
                return; // Could not extract a question — skip to avoid confusing the LLM
            }

            // --- 2. CLASIFICAR Y AGRUPAR EN JSON ---
            
            if (type === 'text' || input.tagName.toLowerCase() === 'textarea') {
                questions.push({ element_id: id, question_text: questionText, question_type: "text" });
            } 
            else if (type === 'radio' || type === 'checkbox') {
                let existingQ = questions.find(q => q.group_name === name);
                if (existingQ) {
                    existingQ.options.push(optionLabel);
                    existingQ.element_ids.push(id);
                } else {
                    questions.push({
                        group_name: name,
                        question_text: questionText,
                        question_type: type === 'radio' ? "single" : "multi",
                        options: [optionLabel],
                        element_ids: [id]
                    });
                }
            } 
            else if (input.tagName.toLowerCase() === 'select') {
                // Filter out placeholder options ("Elegir...", "", value="0", etc.)
                const options = Array.from(input.options)
                    .filter(opt => !TextSanitizer.isPlaceholderOption(opt.text, opt.value))
                    .map(opt => TextSanitizer.stripOptionPrefix(
                        TextSanitizer.normalizeWhitespace(opt.text)
                    ));
                
                questions.push({ element_id: id, question_text: questionText, question_type: "dropdown", options: options });
            }
        });

        console.log("Survey Copilot: Detectadas", questions.length, "preguntas válidas", questions);
        return questions;
    }
}

window.SurveyDetector = SurveyDetector;