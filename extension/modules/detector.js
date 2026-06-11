class SurveyDetector {
    static scanPage() {
        const questions = [];
        const inputs = document.querySelectorAll('input[type="text"], input[type="radio"], input[type="checkbox"], textarea, select');
        
        inputs.forEach((input, index) => {
            const type = input.type;
            const name = input.name || `unnamed_${index}`;
            const id = input.id || `auto_id_${index}`;
            if (!input.id) input.id = id;

            let questionText = "Pregunta sin título";
            let optionLabel = "";

            // --- 1. EXTRAER TEXTOS (Heurística Avanzada) ---
            
            // Caso A: Tablas de emparejamiento (Moodle)
            if (input.tagName.toLowerCase() === 'select' && input.closest('tr')) {
                const row = input.closest('tr');
                const firstCell = row.querySelector('td:first-child');
                const mainQuestionContainer = input.closest('.que');
                
                if (firstCell && mainQuestionContainer) {
                    const mainText = mainQuestionContainer.querySelector('.qtext').innerText.trim();
                    questionText = `${mainText} -> ${firstCell.innerText.trim()}`;
                }
            } 
            // Caso B: Opciones Múltiples (Radios / Checkboxes)
            else if (type === 'radio' || type === 'checkbox') {
                // Aquí extraemos la OPCIÓN
                const optNode = document.querySelector(`label[for="${id}"]`) || input.parentElement;
                let rawOptionText = optNode ? optNode.innerText : input.value;
                
                // Limpieza de basura: quitar saltos de línea, caracteres raros, mantener solo alfanuméricos y puntuación normal
                optionLabel = rawOptionText.replace(/[\n\r]+/g, ' ')
                                           .replace(/[^\w\s\.\,\-\áéíóúÁÉÍÓÚñÑ]/g, '')
                                           .trim();

                // Aquí subimos en el HTML para extraer la verdadera PREGUNTA
                const mainContainer = input.closest('.que');      // Estructura Moodle
                const fieldset = input.closest('fieldset');       // Estructura HTML estándar
                
                if (mainContainer && mainContainer.querySelector('.qtext')) {
                    questionText = mainContainer.querySelector('.qtext').innerText.trim();
                } else if (fieldset && fieldset.querySelector('legend')) {
                    questionText = fieldset.querySelector('legend').innerText.trim();
                } else {
                    // Fallback
                    const parentText = input.closest('.question, .form-group');
                    if (parentText) questionText = parentText.innerText.split('\n')[0].trim();
                }
            }
            // Caso C: Texto libre y Selectboxes normales
            else {
                let label = document.querySelector(`label[for="${id}"]`);
                if (label) {
                    questionText = label.innerText.trim();
                } else {
                    const mainContainer = input.closest('.que');
                    if (mainContainer && mainContainer.querySelector('.qtext')) {
                        questionText = mainContainer.querySelector('.qtext').innerText.trim();
                    }
                }
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
                const options = Array.from(input.options).map(opt => opt.innerText.trim());
                questions.push({ element_id: id, question_text: questionText, question_type: "dropdown", options: options });
            }
        });

        console.log("Survey Copilot: Detectadas", questions);
        return questions;
    }
}

window.SurveyDetector = SurveyDetector;