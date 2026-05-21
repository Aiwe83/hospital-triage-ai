"""Estado compartido de LangGraph para el workflow de triaje."""

from __future__ import annotations
from datetime import datetime
from operator import add
from typing import Annotated, Optional, TypedDict

from app.schemas.triage import AgentEvent, TriageIntake, TriageReport


def _merge_dict(left: dict, right: dict) -> dict:
    out = dict(left or {})
    out.update(right or {})
    return out


class TriageState(TypedDict, total=False):
    case_id: str
    intake: TriageIntake

    # Trace acumulado — cada nodo añade eventos.
    agent_trace: Annotated[list[AgentEvent], add]

    # Salidas por etapa (dicts fusionables).
    clinical_analysis: Annotated[dict, _merge_dict]
    protocols: Annotated[dict, _merge_dict]
    hospital_context: Annotated[dict, _merge_dict]
    safety: Annotated[dict, _merge_dict]

    # Informe final
    report: Optional[TriageReport]

    # Errores por nodo
    errors: Annotated[list[dict], add]


def now_iso() -> str:
    return datetime.utcnow().isoformat()
