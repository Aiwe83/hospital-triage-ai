"""Endpoints de exportación y entrega del informe.

Dos flujos:
  1. Exportación simple: POST /triage/{id}/export y GET /report.pdf.
     Genera el PDF y lo deja disponible para descargar.
  2. Entrega a Drive con progreso en vivo: POST /deliver +
     GET /deliver/events (SSE). El frontend muestra una barra de
     progreso con los pasos (queued → validating → uploading →
     delivered).

¿Por qué dos APIs?
  La exportación simple es para "quiero el PDF ahora". La entrega
  con SSE es para la demo: muestra el workflow paso a paso, incluido
  el upload a la carpeta clínica sincronizada por Drive Desktop.
"""

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from sse_starlette.sse import EventSourceResponse

from app.services.delivery_workflow import (
    DeliveryProgressEvent, DeliveryResult, delivery_bus, start_delivery,
)
from app.services.report_export import export_report
from app.services.triage_service import triage_service

router = APIRouter(prefix="/triage", tags=["reports"])


@router.post("/{case_id}/export")
async def export_case_report(case_id: str) -> dict:
    """Genera el PDF y devuelve metadatos de la entrega (modo mock por defecto).

    Errores:
      * 404 si el case_id no existe.
      * 409 si el caso existe pero el report_writer aún no ha terminado.
    """
    case = triage_service.get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.report is None:
        # 409 Conflict: el recurso existe pero no está en el estado
        # correcto para la operación. Mejor que 404 (existe) y mejor
        # que 425 Too Early (compatibilidad cliente).
        raise HTTPException(status_code=409, detail="Report not yet available")
    delivery = await export_report(case)
    return delivery


@router.get("/{case_id}/report.pdf")
async def download_report(case_id: str):
    """Descarga directa del PDF.

    Si el caso aún no tiene PDF generado (delivery.artifact.path vacío),
    lo genera al vuelo antes de servirlo — así el usuario nunca recibe
    un 404 inesperado si todavía no se llamó al endpoint de export.
    """
    case = triage_service.get(case_id)
    if not case or case.report is None:
        raise HTTPException(status_code=404, detail="Case or report not found")
    delivery = case.delivery or {}
    # El path puede estar en dos sitios según el flujo: en `delivery.artifact.path`
    # (export simple) o en `delivery.path` (workflow de entrega). Probar ambos.
    path = delivery.get("artifact", {}).get("path") or delivery.get("path")
    if not path:
        # Generación perezosa: si nadie llamó a /export, lo hacemos ahora.
        delivery = await export_report(case)
        path = delivery["artifact"]["path"]
    return FileResponse(path, media_type="application/pdf", filename=f"triage_{case_id}.pdf")


# ---------- Workflow de entrega con progreso en vivo ----------

@router.post("/{case_id}/deliver")
async def deliver_case(case_id: str) -> dict:
    """Lanza el workflow de entrega y devuelve la URL del stream SSE.

    El workflow corre en background (asyncio.create_task) y publica
    eventos en `delivery_bus`. El frontend abre /deliver/events para
    consumirlos.
    """
    case = triage_service.get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.report is None:
        raise HTTPException(status_code=409, detail="Report not yet available")

    # Si se reintenta una entrega, reabrimos la cola para arrancar limpia
    # (sin eventos viejos pendientes que confundan al stream).
    delivery_bus.open(case_id)
    start_delivery(case)
    return {"status": "started", "stream_url": f"/triage/{case_id}/deliver/events"}


@router.get("/{case_id}/deliver/events")
async def deliver_events(case_id: str):
    """Stream SSE del progreso de entrega.

    Tres tipos de evento:
      * `delivery_event` — paso del workflow + porcentaje + mensaje.
      * `delivery_done`  — resultado final (file_id, ruta, modo).
      * `delivery_error` — error fatal; el stream se cierra.
    """
    if triage_service.get(case_id) is None:
        raise HTTPException(status_code=404, detail="Case not found")

    async def gen():
        q = delivery_bus.open(case_id)
        try:
            while True:
                try:
                    # Cada item es una tupla (tipo, payload). El emisor
                    # (delivery_workflow) controla la cardinalidad.
                    kind, payload = await asyncio.wait_for(q.get(), timeout=60.0)
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": "{}"}
                    continue

                if kind == "event":
                    ev: DeliveryProgressEvent = payload
                    yield {"event": "delivery_event", "data": json.dumps(ev.model_dump(mode="json"))}
                elif kind == "done":
                    result: DeliveryResult = payload
                    yield {"event": "delivery_done", "data": json.dumps(result.model_dump(mode="json"))}
                    break  # éxito: cerramos el stream
                elif kind == "error":
                    yield {"event": "delivery_error", "data": json.dumps({"message": payload})}
                    break  # error: cerramos el stream

        finally:
            pass

    return EventSourceResponse(gen())
