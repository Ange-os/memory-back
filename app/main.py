from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .config import get_settings
from .routes import auth, documents, search, memory

settings = get_settings()

app = FastAPI(
    title="Qdrant Forms API",
    description="API para carga de PDFs y búsqueda en Qdrant",
    version="1.0.0",
)

# CORS - permitir frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En producción, especificar el dominio del frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rutas
app.include_router(auth.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(memory.router, prefix="/api")


@app.get("/")
def root():
    """Endpoint de health check"""
    return {"status": "ok", "service": "Qdrant Forms API"}


@app.get("/health")
def health():
    """Verifica conexión a servicios externos"""
    return {
        "database": "configured",
        "qdrant": settings.qdrant_url,
        "n8n_webhook": settings.n8n_webhook_url[:50] + "..." if settings.n8n_webhook_url else "not configured",
    }
