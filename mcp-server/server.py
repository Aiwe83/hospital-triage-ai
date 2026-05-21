"""Servidor MCP local — herramientas del hospital (facade HTTP).

Exponemos las herramientas por HTTP para simplicidad y para poder
depurarlas en vivo durante la demo. El agente del backend
(`hospital_systems_executor`) actúa como cliente MCP.

Herramientas:
  - GET  /tools                            -> lista las herramientas disponibles
  - POST /tools/get_available_tests        -> pruebas simuladas para un caso
  - POST /tools/get_resource_status        -> disponibilidad simulada de boxes/oxígeno/monitores
  - POST /tools/get_estimated_wait_time    -> estimación de espera por prioridad
  - POST /tools/hospital_context           -> contexto agregado (one-shot)
  - POST /tools/send_report_to_drive       -> copia el PDF médico a la carpeta sincronizada por Drive Desktop
  - GET  /tools/sync_status                -> informa si DRIVE_SYNC_FOLDER está listo

La integración con Drive es **deliberadamente simple**: la herramienta
MCP solo copia el PDF a una carpeta local que Google Drive Desktop ya
está sincronizando con la nube. Sin Google API, sin OAuth, sin service
account, sin credenciales.
"""

import logging
import os
import random
import re
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import jira_tools

logger = logging.getLogger("mcp.hospital")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="hospital-triage-ai MCP server", version="0.4.0")
app.include_router(jira_tools.router)


# ---------- Esquemas ----------

class TestsRequest(BaseModel):
    suspected_categories: list[str] = []


class WaitRequest(BaseModel):
    priority: str | None = None


class ContextRequest(BaseModel):
    suspected_categories: list[str] = []
    priority: str | None = None


class SendReportRequest(BaseModel):
    report_path: str = Field(..., min_length=1, description="Ruta absoluta del PDF médico a copiar.")
    patient_id: str = Field(..., min_length=1, description="Identificador de paciente / caso usado en el filename canónico.")
    optional_filename: str | None = Field(
        default=None,
        description="Si se proporciona, sobrescribe el nombre autogenerado `informe_<patient>_<ts>.pdf`.",
    )


# ---------- Estado hospitalario simulado (sin cambios) ----------

TESTS_BY_CATEGORY: dict[str, list[str]] = {
    "respiratory": ["chest_xray", "abg", "covid_pcr", "d_dimer"],
    "cardiac": ["ecg_12lead", "troponin", "chest_xray", "echo_bedside"],
    "neurological": ["ct_head_noncontrast", "glucose", "inr", "platelets"],
    "abdominal": ["abdominal_us", "lipase", "lactate", "beta_hcg"],
    "infection_sepsis": ["blood_cultures_x2", "lactate", "cbc", "crp"],
    "allergy": ["tryptase", "cbc"],
    "pediatric": ["pediatric_vitals_continuous", "viral_panel"],
    "airway_breathing_circulation": ["abg", "chest_xray", "ecg_12lead"],
}

BASE_TESTS = ["cbc", "bmp", "urinalysis"]


def _select_tests(categories: list[str]) -> list[str]:
    out: list[str] = list(BASE_TESTS)
    for c in categories:
        out.extend(TESTS_BY_CATEGORY.get(c.lower(), []))
    seen = set()
    return [t for t in out if not (t in seen or seen.add(t))]


def _resource_status() -> dict:
    return {
        "available_boxes": random.randint(2, 6),
        "total_boxes": 10,
        "oxygen_points_free": random.randint(3, 8),
        "cardiac_monitors_free": random.randint(2, 5),
        "resus_room_available": random.choice([True, True, False]),
        "imaging_open": True,
        "lab_turnaround_minutes": random.randint(20, 60),
        "checked_at": datetime.utcnow().isoformat(),
    }


def _wait_by_priority(priority: str | None) -> int:
    return {
        "critical": 0,
        "urgent": random.randint(5, 15),
        "standard": random.randint(30, 90),
        "non_urgent": random.randint(90, 240),
    }.get((priority or "standard").lower(), 60)


# ---------- Internos de la herramienta de sync con Drive ----------

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _drive_sync_folder() -> str | None:
    """Resuelve la carpeta destino desde la env var DRIVE_SYNC_FOLDER."""
    raw = os.environ.get("DRIVE_SYNC_FOLDER", "").strip()
    return raw or None


def _safe_filename_part(value: str) -> str:
    """Sanea un identificador para usarlo seguro en el filesystem."""
    cleaned = _SAFE_NAME.sub("_", value.strip())
    return cleaned or "unknown"


def _canonical_filename(patient_id: str) -> str:
    """`informe_{patient_id}_{YYYY-MM-DD_HHMM}.pdf` — única fuente de verdad."""
    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    return f"informe_{_safe_filename_part(patient_id)}_{ts}.pdf"


# ---------- Endpoints ----------


@app.get("/health")
def health() -> dict:
    folder = _drive_sync_folder()
    return {
        "status": "ok",
        "service": "mcp-hospital-tools",
        "drive_sync_folder": folder,
        "drive_sync_folder_exists": bool(folder and Path(folder).is_dir()),
    }


