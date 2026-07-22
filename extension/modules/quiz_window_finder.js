/**
 * quiz_window_finder.js
 *
 * Multi-window targeting utility for Survey Copilot.
 *
 * Problem: Moodle launches quizzes inside a secure pop-up window that has no
 * extension toolbar, so the user must trigger the scan from the parent window.
 * The default `chrome.tabs.query({active:true, currentWindow:true})` only sees
 * the parent tab and misses the quiz DOM inside the pop-up.
 *
 * Solution: Search ALL open tabs across ALL windows for a Moodle quiz URL, and
 * return the first matching tab so the background script can inject into it.
 */

const QuizWindowFinder = (() => {

    /**
     * URL patterns that identify a Moodle quiz attempt.
     * Matches typical Moodle paths regardless of the institution's hostname.
     */
    const MOODLE_QUIZ_PATTERNS = [
        /mod\/quiz\/attempt\.php/,
        /mod\/quiz\/startattempt\.php/,
        /mod\/quiz\/review\.php/,
        /mod\/quiz\/summary\.php/,
        /mod\/survey\/complete\.php/,
        /mod\/questionnaire\/complete\.php/,
    ];

    /**
     * Checks whether a given URL matches any of the known Moodle quiz patterns.
     * @param {string} url
     * @returns {boolean}
     */
    function isMoodleQuizUrl(url) {
        if (!url) return false;
        return MOODLE_QUIZ_PATTERNS.some(pattern => pattern.test(url));
    }

    /**
     * Scans ALL open tabs (across every window) and returns the first tab whose
     * URL matches a Moodle quiz pattern.
     *
     * Falls back to the currently active tab in the current window when no quiz
     * tab is found, preserving the original behaviour on regular survey pages.
     *
     * @returns {Promise<chrome.tabs.Tab | null>}
     */
    async function findQuizTab() {
        // Query every tab in every window — requires the "tabs" permission
        const allTabs = await chrome.tabs.query({});

        // 1. Prefer a Moodle quiz pop-up window (popup type)
        const quizPopupTab = allTabs.find(
            tab => tab.url && isMoodleQuizUrl(tab.url) && tab.windowId !== chrome.windows.WINDOW_ID_CURRENT
        );
        if (quizPopupTab) {
            console.log("[QuizWindowFinder] Moodle quiz pop-up tab found:", quizPopupTab.url);
            return quizPopupTab;
        }

        // 2. Fallback: quiz in a normal (non-popup) window
        const quizNormalTab = allTabs.find(
            tab => tab.url && isMoodleQuizUrl(tab.url)
        );
        if (quizNormalTab) {
            console.log("[QuizWindowFinder] Moodle quiz tab found in normal window:", quizNormalTab.url);
            return quizNormalTab;
        }

        // 3. Last resort: the currently active tab in the current window
        console.warn("[QuizWindowFinder] No Moodle quiz tab found. Falling back to active tab.");
        const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
        return activeTab || null;
    }

    /**
     * Injects the content scripts (text_sanitizer → detector → filler → content)
     * into the given tab using chrome.scripting.executeScript.
     *
     * This is necessary for tabs that were opened AFTER the extension was loaded
     * (e.g., Moodle secure pop-ups) because content_scripts in manifest.json are
     * injected at page load — if the extension wasn't installed at that moment,
     * or the pop-up blocked the injection, we need to force-inject here.
     *
     * @param {number} tabId
     * @returns {Promise<void>}
     */
    async function injectScriptsIntoTab(tabId) {
        const scripts = [
            "modules/text_sanitizer.js",
            "modules/detector.js",
            "modules/filler.js",
            "content.js",
        ];

        for (const file of scripts) {
            await chrome.scripting.executeScript({
                target: { tabId, allFrames: true },
                files: [file],
            });
        }

        // Also inject the stylesheet
        await chrome.scripting.insertCSS({
            target: { tabId, allFrames: true },
            files: ["content.css"],
        });

        console.log("[QuizWindowFinder] Scripts injected into tab:", tabId);
    }

    /**
     * High-level helper used by popup.js:
     *   1. Finds the best tab to target (quiz pop-up or active tab).
     *   2. Force-injects content scripts if needed.
     *   3. Sends START_SCAN to the content script.
     *
     * @returns {Promise<{tabId: number, wasInjected: boolean, error?: string}>}
     */
    async function resolveAndScan() {
        const tab = await findQuizTab();
        if (!tab) {
            return { tabId: null, wasInjected: false, error: "No tab found." };
        }

        // Try sending START_SCAN. If the content script isn't there yet, inject first.
        const sendScan = () =>
            new Promise((resolve) => {
                chrome.tabs.sendMessage(tab.id, { action: "START_SCAN" }, (response) => {
                    if (chrome.runtime.lastError) {
                        resolve({ success: false, reason: chrome.runtime.lastError.message });
                    } else {
                        resolve({ success: true, response });
                    }
                });
            });

        let result = await sendScan();

        if (!result.success) {
            // Content script missing → inject, then retry once
            console.warn("[QuizWindowFinder] Content script not found, injecting...");
            try {
                await injectScriptsIntoTab(tab.id);
                // Brief pause so injected scripts have time to register their listeners
                await new Promise(r => setTimeout(r, 300));
                result = await sendScan();
                return { tabId: tab.id, wasInjected: true, error: result.success ? undefined : result.reason };
            } catch (err) {
                return { tabId: tab.id, wasInjected: false, error: err.message };
            }
        }

        return { tabId: tab.id, wasInjected: false };
    }

    // Public API
    return { findQuizTab, injectScriptsIntoTab, resolveAndScan, isMoodleQuizUrl };
})();

// Make available to popup.js and background.js (both run in the extension context)
globalThis.QuizWindowFinder = QuizWindowFinder;
