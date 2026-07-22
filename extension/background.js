importScripts("modules/quiz_window_finder.js");

// ── Constants ─────────────────────────────────────────────────────────────────
const API_URL       = "http://localhost:8000/api/survey/analyze";
const BATCH_API_URL = "http://localhost:8000/api/survey/analyze_batch";

// ── Master Scan (keyboard shortcut + popup) ───────────────────────────────────
async function executeMasterScan() {
    try {
        console.log("[Survey Copilot] Iniciando Master Scan...");
        const result = await globalThis.QuizWindowFinder.resolveAndScan();
        if (result.error) {
            console.error("[Survey Copilot] Error en escaneo:", result.error);
            return { success: false, error: result.error };
        }
        return { success: true, tabId: result.tabId, wasInjected: result.wasInjected };
    } catch (err) {
        console.error("[Survey Copilot] Fallo el escaneo maestro:", err);
        return { success: false, error: err.message };
    }
}

// ── Keyboard shortcut (Alt+S) ─────────────────────────────────────────────────
chrome.commands.onCommand.addListener((command) => {
    if (command === "scan-page") {
        console.log("[Survey Copilot] Atajo de teclado detectado:", command);
        executeMasterScan();
    }
});

// ── Message router ────────────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {

    if (request.action === "TRIGGER_SCAN") {
        executeMasterScan().then(result => sendResponse(result));
        return true;
    }

    // ── Single-question / small-batch (≤ 3 questions) ──────────────────────────
    if (request.action === "ANALYZE_SURVEY") {
        handleSurveyAnalysis(request.payload)
            .then(data => sendResponse({ success: true, data }))
            .catch(error => sendResponse({ success: false, error: error.message }));
        return true;
    }

    // ── Large-batch (> 3 questions) — parallel Semaphore(3) on the backend ─────
    if (request.action === "ANALYZE_BATCH") {
        handleBatchAnalysis(request.payload, sender.tab?.id)
            .then(data => sendResponse({ success: true, data }))
            .catch(error => sendResponse({ success: false, error: error.message }));
        return true;
    }
});

// ── Sequential handler: one call per question, used for mode A ─────────────────
async function handleSurveyAnalysis(payload) {
    try {
        const response = await fetch(API_URL, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify(payload),
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data = await response.json();
        _saveHistory(payload, data);
        return data;

    } catch (error) {
        console.error("Survey Copilot — backend error (sequential):", error);
        throw error;
    }
}

// ── Batch handler: sends all questions to the /analyze_batch endpoint,
//    then streams BATCH_PROGRESS events back to the content script. ────────────
async function handleBatchAnalysis(payload, tabId) {
    const questions = payload.questions || [];
    const total     = questions.length;
    console.log(`[Survey Copilot BG] Batch mode — ${total} questions → Semaphore(3) on backend`);

    try {
        // Push an initial progress event immediately
        _pushProgress(tabId, 0, total);

        // Single POST — backend processes with asyncio.Semaphore(3) internally.
        // The endpoint returns a streaming-friendly response: each answer is
        // flushed as it completes (ndjson lines). We read the stream here and
        // push progress as each line arrives.
        const response = await fetch(BATCH_API_URL, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify(payload),
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        // Read the NDJSON stream — each line is one completed answer JSON.
        const reader  = response.body.getReader();
        const decoder = new TextDecoder();
        let   buffer  = "";
        const answers = [];

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop(); // keep the incomplete last chunk

            for (const line of lines) {
                const trimmed = line.trim();
                if (!trimmed) continue;
                try {
                    const answerObj = JSON.parse(trimmed);
                    answers.push(answerObj);
                    _pushProgress(tabId, answers.length, total);
                } catch (parseErr) {
                    console.warn("[Survey Copilot BG] Could not parse NDJSON line:", trimmed);
                }
            }
        }

        // Flush any remaining buffered content
        if (buffer.trim()) {
            try { answers.push(JSON.parse(buffer.trim())); } catch (_) {}
        }

        _pushProgress(tabId, total, total); // ensure 100%

        // Assemble a response object matching the shape content.js expects
        const result = {
            answers,
            model_used:          payload.model_used || "batch",
            processing_time_ms:  0,
        };

        _saveHistory(payload, result);
        return result;

    } catch (error) {
        console.error("Survey Copilot — backend error (batch):", error);
        throw error;
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Send a BATCH_PROGRESS message to the active content script tab. */
function _pushProgress(tabId, current, total) {
    if (!tabId) return;
    chrome.tabs.sendMessage(tabId, {
        action:  "BATCH_PROGRESS",
        current,
        total,
    }).catch(() => { /* tab may have navigated away */ });
}

/** Persist a lightweight history entry in chrome.storage.local. */
function _saveHistory(payload, data) {
    chrome.storage.local.get({ quizHistory: [] }, (res) => {
        const history = res.quizHistory;
        history.unshift({
            timestamp:         new Date().toISOString(),
            questionsAnalyzed: payload.questions ? payload.questions.length : 0,
            modelUsed:         data.model_used || "Unknown",
            processingTime:    data.processing_time_ms || 0,
        });
        if (history.length > 50) history.pop();
        chrome.storage.local.set({ quizHistory: history });
    });
}