// Module-level counter so every stamped ID is unique across repeated scans.
let _scpUidCounter = 0;

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

    /**
     * Moodle generic UI strings that can bleed into extracted question text.
     * These are stripped (case-insensitive, whole-line or inline) by _cleanQText().
     */
    static QTEXT_UI_NOISE = [
        /not yet answered/gi,
        /marked out of [\d.,]+/gi,       // e.g. "Marked out of 1.00"
        /puntuaci[oó]n m[aá]xima.*?\d/gi, // Spanish equivalent
        /flag question/gi,
        /marcar pregunta/gi,
        /edit question/gi,
        /editar pregunta/gi,
        /\bAnswer:\s*/gi,                // The infamous "Answer:" label
        /\bRespuesta:\s*/gi,             // Spanish "Answer:"
        /question\s+\d+\s*(not complete)?/gi, // "Question 3", "Question 3 Not complete"
        /pregunta\s+\d+/gi,
        /your answer\s*:?/gi,
        /tu respuesta\s*:?/gi,
    ];

    /**
     * Strip all known Moodle UI noise patterns from a raw text string.
     * Also collapses excess whitespace and trims the result.
     *
     * @param {string} raw - Raw text extracted from the DOM.
     * @returns {string} Cleaned text.
     */
    static _cleanQText(raw) {
        if (!raw) return '';
        let cleaned = raw;
        for (const pattern of this.QTEXT_UI_NOISE) {
            cleaned = cleaned.replace(pattern, ' ');
        }
        // Collapse multiple spaces/newlines into a single space and trim
        return cleaned.replace(/[\s\n\r]+/g, ' ').trim();
    }

    /**
     * Extracts the first meaningful image found inside a Moodle .que block
     * and returns it as a Base64 data URL.
     *
     * Strategy:
     *  1. If the <img> src is already a data URL (base64), return it directly.
     *  2. Otherwise, try to draw the image on an off-screen <canvas> and call
     *     toDataURL(). This works when the image is same-origin or the server
     *     sends permissive CORS headers.
     *  3. If the canvas is tainted (cross-origin restriction), fall back to
     *     returning the raw src URL so the backend can decide what to do.
     *     Returns null if no usable image is found.
     *
     * @param {Element} queContainer - The .que DOM element to search inside.
     * @returns {string|null} A data URL, an absolute URL, or null.
     */
    /**
     * Moodle UI class names that appear on non-content images.
     * The filter checks the element's own classList (not just ancestors).
     */
    static IMAGE_NOISE_CLASSES = [
        'userpicture',   // user avatar
        'icon',          // generic Moodle icon
        'iconsmall',     // small icon variant
        'smallicon',     // alternate naming
        'questionflag',  // question flag toggle icon
        'emoticon',      // emoji images
        'resize-icon',   // resizable content handles
    ];

    /**
     * src substrings that indicate a user-profile image URL.
     * These are typically served by Moodle's pluginfile.php for the /user/ area.
     */
    static IMAGE_NOISE_SRC_PATTERNS = [
        'pluginfile.php/user',  // user profile files
        '/user/icon',           // Moodle user icon endpoint
        '/user/view',           // user view redirects
        '/theme/',              // theme decoration assets
        '/pix/',                // Moodle core pixel/icon assets
    ];

    /** Minimum rendered or natural dimension (px) for a content image. */
    static IMAGE_MIN_SIZE = 50;

    static extractImageAsBase64(queContainer) {
        if (!queContainer) return null;

        const img = Array.from(queContainer.querySelectorAll('img')).find(el => {
            const src = el.src || '';

            // 1. Must have a non-empty src that is not a blank GIF tracking pixel
            if (!src) return false;
            if (src.startsWith('data:image/gif') && el.width <= 1) return false;

            // 2. Dimension check — use rendered size; fall back to natural size
            //    Both width AND height must meet the minimum threshold.
            const w = el.offsetWidth  || el.naturalWidth  || el.width  || 0;
            const h = el.offsetHeight || el.naturalHeight || el.height || 0;
            if (w < this.IMAGE_MIN_SIZE || h < this.IMAGE_MIN_SIZE) return false;

            // 3. Class check on the element itself (not just ancestors)
            const classes = el.classList;
            if (this.IMAGE_NOISE_CLASSES.some(c => classes.contains(c))) return false;

            // 4. Also reject if inside a Moodle UI ancestor with these classes
            if (el.closest('.userpicture, .icon, .smallicon, .questionflag')) return false;

            // 5. src substring check — reject known profile / decoration URL patterns
            if (this.IMAGE_NOISE_SRC_PATTERNS.some(pattern => src.includes(pattern))) return false;

            return true; // passes all checks → this is a genuine content image
        });

        if (!img) return null;

        // Case 1: already a base64 data URL
        if (img.src.startsWith('data:')) return img.src;

        // Case 2: attempt canvas extraction (same-origin or permissive CORS)
        try {
            const canvas = document.createElement('canvas');
            canvas.width  = img.naturalWidth  || img.width  || 300;
            canvas.height = img.naturalHeight || img.height || 300;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            return canvas.toDataURL('image/png'); // throws if canvas is tainted
        } catch (corsErr) {
            // Canvas is tainted due to cross-origin restriction.
            // Fall back to the absolute URL so the backend can decide what to do.
            console.warn('Survey Copilot: canvas tainted for image', img.src, '— sending URL instead.');
            try {
                return new URL(img.src, window.location.href).href;
            } catch (_) {
                return img.src || null; // last resort
            }
        }
    }

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
            // Note: for matching-row <select> elements the id is overwritten with
            // a guaranteed-unique scp-uid-N value in Caso A below. For all other
            // inputs we preserve any existing id or mint a unique fallback.
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
            
            // Caso A: Tablas de emparejamiento (Moodle matching questions)
            // ── Each <tr> = one sub-question; extract its unique clue locally ──
            if (input.tagName.toLowerCase() === 'select' && input.closest('tr')) {
                // ── 0. Stamp a guaranteed-unique ID onto the DOM element ───────
                // Moodle matching rows often share the same id (e.g. all "sub0") or
                // have no id at all.  We overwrite whatever is there with a fresh
                // scp-uid-N value so document.getElementById() in filler.js always
                // resolves to exactly this <select> and nothing else.
                const uniqueId = `scp-uid-${_scpUidCounter++}`;
                input.id = uniqueId;

                const row               = input.closest('tr');
                const mainQContainer    = input.closest('.que');

                // ── 1. Global question title from .qtext ──────────────────────
                let mainTitle = '';
                if (mainQContainer) {
                    const qtextEl = mainQContainer.querySelector('.qtext');
                    mainTitle = qtextEl
                        ? this._cleanQText(TextSanitizer.sanitize(qtextEl))
                        : '';
                }

                // ── 2. Find the local clue cell in this row ───────────────────
                // The row typically has:
                //   <td class="text">  ← clue (text and/or image)
                //   <td class="control"> ← contains the <select>
                // We pick every <td> that does NOT contain this <select>.
                const selectTd  = input.closest('td');
                const clueCells = Array.from(row.querySelectorAll('td'))
                    .filter(td => !td.contains(input));

                // Prefer an explicit .text or .stem cell; fall back to first non-select td
                const clueCell = clueCells.find(td =>
                    td.classList.contains('text') ||
                    td.classList.contains('stem') ||
                    td.classList.contains('clue')
                ) || clueCells[0] || null;

                // ── 3. Extract local text clue (ignore <img> and <select> text) ─
                let localText = '';
                if (clueCell) {
                    // Clone the cell and strip any <img> and <select> nodes so their
                    // alt/value text doesn't contaminate the text extraction.
                    const cloneCell = clueCell.cloneNode(true);
                    cloneCell.querySelectorAll('img, select, input').forEach(el => el.remove());
                    localText = this._cleanQText(TextSanitizer.extractCleanText(cloneCell));
                }

                // ── 4. Build final question_text ──────────────────────────────
                if (mainTitle && localText) {
                    questionText = `${mainTitle} -> ${localText}`;
                } else if (mainTitle) {
                    questionText = mainTitle;     // image-only clue row; title alone
                } else if (localText) {
                    questionText = localText;     // no global .qtext; use local clue
                }
                // else: remains "Pregunta sin título" — caught by the FINAL GUARD below

                // ── 5. Per-row image extraction ───────────────────────────────
                // Look for an <img> ONLY inside this row's clue cell (or the whole
                // row as fallback). Explicitly null when no image is found here,
                // so the LLM payload is not confused by images from other rows.
                const rowImageScope = clueCell || row;
                const rowImg = Array.from(rowImageScope.querySelectorAll('img')).find(el => {
                    const src = el.src || '';
                    if (!src || (src.startsWith('data:image/gif') && el.width <= 1)) return false;
                    const w = el.offsetWidth  || el.naturalWidth  || el.width  || 0;
                    const h = el.offsetHeight || el.naturalHeight || el.height || 0;
                    if (w < this.IMAGE_MIN_SIZE || h < this.IMAGE_MIN_SIZE) return false;
                    if (this.IMAGE_NOISE_CLASSES.some(c => el.classList.contains(c))) return false;
                    if (this.IMAGE_NOISE_SRC_PATTERNS.some(p => src.includes(p))) return false;
                    return true;
                }) || null;

                // Convert the row-local image to Base64 (reuse the canvas logic)
                // stored as a temporary property; we'll wire it into the question
                // object below in the classification section.
                input._rowImageBase64 = rowImg
                    ? (this._imgToBase64(rowImg) || null)
                    : null;

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
            // Caso C: Texto libre (text / textarea) y Selectboxes fuera de tabla
            // ── Priority order ────────────────────────────────────────────────
            // 1. .qtext inside the .que block        ← real question content
            // 2. label[for="id"] if .qtext is absent ← fallback (may say "Answer:")
            // 3. Any ancestor .question / .form-group ← last resort
            //
            // In Moodle Short Answer questions a <label> with text "Answer:" sits
            // right next to the <input>, so we MUST check .qtext first.
            else {
                const mainContainer = input.closest('.que');
                const qtextEl = mainContainer?.querySelector('.qtext');

                if (qtextEl) {
                    // Primary: clean the .qtext content — this is always the real question
                    const raw = TextSanitizer.sanitize(qtextEl);
                    const cleaned = this._cleanQText(raw);
                    if (cleaned) {
                        questionText = cleaned;
                    }
                } else {
                    // Fallback A: label associated with the input
                    const label = document.querySelector(`label[for="${id}"]`);
                    if (label) {
                        const raw = TextSanitizer.sanitize(label);
                        const cleaned = this._cleanQText(raw);
                        // Only use the label if it has real content after noise removal
                        if (cleaned && cleaned.length > 3) {
                            questionText = cleaned;
                        }
                    }

                    // Fallback B: broadest ancestor scan
                    if (questionText === "Pregunta sin título") {
                        const parentEl = input.closest('.question, .form-group');
                        if (parentEl) {
                            const raw = TextSanitizer.extractCleanText(parentEl);
                            const cleaned = this._cleanQText(raw);
                            questionText = cleaned.split('\n')[0].trim() || questionText;
                        }
                    }
                }
            }

            // --- FINAL GUARD: Skip questions with no meaningful text ---
            if (questionText === "Pregunta sin título") {
                return; // Could not extract a question — skip to avoid confusing the LLM
            }

            // --- 2. CLASIFICAR Y AGRUPAR EN JSON ---

            // Extract image from the .que block once per question group
            const imageBase64 = this.extractImageAsBase64(queContainer);

            if (type === 'text' || input.tagName.toLowerCase() === 'textarea') {

                // ── CLOZE DETECTION ──────────────────────────────────────────
                // If the .que block contains more than one text/select input,
                // this is a multi-gap (cloze) question. We process it exactly
                // once — on the first input — and skip all subsequent siblings.
                if (queContainer) {
                    const gapInputs = Array.from(
                        queContainer.querySelectorAll('input[type="text"], select')
                    );

                    if (gapInputs.length > 1) {
                        // Check if we have already emitted a cloze entry for this .que
                        const alreadyEmitted = questions.some(
                            q => q.question_type === 'cloze' && q._cloze_que === queContainer
                        );
                        if (alreadyEmitted) return; // skip — already handled

                        // Build the gapped question text by cloning the .qtext node
                        // and replacing each input/select with a [GAP n] marker.
                        const qtextEl = queContainer.querySelector('.qtext') || queContainer;
                        const clone = qtextEl.cloneNode(true);
                        let gapIndex = 1;
                        clone.querySelectorAll('input[type="text"], select').forEach(el => {
                            const marker = document.createTextNode(` [GAP ${gapIndex++}] `);
                            el.parentNode.replaceChild(marker, el);
                        });
                        const gappedText = TextSanitizer.extractCleanText(clone)
                            || questionText;

                        // Collect the ordered element IDs so filler.js can address each gap
                        const gapElementIds = gapInputs.map((el, i) => {
                            if (!el.id) el.id = `cloze_gap_${i}_${Date.now()}`;
                            return el.id;
                        });

                        const q = {
                            element_ids: gapElementIds,
                            question_text: gappedText,
                            question_type: 'cloze',
                            gap_count: gapInputs.length,
                            _cloze_que: queContainer, // internal sentinel — stripped before sending
                        };
                        if (imageBase64) q.image_base64 = imageBase64;
                        questions.push(q);
                        return; // done for this .que block
                    }
                }

                // ── Single-gap text / textarea (unchanged) ───────────────────
                const q = { element_id: id, question_text: questionText, question_type: 'text' };
                if (imageBase64) q.image_base64 = imageBase64;
                questions.push(q);

            } 
            else if (type === 'radio' || type === 'checkbox') {
                let existingQ = questions.find(q => q.group_name === name);
                if (existingQ) {
                    existingQ.options.push(optionLabel);
                    existingQ.element_ids.push(id);
                    // Attach image if not already attached (first radio sets it)
                    if (imageBase64 && !existingQ.image_base64) {
                        existingQ.image_base64 = imageBase64;
                    }
                } else {
                    const q = {
                        group_name: name,
                        question_text: questionText,
                        question_type: type === 'radio' ? "single" : "multi",
                        options: [optionLabel],
                        element_ids: [id]
                    };
                    if (imageBase64) q.image_base64 = imageBase64;
                    questions.push(q);
                }
            } 
            else if (input.tagName.toLowerCase() === 'select') {
                // Skip selects that are already counted as cloze gaps in this .que
                if (queContainer) {
                    const isClozeGap = questions.some(
                        q => q.question_type === 'cloze'
                             && q._cloze_que === queContainer
                             && q.element_ids?.includes(id)
                    );
                    if (isClozeGap) return;
                }

                // Filter out placeholder options ("Elegir...", "", value="0", etc.)
                const options = Array.from(input.options)
                    .filter(opt => !TextSanitizer.isPlaceholderOption(opt.text, opt.value))
                    .map(opt => TextSanitizer.stripOptionPrefix(
                        TextSanitizer.normalizeWhitespace(opt.text)
                    ));

                // ── Image source decision ───────────────────────────────────
                // Matching-table selects store their per-row image on the input
                // element itself (set in Caso A above). Use that if present;
                // otherwise fall back to the shared .que-level image for
                // standalone <select> questions outside a table.
                const isMatchingRow = input.closest('tr') !== null;
                const resolvedImage = isMatchingRow
                    ? (input._rowImageBase64 ?? null)   // null = no image in this row
                    : (imageBase64 ?? null);             // shared .que image

                const q = {
                    element_id: id,
                    question_text: questionText,
                    question_type: "dropdown",
                    options,
                    image_base64: resolvedImage,         // explicit null when absent
                };
                questions.push(q);
            }
        });

        // Strip internal sentinel before returning (not serialisable / not needed by backend)
        const cleanQuestions = questions.map(q => {
            const { _cloze_que, ...rest } = q;
            return rest;
        });

        console.log("Survey Copilot: Detectadas", cleanQuestions.length, "preguntas válidas", cleanQuestions);
        return cleanQuestions;
    }
    /**
     * Convert a single <img> element to a Base64 data URL.
     *
     * Uses the same canvas-extraction + CORS-fallback strategy as
     * extractImageAsBase64(), but operates on an already-selected <img>
     * so the caller controls which image to convert.
     *
     * @param {HTMLImageElement} img
     * @returns {string|null} data URL, absolute URL (CORS fallback), or null.
     */
    static _imgToBase64(img) {
        if (!img) return null;

        // Already a base64 data URL — return as-is
        if (img.src.startsWith('data:')) return img.src;

        try {
            const canvas = document.createElement('canvas');
            canvas.width  = img.naturalWidth  || img.width  || 300;
            canvas.height = img.naturalHeight || img.height || 300;
            canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
            return canvas.toDataURL('image/png'); // throws if canvas is tainted
        } catch (_corsErr) {
            // Cross-origin restriction: send the absolute URL so the backend can fetch it
            console.warn('Survey Copilot: canvas tainted for row image', img.src, '— sending URL.');
            try   { return new URL(img.src, window.location.href).href; }
            catch { return img.src || null; }
        }
    }
}

window.SurveyDetector = SurveyDetector;