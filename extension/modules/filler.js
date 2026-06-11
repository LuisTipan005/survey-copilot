// extension/modules/filler.js

class SurveyFiller {
    static async fillAnswers(answers, detectedQuestions) {
        for (const ans of answers) {
            // Buscamos la pregunta original en nuestro mapeo
            const qMap = detectedQuestions.find(q => q.question_text === ans.question_text);
            if (!qMap) continue;

            if (qMap.question_type === 'text') {
                const element = document.getElementById(qMap.element_id);
                if (element) {
                    await this.simulateTyping(element, ans.answer);
                }
            } 
            else if (qMap.question_type === 'single' || qMap.question_type === 'multi') {
                if (ans.selected_options && ans.selected_options.length > 0) {
                    ans.selected_options.forEach(index => {
                        if (qMap.element_ids[index]) {
                            const radioOrCheck = document.getElementById(qMap.element_ids[index]);
                            if (radioOrCheck && !radioOrCheck.checked) {
                                radioOrCheck.click();
                            }
                        }
                    });
                }
            }
            else if (qMap.question_type === 'dropdown') {
                const element = document.getElementById(qMap.element_id);
                if (element && ans.selected_options && ans.selected_options.length > 0) {
                    element.selectedIndex = ans.selected_options[0];
                    element.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }
        }
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