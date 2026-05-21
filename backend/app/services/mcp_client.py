"""Cliente para el servidor MCP local (herramientas del hospital).

MCP (Model Context Protocol): protocolo de Anthropic para exponer
"herramientas" a agentes LLM. En este proyecto el MCP server simula
sistemas hospitalarios reales (LIS, RIS, gestor de camas, etc.).

¿Por qué HTTP en vez de stdio?
------------------------------
MCP "real" usa stdio (proceso hijo, JSON-RPC). Aquí usamos una facade
HTTP fina porque:
  * Es más fácil debuggear en directo durante la demo (curl, devtools).
  * Permite que frontend y MCP server vivan en contenedores separados.
  * Una migración a stdio MCP queda trivial: cambiar este cliente.

Herramientas expuestas por el MCP server:
  * `/tools/hospital_context` — devuelve pruebas disponibles, recursos
    y tiempo estimado de espera para las categorías sospechadas.
  * `/tools/send_report_to_drive` — copia el PDF a la carpeta clínica
    sincronizada por Google Drive Desktop.
"""

import httpx
from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)


async def fetch_hospital_context(
    suspected_categories: list[str] | None = None,
    priority: str | None = None,
) -> dict:
    """Pide al MCP el contexto operacional del hospital.

    Lo invoca el nodo `hospital_systems_executor` del grafo. Si MCP
    está deshabilitado en settings, levantamos `RuntimeError` — el
    nodo lo captura y aplica su fallback (ctx con `fallback: True`).

    Args:
      suspected_categories: lista de categorías clínicas que el
        analista sospecha (cardiac, respiratory, neurological, …).
        El MCP filtra qué pruebas/recursos son relevantes.
      priority: prioridad sugerida (critical, urgent, …). Influye
        en el tiempo estimado de espera.
    """
    s = get_settings()
    if not s.mcp_enabled:
        # Convertirlo en excepción mantiene el contrato simple:
        # quien llame decide si caer al fallback o propagar el error.
        raise RuntimeError("MCP disabled")
    url = f"{s.mcp_server_url.rstrip('/')}/tools/hospital_context"
    payload = {
        "suspected_categories": suspected_categories or [],
        "priority": priority,
    }
    # `timeout=10.0`: el MCP es local, si tarda más es que algo va mal.
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(url, json=payload)
        # `raise_for_status` convierte 4xx/5xx en excepción → captura
        # en el nodo del grafo.
        r.raise_for_status()
        return r.json()
