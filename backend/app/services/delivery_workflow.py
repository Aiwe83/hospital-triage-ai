"""Workflow de entrega multi-paso.

Emite eventos de progreso (queued → validating_report → generating_pdf →
connecting_drive → uploading → verifying → delivered) a través de una
cola async dedicada por caso. La capa API hace stream de esos eventos
como SSE.

Los pasos envuelven el trabajo real con pequeñas pausas artificiales
para que la demo en vivo se sienta animada (sin ellas el workflow
entero termina en menos de un segundo).
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel

from app.core.logging import get_logger
from app.core.settings import get_settings
from app.db.cases_repo import cases_repo
from app.schemas.triage import TriageCase
from app.services.drive_adapter import DriveAdapter, UploadResult, get_drive_adapter
from app.services.report_pdf import render_triage_pdf
from app.services import jira_hooks

log = get_logger(__name__)


# ---------- Esquemas ----------

class DeliveryProgressEvent(BaseModel):
    case_id: str
    step: str
    progress: int
    message: str
    timestamp: datetime
    data: dict = {}


class DeliveryResult(BaseModel):
    case_id: str
    status: str  # delivered | error
    mode: str
    drive_file_id: Optional[str] = None
    drive_view_url: Optional[str] = None
    folder: Optional[str] = None
    size_bytes: Optional[int] = None
    path: Optional[str] = None
    finished_at: datetime
    note: str = ""


# ---------- Bus ----------

class DeliveryBus:
    """Colas asyncio por caso para los eventos de entrega.

    El centinela `("done", result)` cierra el stream. `("error", message)`
    propaga un error terminal.
    """

    def __init__(self) -> None:
        self._queues: Dict[str, asyncio.Queue] = {}
        self._results: Dict[str, DeliveryResult] = {}

    def open(self, case_id: str) -> asyncio.Queue:
        if case_id not in self._queues:
            self._queues[case_id] = asyncio.Queue()
        return self._queues[case_id]

    def get(self, case_id: str) -> asyncio.Queue | None:
        return self._queues.get(case_id)

    def get_result(self, case_id: str) -> DeliveryResult | None:
        return self._results.get(case_id)

    async def publish_event(self, case_id: str, event: DeliveryProgressEvent) -> None:
        await self.open(case_id).put(("event", event))

    async def publish_done(self, case_id: str, result: DeliveryResult) -> None:
        self._results[case_id] = result
        await self.open(case_id).put(("done", result))

    async def publish_error(self, case_id: str, message: str) -> None:
        await self.open(case_id).put(("error", message))


delivery_bus = DeliveryBus()


# ---------- Pasos del workflow ----------

async def _emit(case_id: str, step: str, progress: int, message: str, data: dict | None = None) -> None:
    await delivery_bus.publish_event(case_id, DeliveryProgressEvent(
        case_id=case_id,
        step=step,
        progress=progress,
        message=message,
        timestamp=datetime.utcnow(),
        data=data or {},
    ))


async def _run_delivery(case: TriageCase, adapter: DriveAdapter) -> None:
    cid = case.case_id
    try:
        await _emit(cid, "queued", 5, "Solicitud de envío en cola.")
        await asyncio.sleep(0.3)

        await _emit(cid, "validating_report", 15, "Comprobando que el informe contiene la información mínima.")
        if case.report is None:
            raise RuntimeError("El caso aún no tiene informe generado.")
        if not case.report.summary:
            raise RuntimeError("El informe no contiene resumen clínico.")
        await asyncio.sleep(0.5)

        await _emit(cid, "generating_pdf", 35, "Renderizando informe en formato PDF.")
        pdf_bytes = render_triage_pdf(case)
        size_kb = len(pdf_bytes) / 1024
        await asyncio.sleep(0.4)

        await _emit(
            cid, "connecting_drive", 50,
            f"Estableciendo conexión con Google Drive ({adapter.name}).",
            data={"size_kb": round(size_kb, 1)},
        )
        await asyncio.sleep(0.4)

        await _emit(cid, "uploading", 70, "Subiendo archivo al consultorio del facultativo.")
        # Heartbeat — emite updates de uploading periódicos mientras el
        # adapter hace su trabajo. Curva asintótica hacia 95 para que la
        # barra nunca se quede congelada en un mismo número aunque el
        # bridge tarde minutos en responder.
        HB_CAP = 95
        HB_INTERVAL = 1.5

        async def _heartbeat():
            pct = 70.0
            while True:
                await asyncio.sleep(HB_INTERVAL)
                # Paso menguante → aproximación suave sin tocar nunca el tope.
                pct += max(0.4, (HB_CAP - pct) * 0.12)
                pct = min(pct, HB_CAP - 0.5)
                await _emit(
                    cid, "uploading", int(pct),
                    "Transferencia en curso hacia Google Drive…",
                )

        hb_task = asyncio.create_task(_heartbeat())
        # Techo duro para que un adapter mal portado nunca congele el workflow.
        settings = get_settings()
        hard_timeout = float(settings.mcp_drive_timeout) + 30.0
        try:
            try:
                upload: UploadResult = await asyncio.wait_for(
                    adapter.upload(
                        filename=f"triage_{cid}.pdf",
                        content=pdf_bytes,
                        patient_id=cid,
                    ),
                    timeout=hard_timeout,
                )
            except asyncio.TimeoutError:
                log.warning("delivery_adapter_hard_timeout", case_id=cid, seconds=hard_timeout)
                raise RuntimeError(
                    f"El adaptador de Drive no respondió en {hard_timeout:.0f}s. "
                    "Reintente el envío."
                )
        finally:
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass

        await _emit(
            cid, "uploading", 95,
            "Transferencia completada. Cerrando subida.",
            data={"mode": upload.mode},
        )
        await _emit(cid, "verifying", 97, "Verificando integridad y trazabilidad en Drive.")
        await asyncio.sleep(0.3)

        result = DeliveryResult(
            case_id=cid,
            status="delivered",
            mode=upload.mode,
            drive_file_id=upload.drive_file_id,
            drive_view_url=upload.drive_view_url,
            folder=upload.folder,
            size_bytes=upload.size_bytes,
            path=upload.path,
            finished_at=datetime.utcnow(),
            note=upload.note,
        )

        await _emit(
            cid, "delivered", 100,
            "Informe entregado correctamente en la carpeta clínica.",
            data={"file_id": upload.drive_file_id, "folder": upload.folder},
        )

        # Persistir la info final de entrega en el caso
        delivery_payload = result.model_dump(mode="json")
        await cases_repo.record_delivery(cid, delivery_payload)
        case.delivery = delivery_payload

        # Canal lateral: dejar un comentario en Jira con el filename + path final.
        try:
            await jira_hooks.on_delivered(cid, case.jira_key, delivery_payload)
        except Exception as e:
            log.warning("jira_on_delivered_failed", error=str(e), case_id=cid)

        await delivery_bus.publish_done(cid, result)

    except Exception as e:
        log.exception("delivery_failed", case_id=cid)
        await _emit(cid, "error", 0, f"Error en el envío: {e}")
        await delivery_bus.publish_error(cid, str(e))


# ---------- Punto de entrada público ----------

def start_delivery(case: TriageCase) -> None:
    """Programa el workflow de entrega en el event loop."""
    if case.report is None:
        raise RuntimeError("Cannot deliver a case without a report.")
    adapter = get_drive_adapter()
    asyncio.create_task(_run_delivery(case, adapter))
