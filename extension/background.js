// Escuchar mensajes desde el content.js
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "ANALYZE_SURVEY") {
        handleSurveyAnalysis(request.payload)
            .then(data => sendResponse({ success: true, data: data }))
            .catch(error => sendResponse({ success: false, error: error.message }));
        
        // Retornar true indica que la respuesta será asíncrona
        return true; 
    }
});

// Función para comunicarse con el backend en FastAPI
async function handleSurveyAnalysis(payload) {
    const API_URL = "http://localhost:8000/api/survey/analyze";
    
    try {
        const response = await fetch(API_URL, {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();
        return data;
    } catch (error) {
        console.error("Survey Copilot - Error de conexión con el backend:", error);
        throw error;
    }
}