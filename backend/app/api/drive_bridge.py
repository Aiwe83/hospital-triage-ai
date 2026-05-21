"""Bridge endpoints used by the Claude Code MCP session.

The MCP bridge (running outside the container as part of the Claude Code
session) polls these endpoints to learn about pending Drive uploads and
report confirmations back. The endpoints are intentionally simple file
operations on the shared `/app/reports/pending/` volume.

Endpoints:
  GET  /drive-bridge/pending           -> list current pending uploads
  GET  /drive-bridge/pending/{case_id} -> read one pending entry + base64 pdf
  POST /drive-bridge/confirm/{case_id} -> record real Drive metadata
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.logging import get_logger
from app.core.settings import get_settings

router = APIRouter(prefix="/drive-bridge", tags=["drive-bridge"])
log = get_logger(__name__)


class ConfirmPayload(BaseModel):
    drive_file_id: str
    drive_view_url: str | None = None
    folder: str | None = None


def _pending_dir() -> Path:
    return Path(get_settings().report_output_dir) / "pending"


@router.get("/pending")
async def list_pending() -> dict:
    pdir = _pending_dir()
    if not pdir.exists():
        return {"items": []}
    items: list[dict[str, Any]] = []
    for f in sorted(pdir.glob("*.pending.json")):
        case_id = f.stem.replace(".pending", "")
        confirmed = (pdir / f"{case_id}.confirmed.json").exists()
        if confirmed:
            continue
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        items.append(data)
    return {"items": items}


@router.get("/pending/{case_id}")
async def read_pending(case_id: str) -> dict:
    pdir = _pending_dir()
    pf = pdir / f"{case_id}.pending.json"
    if not pf.exists():
        raise HTTPException(status_code=404, detail="No pending upload for case")
    meta = json.loads(pf.read_text())
    pdf_path = Path(meta["path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=410, detail="PDF artifact no longer exists")
    pdf_bytes = pdf_path.read_bytes()
    meta["base64_content"] = base64.b64encode(pdf_bytes).decode()
    return meta


@router.post("/confirm/{case_id}")
async def confirm_uploaded(case_id: str, payload: ConfirmPayload) -> dict:
    pdir = _pending_dir()
    confirmed_path = pdir / f"{case_id}.confirmed.json"
    pdir.mkdir(parents=True, exist_ok=True)
    confirmed_path.write_text(json.dumps(payload.model_dump(), ensure_ascii=False, indent=2))
    log.info("drive_bridge_confirmed", case_id=case_id, file_id=payload.drive_file_id)
    return {"status": "confirmed", "case_id": case_id}
