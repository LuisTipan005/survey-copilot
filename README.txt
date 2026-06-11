# Survey Copilot — Asistente Local de IA

Un "copilot invisible" basado en una extensión MV3 de Chrome y un backend de FastAPI local con Ollama. Escanea formularios web y los responde automáticamente simulando la escritura humana y utilizando tu propio contexto.

## Requisitos
- Python 3.11+
- Ollama instalado localmente
- Modelo: `qwen2.5:3b` (`ollama run qwen2.5:3b`)

## Instalación y Ejecución

### 1. Levantar el Backend
Navega a la carpeta `/backend`:
\`\`\`bash
python -m venv venv
source venv/Scripts/activate  # (En Windows)
pip install -r requirements.txt
python run.py
\`\`\`
El backend correrá en `http://localhost:8000`.

### 2. Instalar la Extensión de Chrome
1. Abre Chrome y ve a `chrome://extensions/`.
2. Activa el "Modo Desarrollador" (Developer mode).
3. Haz clic en "Cargar descomprimida" (Load unpacked) y selecciona la carpeta `/extension` de este proyecto.

### 3. Uso
1. Abre el archivo `tests/test_pages/simple_survey.html` en Chrome.
2. Haz clic en el ícono de la extensión en la barra superior.
3. Asegúrate de que diga "Backend Online".
4. Configura tu perfil (ej. Estudiante de Ingeniería).
5. Presiona "Scan Current Page".
6. Observa cómo el widget inferior te notifica y autocompleta el formulario.