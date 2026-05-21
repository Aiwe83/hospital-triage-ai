"""Herramientas Jira estilo MCP expuestas como endpoints HTTP.

Refleja las siete herramientas listadas en la spec del proyecto:

    create_patient_ticket
    update_patient_status
    assign_doctor
    add_medical_comment
    attach_drive_report
    close_case
    get_patient_ticket

La implementación es deliberadamente independiente — NO importa nada del
paquete ``backend/`` porque el servidor MCP corre en su propio contenedor
con su propio cierre de dependencias. Las dos capas (hooks del backend +
este facade MCP) hablan con Atlassian con clientes propios pero
comparten las mismas env vars, así que el comportamiento es consistente.

Reglas de diseño:

* Cada endpoint devuelve HTTP 200 con
  ``{"success": false, "reason": "..."}`` cuando Jira está deshabilitado
  o faltan credenciales. El caller decide cómo reaccionar sin parsear
  códigos HTTP.
* Errores reales de red degradan a HTTP 502 con un detalle claro. Es el
  único camino que expone un error code, así es fácil distinguir fallos
  de "config" de fallos de "Atlassian caído".
* La cabecera Authorization se calcula una vez al arrancar. Nunca se
  refleja en respuestas ni se loguea.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("mcp.jira")

router = APIRouter(prefix="/tools/jira", tags=["jira"])


# ---------------------------------------------------------------------------
# Config + cliente
# ---------------------------------------------------------------------------

class _Config:
    """Resuelto al arrancar desde variables de entorno."""

    def __init__(self) -> None:
        self.enabled = os.environ.get("JIRA_ENABLED", "false").lower() == "true"
        self.url = os.environ.get("JIRA_URL", "").rstrip("/")
        self.email = os.environ.get("JIRA_EMAIL", "")
        self.token = os.environ.get("JIRA_API_TOKEN", "")
        self.project = os.environ.get("JIRA_PROJECT_KEY", "KAN")
        self.issuetype = os.environ.get("JIRA_ISSUETYPE_NAME", "Task")
        self.transition_in_progress = os.environ.get("JIRA_TRANSITION_ID_IN_PROGRESS", "")
        self.transition_done = os.environ.get("JIRA_TRANSITION_ID_DONE", "")
        self.labels = [
            l.strip() for l in os.environ.get(
                "JIRA_LABELS", "paciente,triage-ia,hospital-ai",
            ).split(",") if l.strip()
        ]
        self.timeout = float(os.environ.get("JIRA_TIMEOUT", "15"))

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.url and self.email and self.token and self.project)


_cfg = _Config()


def _auth_headers() -> dict:
    raw = f"{_cfg.email}:{_cfg.token}".encode("utf-8")
    return {
        "Authorization": "Basic " + base64.b64encode(raw).decode("ascii"),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _adf(text: str) -> dict:
    """Atlassian Document Format — un único párrafo de texto plano."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ],
    }


def _disabled(reason: str = "JIRA disabled or credentials missing.") -> dict:
    return {"success": False, "reason": reason}


async def _post(path: str, payload: dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=_cfg.timeout) as client:
        return await client.post(f"{_cfg.url}{path}", json=payload, headers=_auth_headers())


async def _get(path: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=_cfg.timeout) as client:
        return await client.get(f"{_cfg.url}{path}", headers=_auth_headers())


async def _put(path: str, payload: dict) -> httpx.Response:
    async with httpx.AsyncClient(timeout=_cfg.timeout) as client:
        return await client.put(f"{_cfg.url}{path}", json=payload, headers=_auth_headers())


# ---------------------------------------------------------------------------
# Esquemas
# ---------------------------------------------------------------------------

class CreatePatientTicket(BaseModel):
    patient_name: str = Field(..., min_length=1)
    age: int = Field(..., ge=0, le=130)
    symptoms: str = Field(..., min_length=1)
    priority: Optional[str] = None       # solo informativo, no es el campo de Jira
    risk_level: Optional[str] = None     # se añade al summary
    case_id: Optional[str] = None        # se usa como label para cross-reference


class UpdatePatientStatus(BaseModel):
    ticket_key: str = Field(..., min_length=2)
    status: str = Field(..., description="Uno de: REGISTRADO, EN CONSULTA, ALTA — mapeado a IDs de transición.")


class AssignDoctor(BaseModel):
    ticket_key: str
    doctor_email: str


class AddMedicalComment(BaseModel):
    ticket_key: str
    comment: str


class AttachDriveReport(BaseModel):
    ticket_key: str
    drive_url: Optional[str] = None
    filename: Optional[str] = None
    folder: Optional[str] = None


class CloseCase(BaseModel):
    ticket_key: str


class GetPatientTicket(BaseModel):
    ticket_key: str


# ---------------------------------------------------------------------------
# Endpoints de las herramientas
# ---------------------------------------------------------------------------

