"""Punto de entrada del backend FastAPI.

¿Qué hace este módulo?
----------------------
1. Configura logging estructurado al arrancar.
2. Abre conexiones a MongoDB y Elasticsearch antes de aceptar peticiones,
   y las cierra al apagar el proceso (lifespan).
3. Monta los routers de la API (/health, /triage, /reports, etc.).
4. Expone `app = create_app()` — la variable que uvicorn busca cuando
   arranca con `uvicorn app.main:app`.

Convención FastAPI:
  * `lifespan` reemplaza a los antiguos `on_startup` / `on_shutdown`.
  * Es un async context manager: el código antes de `yield` corre al
    arrancar; el código después, al apagar.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.logging import configure_logging, get_logger
from app.core.settings import get_settings
from app.api import health, triage, reports, drive_bridge, handbook, jira as jira_api
from app.db import mongo, elastic

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ciclo de vida del proceso uvicorn.

    Al arrancar: configura logs, conecta Mongo y Elasticsearch.
    Al apagar (Ctrl+C, SIGTERM en docker): cierra ambas conexiones.
    Si Mongo o ES no están disponibles, los clientes lo loguean como
    warning pero NO levantan — el backend sigue arrancando para no
    bloquear la demo (los endpoints degradan con fallbacks).
    """
    configure_logging()
    s = get_settings()
    log.info("startup", model=s.llm_model, export_mode=s.report_export_mode)
    await mongo.connect()
    await elastic.connect()
    yield  # <- aquí FastAPI sirve peticiones hasta que llegue la señal de apagado
    await elastic.disconnect()
    await mongo.disconnect()
    log.info("shutdown")


def create_app() -> FastAPI:
    """Factory de la aplicación.

    Patrón "app factory": en vez de crear `app` a nivel de módulo, lo
    construimos en una función. Ventajas:
      * Tests pueden crear instancias frescas con settings distintos.
      * El orden de imports es más predecible (no se ejecuta nada al
        importar `main`).
    """
    s = get_settings()
    app = FastAPI(
        title="hospital-triage-ai",
        description="Multi-agent triage decision support (MVP).",
        version="0.1.0",
        lifespan=lifespan,
    )
    # CORS: permite que el frontend (Next.js en :3000) llame al backend
    # (:8000). En producción se restringe; en demo solemos abrir "*".
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Cada router agrupa un conjunto de endpoints. Mantenerlos en
    # archivos separados ayuda a que /docs salga bien organizado por tags.
    app.include_router(health.router)        # /health
    app.include_router(triage.router)        # /triage, /triage/{id}, /triage/{id}/events
    app.include_router(reports.router)       # /triage/{id}/export, /report.pdf, /deliver
    app.include_router(drive_bridge.router)  # bridge MCP ↔ Drive Desktop
    app.include_router(handbook.router)      # /handbook/readme, /handbook/claude
    app.include_router(jira_api.router)      # /jira/status, /triage/{id}/jira/close

    @app.get("/", tags=["meta"], summary="Service descriptor")
    async def root() -> dict:
        """Endpoint informativo en la raíz.

        Devuelve la identidad del servicio + un mapa de rutas, para que
        quien abra `http://localhost:8000/` no vea un escueto
        `{"detail":"Not Found"}`. Útil para presentaciones en vivo.
        """
        return {
            "service": "Hospital Triage AI API",
            "status": "running",
            "version": app.version,
            "message": "API en marcha. Consulte /docs para Swagger o /health para el estado del servicio.",
            "available_routes": {
                "health": "/health",
                "docs": "/docs",
                "openapi": "/openapi.json",
                "triage": "/triage",
                "reports": "/triage/{case_id}/export",
                "report_pdf": "/triage/{case_id}/report.pdf",
                "deliver": "/triage/{case_id}/deliver",
                "deliver_events": "/triage/{case_id}/deliver/events",
                "drive_bridge": "/drive-bridge/pending",
            },
            "links": {
                "swagger": "/docs",
                "redoc": "/redoc",
                "health": "/health",
            },
        }

    return app


# Instancia global que uvicorn carga: `uvicorn app.main:app`.
app = create_app()
