"""Endpoints HTTP del flujo de triage.

Tres rutas:
  * POST /triage              — crea un caso y arranca el grafo de agentes.
  * GET  /triage/{case_id}    — devuelve el caso completo (estado actual).
  * GET  /triage/{case_id}/events — stream SSE de eventos de los agentes
                                    (lo que mueve la escena hospitalaria).

SSE (Server-Sent Events) vs WebSocket:
  Usamos SSE porque la comunicación es 100% backend → frontend (no
  necesitamos que el cliente mande datos por el mismo canal). SSE
  reconecta automáticamente y atraviesa proxies HTTP convencionales.
"""

import asyncio
import json
from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from app.agents.events import bus
from app.schemas.triage import TriageIntake
from app.services.triage_service import triage_service

# `prefix="/triage"` evita repetirlo en cada decorator.
router = APIRouter(prefix="/triage", tags=["triage"])


@router.post("")
async def create_triage(intake: TriageIntake) -> dict:
    """Crea un caso y lanza el workflow LangGraph en background.

    Devuelve inmediatamente con el case_id y la URL del stream SSE —
    NO espera a que termine el workflow (puede tardar 10-30 segundos).
    El frontend abre el EventSource con `stream_url` para ver el
    progreso en vivo.
    """
    case = await triage_service.start(intake)
    return {
        "case_id": case.case_id,
        "status": case.status,
        "stream_url": f"/triage/{case.case_id}/events",
    }


@router.get("/{case_id}")
async def get_triage(case_id: str) -> dict:
    """Lee el caso completo. Útil para refrescar la UI tras un reload."""
    case = triage_service.get(case_id)
    if not case:
        # 404 estándar; el frontend muestra "caso no encontrado".
        raise HTTPException(status_code=404, detail="Case not found")
    # mode="json" garantiza que datetimes / Enums salgan serializables.
    return case.model_dump(mode="json")


@router.get("/{case_id}/events")
async def stream_triage(case_id: str):
    """Stream SSE de eventos de los agentes.

    El cliente abre un EventSource y recibe eventos `agent_event` con
    el JSON de cada AgentEvent. Cuando el workflow termina, llega un
    evento `done` y la conexión se cierra.

    Heartbeats: si pasan 60s sin eventos, enviamos `heartbeat` vacío
    para que proxies (nginx, traefik) no cierren la conexión por
    inactividad.
    """
    if triage_service.get(case_id) is None:
        raise HTTPException(status_code=404, detail="Case not found")

    async def event_generator():
        # bus.open() devuelve la cola del caso (creándola si no existe).
        q = bus.open(case_id)
        try:
            while True:
                try:
                    # wait_for con timeout = corto-circuito para el heartbeat.
                    item = await asyncio.wait_for(q.get(), timeout=60.0)
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
                    continue
                # Centinela None = fin del stream (lo pone bus.close()).
                if item is None:
                    yield {"event": "done", "data": "{}"}
                    break
                yield {
                    "event": "agent_event",
                    "data": json.dumps(item.model_dump(mode="json")),
                }
        finally:
            # Sin lógica de cleanup aquí: la cola la limpia el bus al
            # publicar el centinela. Mantenemos el `finally` para futuro.
            pass

    return EventSourceResponse(event_generator())