@router.get("/status")
def jira_status() -> dict:
    """Sonda rápida para que el operador verifique la config sin tocar Atlassian."""
    return {
        "enabled": _cfg.enabled,
        "ready": _cfg.ready,
        "url": _cfg.url or None,
        "project": _cfg.project if _cfg.ready else None,
        "issuetype": _cfg.issuetype,
        "transition_in_progress": bool(_cfg.transition_in_progress),
        "transition_done": bool(_cfg.transition_done),
    }


@router.post("/create_patient_ticket")
async def create_patient_ticket(req: CreatePatientTicket) -> dict:
    if not _cfg.ready:
        return _disabled()

    summary = f"Paciente: {req.patient_name} | Edad: {req.age}"
    if req.risk_level:
        summary = f"{summary} | Riesgo: {req.risk_level}"
    summary = summary[:250]

    description = (
        f"Paciente: {req.patient_name}\n"
        f"Edad: {req.age}\n"
        f"Síntomas: {req.symptoms}\n"
        + (f"Prioridad clínica: {req.priority}\n" if req.priority else "")
        + (f"Nivel de riesgo IA: {req.risk_level}\n" if req.risk_level else "")
        + (f"Caso: {req.case_id}\n" if req.case_id else "")
    )

    labels = list({*_cfg.labels, *(["case-" + req.case_id] if req.case_id else [])})
    payload = {
        "fields": {
            "project": {"key": _cfg.project},
            "summary": summary,
            "description": _adf(description),
            "issuetype": {"name": _cfg.issuetype},
            "labels": labels,
        }
    }
    try:
        r = await _post("/rest/api/3/issue", payload)
    except httpx.HTTPError as e:
        logger.warning("jira.create_failed network error=%s", e)
        raise HTTPException(status_code=502, detail=f"Jira unreachable: {e}")
    if r.status_code not in (200, 201):
        logger.warning("jira.create_rejected status=%s body=%s", r.status_code, r.text[:300])
        return {
            "success": False,
            "status_code": r.status_code,
            "error": r.text[:500],
            "reason": "Jira rejected the create request.",
        }
    key = r.json().get("key")
    logger.info("jira.create_ok key=%s patient=%s", key, req.patient_name)
    return {"success": True, "ticket_key": key, "labels": labels}


