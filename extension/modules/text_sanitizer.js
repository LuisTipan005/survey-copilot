// extension/modules/text_sanitizer.js

/**
 * TextSanitizer — DOM text extraction with noise removal.
 * 
 * Moodle's DOM is littered with hidden icons, feedback text from previous
 * attempts, grade info, and CSS pseudo-content. This module clones DOM nodes
 * and strips all known noise sources before extracting text, so the detector
 * only sees semantically meaningful content.
 */
class TextSanitizer {
    // Moodle elements that inject noise into question/option text
    static NOISE_SELECTORS = [
        '.feedbacktext',
        '.rightanswer',
        '.specificfeedback',
        '.outcome',
        '.grade',
        '.questionflag',
        '.editquestion',
        '.info',
        '.state',
        '.icon',
        '.fa',                    // FontAwesome icons
        '.feedback',
        '[aria-hidden="true"]',   // Screen-reader-hidden decorative elements
        'script',
        'style',
        '.que > .info',           // Moodle question metadata block ("Pregunta 1", "Puntúa 1,00")
    ];

    // Placeholder texts to filter out of <select> options
    static PLACEHOLDER_PATTERNS = [
        /^elegir\.{0,3}$/i,
        /^choose\.{0,3}$/i,
        /^seleccione\.{0,3}$/i,
        /^select\.{0,3}$/i,
        /^--.*--$/,
        /^\s*$/,
    ];

    /**
     * Clone an element, remove all noise children, then return the clean innerText.
     * The live DOM is never modified.
     * 
     * @param {HTMLElement} element - The DOM element to extract text from.
     * @returns {string} Clean text content.
     */
    static extractCleanText(element) {
        if (!element) return '';

        const clone = element.cloneNode(true);

        // Remove all noise nodes from the clone
        for (const selector of this.NOISE_SELECTORS) {
            clone.querySelectorAll(selector).forEach(n => n.remove());
        }

        // Extract text and normalize
        return this.normalizeWhitespace(clone.innerText || clone.textContent || '');
    }

    /**
     * Remove common option prefixes added by Moodle/LMS:
     * "a. ", "b) ", "A- ", "c: ", "1. ", "2) " etc.
     * 
     * @param {string} text - Raw option text.
     * @returns {string} Text without the leading prefix.
     */
    static stripOptionPrefix(text) {
        if (!text) return '';
        // Match: letter or digit, followed by . ) : or -, then whitespace
        return text.replace(/^[a-zA-Z0-9][.):\-]\s*/, '').trim();
    }

    /**
     * Normalize whitespace: collapse multiple spaces/newlines, trim,
     * remove zero-width characters and other invisible Unicode.
     * 
     * @param {string} text - Raw text.
     * @returns {string} Normalized text.
     */
    static normalizeWhitespace(text) {
        if (!text) return '';
        return text
            // Remove zero-width chars (ZWS, ZWNJ, ZWJ, BOM, etc.)
            .replace(/[\u200B\u200C\u200D\uFEFF\u00AD]/g, '')
            // Collapse all whitespace runs (including \n, \r, \t) into single space
            .replace(/\s+/g, ' ')
            // Trim
            .trim();
    }

    /**
     * Check if a <select> option text is a placeholder.
     * 
     * @param {string} text - The option's display text.
     * @param {string} value - The option's value attribute.
     * @returns {boolean} True if this option should be filtered out.
     */
    static isPlaceholderOption(text, value) {
        // Empty value or explicit reset value are always placeholders
        if (value === '' || value === '-1') {
            return true;
        }
        const trimmed = text.trim();
        // value="0" is only a placeholder if the text also looks like one
        if (value === '0' && this.PLACEHOLDER_PATTERNS.some(pattern => pattern.test(trimmed))) {
            return true;
        }
        // Pure text-based check for remaining cases
        return this.PLACEHOLDER_PATTERNS.some(pattern => pattern.test(trimmed));
    }

    /**
     * Full sanitization pipeline: clone → strip noise → extract text → normalize.
     * Use this for question text where maximum cleanliness is needed.
     * 
     * @param {HTMLElement} element - The DOM element to sanitize.
     * @returns {string} Fully sanitized text.
     */
    static sanitize(element) {
        return this.extractCleanText(element);
    }

    /**
     * Sanitize an option label: extract clean text, strip prefix, normalize.
     * 
     * @param {HTMLElement} element - The label or parent element.
     * @returns {string} Clean option text without prefix.
     */
    static sanitizeOption(element) {
        const cleanText = this.extractCleanText(element);
        return this.stripOptionPrefix(cleanText);
    }
}

window.TextSanitizer = TextSanitizer;