@app.get("/tools")
def list_tools() -> dict:
    return {
        "tools": [
            {"name": "get_available_tests", "endpoint": "/tools/get_available_tests"},
            {"name": "get_resource_status", "endpoint": "/tools/get_resource_status"},
            {"name": "get_estimated_wait_time", "endpoint": "/tools/get_estimated_wait_time"},
            {"name": "hospital_context", "endpoint": "/tools/hospital_context"},
            {"name": "send_report_to_drive", "endpoint": "/tools/send_report_to_drive"},
            {"name": "sync_status", "endpoint": "/tools/sync_status"},
            *jira_tools.tool_index(),
        ]
    }


@app.post("/tools/get_available_tests")
def get_available_tests(req: TestsRequest) -> dict:
    return {"tests": _select_tests(req.suspected_categories)}


@app.post("/tools/get_resource_status")
def get_resource_status() -> dict:
    return _resource_status()


@app.post("/tools/get_estimated_wait_time")
def get_estimated_wait_time(req: WaitRequest) -> dict:
    return {"priority": req.priority, "estimated_wait_minutes": _wait_by_priority(req.priority)}


@app.post("/tools/hospital_context")
def hospital_context(req: ContextRequest) -> dict:
    return {
        "available_tests": _select_tests(req.suspected_categories),
        "resources": _resource_status(),
        "estimated_wait_minutes": _wait_by_priority(req.priority),
        "fallback": False,
    }


@app.get("/tools/sync_status")
def sync_status() -> dict:
    folder = _drive_sync_folder()
    if not folder:
        return {
            "configured": False,
            "drive_sync_folder": None,
            "exists": False,
            "writable": False,
            "message": "DRIVE_SYNC_FOLDER env var not set.",
        }
    p = Path(folder)
    exists = p.is_dir()
    writable = exists and os.access(p, os.W_OK)
    return {
        "configured": True,
        "drive_sync_folder": str(p),
        "exists": exists,
        "writable": writable,
        "message": (
            "Folder ready — files copied here are synced to Google Drive by Drive Desktop."
            if writable else "Folder not writable or missing — it will be created on demand."
        ),
    }


@app.post("/tools/send_report_to_drive")
def send_report_to_drive(req: SendReportRequest) -> dict:
    """Copia un PDF médico a la carpeta sincronizada por Drive Desktop.

    Pasos:
      1. Validar que `report_path` existe.
      2. Validar que es un PDF (extensión + sniff simple del header).
      3. Resolver DRIVE_SYNC_FOLDER (env var).
      4. Crear la carpeta destino si no existe.
      5. Copiar el PDF, renombrándolo a
         `informe_<patient_id>_<YYYY-MM-DD_HHMM>.pdf` (o respetando
         `optional_filename` si se proporciona).
      6. Devolver metadata de éxito.
    """
    src = Path(req.report_path)
    logger.info("send_report_to_drive.start patient_id=%s source=%s", req.patient_id, src)

    if not src.exists():
        msg = f"Source report not found: {src}"
        logger.warning("send_report_to_drive.missing_source %s", msg)
        raise HTTPException(status_code=404, detail=msg)
    if not src.is_file():
        raise HTTPException(status_code=400, detail=f"Source path is not a file: {src}")
    if src.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail=f"Only PDF files accepted, got: {src.suffix}")

    # Sanity check ligero sobre los bytes reales — un PDF empieza con `%PDF-`.
    try:
        with src.open("rb") as f:
            header = f.read(5)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Cannot read source file: {e}")
    if header[:4] != b"%PDF":
        raise HTTPException(status_code=400, detail="Source file is not a valid PDF (header check failed).")

    folder = _drive_sync_folder()
    if not folder:
        raise HTTPException(
            status_code=503,
            detail="DRIVE_SYNC_FOLDER not configured. Set it in .env or the mcp-server environment.",
        )
    dest_dir = Path(folder)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Cannot create destination folder '{dest_dir}': {e}")

    filename = req.optional_filename or _canonical_filename(req.patient_id)
    if not filename.lower().endswith(".pdf"):
        filename = f"{filename}.pdf"
    filename = _SAFE_NAME.sub("_", filename) if filename != _SAFE_NAME.sub("_", filename) else filename

    dest_path = dest_dir / filename
    logger.info("send_report_to_drive.copy dest=%s", dest_path)

    try:
        shutil.copy2(src, dest_path)
    except OSError as e:
        logger.exception("send_report_to_drive.copy_failed")
        raise HTTPException(status_code=500, detail=f"Failed to copy report: {e}")

    size_bytes = dest_path.stat().st_size
    logger.info(
        "send_report_to_drive.ok patient_id=%s filename=%s size_bytes=%d",
        req.patient_id, filename, size_bytes,
    )
    return {
        "success": True,
        "destination_path": str(dest_path),
        "filename": filename,
        "patient_id": req.patient_id,
        "size_bytes": size_bytes,
        "drive_sync_folder": str(dest_dir),
        "copied_at": datetime.utcnow().isoformat() + "Z",
        "message": "Report uploaded successfully",
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "7800")))
