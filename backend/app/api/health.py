"""Endpoint /health — sonda de vida del backend.

¿Para qué sirve?
----------------
  * Docker / Kubernetes / monitoring lo golpean cada pocos segundos
    para saber si el contenedor está vivo.
  * El frontend lo usa en su página /docs para mostrar el estado.

Devuelve un dict con la configuración relevante (modelo LLM activo,
si MCP está habilitado, modo de exportación). NO toca Mongo ni ES
para mantenerse barato y rápido — un health check que falla por
dependencias caídas convierte un microcorte en un reinicio completo.
"""

from fastapi import APIRouter
from app.core.settings import get_settings

# `tags` agrupa este endpoint bajo "health" en Swagger UI (/docs).
router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "service": "hospital-triage-ai",
        "llm_model": s.llm_model,          # útil para saber qué modelo está sirviendo
        "mcp_enabled": s.mcp_enabled,      # True si el MCP server está activo
        "export_mode": s.report_export_mode,  # mock | drive | gmail | bridge
    }
