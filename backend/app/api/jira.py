"""Minimal Jira-facing API surface.

Only the actions the UI needs today are exposed:

* GET  /jira/status                                — quick health probe
* POST /triage/{case_id}/jira/close                — transition to DONE

Creation, reporting and delivery comments happen automatically from the
backend triage workflow (see ``app.services.jira_hooks``) and do not need
a dedicated REST surface.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.logging import get_logger
from app.services.jira_service import get_jira_service
from app.services import jira_hooks
from app.services.triage_service import triage_service

router = APIRouter(tags=["jira"])
log = get_logger(__name__)


@router.get("/jira/status")
async def jira_status() -> dict:
    svc = get_jira_service()
    return {
        "enabled": svc.is_enabled,
        "project": getattr(svc, "_project", None) if svc.is_enabled else None,
    }


@router.post("/triage/{case_id}/jira/close")
async def jira_close(case_id: str) -> dict:
    case = triage_service.get(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if not case.jira_key:
        raise HTTPException(
            status_code=409,
            detail="This case has no Jira ticket associated (Jira disabled or creation failed).",
        )
    ok = await jira_hooks.close_case(case.jira_key)
    if not ok:
        raise HTTPException(status_code=502, detail="Jira refused the close transition.")
    return {"status": "closed", "case_id": case_id, "jira_key": case.jira_key}
