// extension/content.js

// ── Constants ─────────────────────────────────────────────────────────────────
const SEQUENTIAL_THRESHOLD = 3; // ≤ this → sequential mode; > this → batch mode

// ── Message listener (from popup / keyboard shortcut) ─────────────────────────
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "START_SCAN") {
        startCopilotFlow();
        sendResponse({ status: "started" });
    }

    // Progress updates pushed from background.js during batch processing
    if (request.action === "BATCH_PROGRESS") {
        updateProgressOverlay(request.current, request.total);
    }
});

// ── Main orchestration ────────────────────────────────────────────────────────
async function startCopilotFlow() {
    showWidgetStatus("Detectando preguntas...");

    // 1. Detect questions
    const questions = window.SurveyDetector.scanPage();
    if (questions.length === 0) {
        showWidgetStatus("No se encontraron formularios.", true);
        return;
    }

    // 2. Load user profile
    const profile = await new Promise(resolve =>
        chrome.storage.local.get(['userProfile'], r => resolve(r.userProfile || "Usuario estándar"))
    );

    const surveyContext = document.title;

    // 3. Choose execution mode
    if (questions.length <= SEQUENTIAL_THRESHOLD) {
        await runSequentialMode(questions, profile, surveyContext);
    } else {
        await runBatchMode(questions, profile, surveyContext);
    }
}

// ── Mode A: Sequential (low-latency, ≤ 3 questions) ─────────────────────────
async function runSequentialMode(questions, profile, surveyContext) {
    showWidgetStatus(`Modo Secuencial — ${questions.length} pregunta(s)...`);
    console.log(`[Survey Copilot] Sequential mode: ${questions.length} question(s).`);

    const collectedAnswers = [];

    for (let i = 0; i < questions.length; i++) {
        const q = questions[i];
        showWidgetStatus(`Analizando ${i + 1} de ${questions.length}...`);

        const payload = {
            questions: [q],
            user_profile: profile,
            survey_context: surveyContext,
        };

        const response = await sendAnalyze(payload);

        if (response.success && response.data?.answers?.length > 0) {
            const ans = response.data.answers[0];
            collectedAnswers.push(ans);

            // Inject answer immediately (low-latency feel)
            await window.SurveyFiller.fillAnswers([ans], [q]);
            console.log(`[Survey Copilot] Sequential: filled question ${i + 1}/${questions.length}`);
        } else {
            console.warn(`[Survey Copilot] Sequential: no answer for question ${i + 1}`, response.error);
        }
    }

    showWidgetStatus(`¡Completado! ✨ (${collectedAnswers.length}/${questions.length})`, true);
}

// ── Mode B: Batch (parallel Semaphore(3), > 3 questions) ─────────────────────
async function runBatchMode(questions, profile, surveyContext) {
    console.log(`[Survey Copilot] Batch mode: ${questions.length} question(s).`);
    showProgressOverlay(0, questions.length);

    const payload = {
        questions: questions,
        user_profile: profile,
        survey_context: surveyContext,
    };

    // Kick off the batch request — background.js handles Semaphore(3) parallelism
    // and sends BATCH_PROGRESS messages back as each question completes.
    const response = await new Promise((resolve) => {
        chrome.runtime.sendMessage({ action: "ANALYZE_BATCH", payload }, resolve);
    });

    removeProgressOverlay();

    if (response.success && response.data?.answers) {
        showWidgetStatus("Autocompletando respuestas...");
        await window.SurveyFiller.fillAnswers(response.data.answers, questions);
        showWidgetStatus(`¡Completado! ✨ (${response.data.answers.length}/${questions.length})`, true);
    } else {
        showWidgetStatus("Error en modo batch — revisa consola", true);
        console.error("[Survey Copilot] Batch error:", response.error);
    }
}

// ── Backend helper ────────────────────────────────────────────────────────────
function sendAnalyze(payload) {
    return new Promise(resolve =>
        chrome.runtime.sendMessage({ action: "ANALYZE_SURVEY", payload }, resolve)
    );
}

// ── Progress Overlay UI ───────────────────────────────────────────────────────
const OVERLAY_ID = "sc-progress-overlay";

function showProgressOverlay(current, total) {
    removeProgressOverlay();

    const overlay = document.createElement("div");
    overlay.id = OVERLAY_ID;
    overlay.innerHTML = `
        <div class="sc-pill">
            <div class="sc-pill-icon">⚡</div>
            <div class="sc-pill-body">
                <div class="sc-pill-label" id="sc-label">Procesando ${current} de ${total}…</div>
                <div class="sc-bar-track">
                    <div class="sc-bar-fill" id="sc-bar" style="width: ${total > 0 ? Math.round((current / total) * 100) : 0}%"></div>
                </div>
            </div>
            <div class="sc-pill-count" id="sc-count">${current}/${total}</div>
        </div>
    `;

    const style = document.createElement("style");
    style.id = "sc-progress-style";
    style.textContent = `
        #${OVERLAY_ID} {
            position: fixed;
            bottom: 28px;
            right: 28px;
            z-index: 2147483647;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            animation: scSlideIn 0.35s cubic-bezier(0.34, 1.56, 0.64, 1) both;
        }
        @keyframes scSlideIn {
            from { opacity: 0; transform: translateY(20px) scale(0.95); }
            to   { opacity: 1; transform: translateY(0)    scale(1);    }
        }
        .sc-pill {
            display: flex;
            align-items: center;
            gap: 12px;
            background: rgba(15, 23, 42, 0.92);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(99, 102, 241, 0.45);
            border-radius: 16px;
            padding: 14px 18px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.5), 0 0 0 1px rgba(99,102,241,0.2);
            min-width: 270px;
        }
        .sc-pill-icon { font-size: 1.4rem; flex-shrink: 0; }
        .sc-pill-body { flex: 1; min-width: 0; }
        .sc-pill-label {
            color: #e2e8f0;
            font-size: 0.82rem;
            font-weight: 600;
            margin-bottom: 7px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .sc-bar-track {
            height: 5px;
            background: rgba(255,255,255,0.1);
            border-radius: 99px;
            overflow: hidden;
        }
        .sc-bar-fill {
            height: 100%;
            background: linear-gradient(90deg, #6366f1, #a78bfa);
            border-radius: 99px;
            transition: width 0.4s cubic-bezier(0.4,0,0.2,1);
        }
        .sc-pill-count {
            color: #a78bfa;
            font-size: 0.78rem;
            font-weight: 700;
            flex-shrink: 0;
        }
    `;

    document.head.appendChild(style);
    document.body.appendChild(overlay);
}

function updateProgressOverlay(current, total) {
    const label = document.getElementById("sc-label");
    const bar   = document.getElementById("sc-bar");
    const count = document.getElementById("sc-count");
    if (label) label.textContent = `Procesando ${current} de ${total}…`;
    if (bar)   bar.style.width   = `${Math.round((current / total) * 100)}%`;
    if (count) count.textContent = `${current}/${total}`;
}

function removeProgressOverlay() {
    document.getElementById(OVERLAY_ID)?.remove();
    document.getElementById("sc-progress-style")?.remove();
}

// ── Lightweight logger (replaces old widget) ───────────────────────────────────
function showWidgetStatus(text, hideAfter = false) {
    console.log(`[Survey Copilot] ${text}`);
    // If a progress overlay is active, update its label too
    const label = document.getElementById("sc-label");
    if (label) label.textContent = text;
}