@router.post("/update_patient_status")
async def update_patient_status(req: UpdatePatientStatus) -> dict:
    if not _cfg.ready:
        return _disabled()

    # Mapea los estados clínicos canónicos a los IDs de transición
    # configurados por env. Aceptamos los nombres de la spec más las
    # variantes en inglés más habituales para que el operador pueda
    # llamar la herramienta en cualquier idioma.
    s = req.status.strip().upper()
    if s in {"REGISTRADO", "TO DO", "TODO"}:
        # La primera columna no tiene transición (es el estado inicial);
        # para la demo lo tratamos como éxito no-op para que los callers
        # confíen en la misma forma sea cual sea el estado.
        return {"success": True, "ticket_key": req.ticket_key, "applied": "noop", "status": "REGISTRADO"}
    if s in {"EN CONSULTA", "IN PROGRESS"}:
        tr_id = _cfg.transition_in_progress
        canonical = "EN CONSULTA"
    elif s in {"ALTA", "DONE"}:
        tr_id = _cfg.transition_done
        canonical = "ALTA"
    else:
        raise HTTPException(status_code=400, detail=f"Unknown clinical status: {req.status}")

    if not tr_id:
        return _disabled(
            f"Missing JIRA_TRANSITION_ID_{('IN_PROGRESS' if canonical == 'EN CONSULTA' else 'DONE')}. "
            "Run scripts/jira_discover.py to obtain it."
        )

    try:
        r = await _post(
            f"/rest/api/3/issue/{req.ticket_key}/transitions",
            {"transition": {"id": str(tr_id)}},
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Jira unreachable: {e}")
    if r.status_code not in (200, 204):
        logger.warning("jira.transition_rejected status=%s body=%s", r.status_code, r.text[:300])
        return {"success": False, "status_code": r.status_code, "error": r.text[:500]}
    return {"success": True, "ticket_key": req.ticket_key, "status": canonical}


@router.post("/assign_doctor")
async def assign_doctor(req: AssignDoctor) -> dict:
    if not _cfg.ready:
        return _disabled()

    # Atlassian Cloud ya no acepta asignación por email (GDPR). Resolvemos
    # primero el accountId; si no hay match, el caller recibe un fallo
    # claro en vez de un 400 confuso de Jira.
    try:
        r = await _get(f"/rest/api/3/user/search?query={req.doctor_email}")
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Jira unreachable: {e}")
    if r.status_code != 200:
        return {"success": False, "status_code": r.status_code, "error": r.text[:400]}
    users = r.json() if isinstance(r.json(), list) else []
    if not users:
        return {
            "success": False,
            "reason": f"No Jira user matched '{req.doctor_email}'. "
                      "Confirm the email is associated with an Atlassian account in this site.",
        }
    account_id = users[0].get("accountId")
    try:
        r2 = await _put(
            f"/rest/api/3/issue/{req.ticket_key}/assignee",
            {"accountId": account_id},
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Jira unreachable: {e}")
    if r2.status_code not in (200, 204):
        return {"success": False, "status_code": r2.status_code, "error": r2.text[:400]}
    return {"success": True, "ticket_key": req.ticket_key, "account_id": account_id}


@router.post("/add_medical_comment")
async def add_medical_comment(req: AddMedicalComment) -> dict:
    if not _cfg.ready:
        return _disabled()
    try:
        r = await _post(
            f"/rest/api/3/issue/{req.ticket_key}/comment",
            {"body": _adf(req.comment)},
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Jira unreachable: {e}")
    if r.status_code not in (200, 201):
        return {"success": False, "status_code": r.status_code, "error": r.text[:400]}
    return {"success": True, "ticket_key": req.ticket_key, "comment_id": r.json().get("id")}


@router.post("/attach_drive_report")
async def attach_drive_report(req: AttachDriveReport) -> dict:
    """Comentamos con lo que sepamos de la copia en Drive.

    Adjuntos reales requieren multipart/form-data, fuera de alcance para
    este MVP. Un comentario con la URL o el filename local basta para que
    el clínico encuentre el informe en la carpeta sincronizada.
    """
    if not _cfg.ready:
        return _disabled()
    lines = ["[Informe entregado a la carpeta clínica]"]
    if req.drive_url:
        lines.append(f"URL Drive: {req.drive_url}")
    if req.filename:
        lines.append(f"Archivo: {req.filename}")
    if req.folder:
        lines.append(f"Carpeta sincronizada: {req.folder}")
    if not (req.drive_url or req.filename or req.folder):
        lines.append("(sin metadatos adicionales)")

    try:
        r = await _post(
            f"/rest/api/3/issue/{req.ticket_key}/comment",
            {"body": _adf("\n".join(lines))},
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Jira unreachable: {e}")
    if r.status_code not in (200, 201):
        return {"success": False, "status_code": r.status_code, "error": r.text[:400]}
    return {"success": True, "ticket_key": req.ticket_key}


@router.post("/close_case")
async def close_case(req: CloseCase) -> dict:
    if not _cfg.ready:
        return _disabled()
    if not _cfg.transition_done:
        return _disabled(
            "Missing JIRA_TRANSITION_ID_DONE. Run scripts/jira_discover.py to obtain it.",
        )
    try:
        r = await _post(
            f"/rest/api/3/issue/{req.ticket_key}/transitions",
            {"transition": {"id": str(_cfg.transition_done)}},
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Jira unreachable: {e}")
    if r.status_code not in (200, 204):
        return {"success": False, "status_code": r.status_code, "error": r.text[:400]}
    return {"success": True, "ticket_key": req.ticket_key, "status": "ALTA"}


@router.post("/get_patient_ticket")
async def get_patient_ticket(req: GetPatientTicket) -> dict:
    if not _cfg.ready:
        return _disabled()
    try:
        r = await _get(
            f"/rest/api/3/issue/{req.ticket_key}"
            "?fields=summary,status,assignee,labels,priority,comment,issuetype"
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Jira unreachable: {e}")
    if r.status_code != 200:
        return {"success": False, "status_code": r.status_code, "error": r.text[:400]}
    data = r.json()
    fields = data.get("fields", {})
    comments_raw = fields.get("comment", {}).get("comments", [])

    def _flatten(adf: Any) -> str:
        """Recorre el árbol ADF y une nodos de texto — los comentarios llegan como ADF."""
        if isinstance(adf, dict):
            if adf.get("type") == "text":
                return adf.get("text", "")
            return "".join(_flatten(c) for c in adf.get("content", []))
        if isinstance(adf, list):
            return "".join(_flatten(c) for c in adf)
        return ""

    return {
        "success": True,
        "ticket_key": data.get("key"),
        "summary": fields.get("summary"),
        "status": (fields.get("status") or {}).get("name"),
        "issuetype": (fields.get("issuetype") or {}).get("name"),
        "assignee": (fields.get("assignee") or {}).get("displayName") if fields.get("assignee") else None,
        "labels": fields.get("labels", []),
        "comments": [
            {
                "id": c.get("id"),
                "author": (c.get("author") or {}).get("displayName"),
                "created": c.get("created"),
                "body": _flatten(c.get("body")),
            }
            for c in comments_raw
        ],
    }


def tool_index() -> list[dict]:
    """Lista de descriptores de herramientas que el server.py padre fusiona en /tools."""
    return [
        {"name": "jira_create_patient_ticket", "endpoint": "/tools/jira/create_patient_ticket"},
        {"name": "jira_update_patient_status", "endpoint": "/tools/jira/update_patient_status"},
        {"name": "jira_assign_doctor", "endpoint": "/tools/jira/assign_doctor"},
        {"name": "jira_add_medical_comment", "endpoint": "/tools/jira/add_medical_comment"},
        {"name": "jira_attach_drive_report", "endpoint": "/tools/jira/attach_drive_report"},
        {"name": "jira_close_case", "endpoint": "/tools/jira/close_case"},
        {"name": "jira_get_patient_ticket", "endpoint": "/tools/jira/get_patient_ticket"},
        {"name": "jira_status", "endpoint": "/tools/jira/status"},
    ]
