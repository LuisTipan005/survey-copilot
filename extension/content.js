// extension/content.js

// Escuchar comandos desde el popup
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "START_SCAN") {
        startCopilotFlow();
        sendResponse({ status: "started" });
    }
});

async function startCopilotFlow() {
    showWidgetStatus("Detectando preguntas...");
    
    // 1. Detectar
    const questions = window.SurveyDetector.scanPage();
    if (questions.length === 0) {
        showWidgetStatus("No se encontraron formularios.", true);
        return;
    }

    // 2. Obtener perfil del storage
    chrome.storage.local.get(['userProfile'], async (result) => {
        const profile = result.userProfile || "Usuario estándar";
        
        const payload = {
            questions: questions,
            user_profile: profile,
            survey_context: document.title
        };

        showWidgetStatus(`IA Pensando (${questions.length} preguntas)...`);

        // 3. Enviar al background script para que haga la petición a FastAPI
        chrome.runtime.sendMessage({ action: "ANALYZE_SURVEY", payload: payload }, async (response) => {
            if (response.success) {
                showWidgetStatus("Autocompletando...");
                await window.SurveyFiller.fillAnswers(response.data.answers, questions);
                showWidgetStatus("¡Completado! ✨", true);
            } else {
                showWidgetStatus("Error de IA: Revisa consola", true);
                console.error(response.error);
            }
        });
    });
}

// Widget visual inyectado en la página
function showWidgetStatus(text, hideAfter = false) {
    let widget = document.getElementById('survey-copilot-widget');
    if (!widget) {
        widget = document.createElement('div');
        widget.id = 'survey-copilot-widget';
        document.body.appendChild(widget);
    }
    widget.innerText = text;
    widget.style.display = 'block';

    if (hideAfter) {
        setTimeout(() => {
            widget.style.display = 'none';
        }, 4000);
    }
}   