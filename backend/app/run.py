import uvicorn

if __name__ == "__main__":
    # Ejecuta el servidor FastAPI en el puerto 8000 con recarga automática
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)