"""Pegamento entre el workflow de triaje y el canal lateral de Jira.

Los hooks de abajo son intencionalmente fire-and-forget. Ellos:

* llaman a :class:`JiraService` (que ya traga errores HTTP),
* actualizan Mongo con la key del ticket resultante,
* nunca re-lanzan. Si Jira está offline, deshabilitado o con rate-limit,
  el pipeline de triaje completa normalmente.

La granularidad es deliberadamente baja — cuatro hitos por caso, no uno
por evento de agente — para que un día ajetreado no roce el rate limit de
Atlassian Cloud (~50 req/min/usuario).
"""

from __future__ import annotations

from typing import Optional

from app.core.logging import get_logger
from app.db.cases_repo import cases_repo
from app.schemas.triage import TriageCase, TriageIntake, TriageReport
from app.services.jira_service import get_jira_service

log = get_logger(__name__)


_PRIORITY_ES = {
    "critical": "crítica",
    "urgent": "urgente",
    "standard": "estándar",
    "non_urgent": "no urgente",
}


def _intake_summary(intake: TriageIntake) -> str:
    """Etiqueta de paciente en una línea, usada como título del ticket Jira."""
    age = intake.age
    sex = {"male": "H", "female": "M", "other": "Otro"}.get(intake.sex or "", "?")
    symptoms = (intake.symptoms or "").strip().splitlines()[0]
    return f"Paciente {age}a {sex} — {symptoms}"


def _intake_description(case_id: str, intake: TriageIntake) -> str:
    v = intake.vital_signs
    lines = [
        f"Caso: {case_id}",
        f"Edad: {intake.age}    Sexo: {intake.sex or 'desconocido'}    Llegada: {intake.arrival_mode or 'por sus medios'}",
        "",
        "Síntomas:",
        intake.symptoms or "—",
        "",
        f"Antecedentes: {intake.medical_history or '—'}",
        f"Medicación: {intake.medications or '—'}",
        f"Alergias: {intake.allergies or '—'}",
        "",
        "Constantes:",
        f"  FC {v.heart_rate}    FR {v.respiratory_rate}    SpO2 {v.oxygen_saturation}",
        f"  PA {v.blood_pressure_systolic}/{v.blood_pressure_diastolic}    Temp {v.temperature_celsius}    Dolor {v.pain_score}",
    ]
    return "\n".join(lines)


async def on_start(case: TriageCase) -> Optional[str]:
    """Crea el ticket Jira cuando arranca el workflow de triaje.

    Se ejecuta una vez por caso desde ``orchestrator_node``. Persiste la
    key resultante en el caso para que los hooks posteriores y el
    frontend puedan alcanzarla.
    """
    svc = get_jira_service()
    if not svc.is_enabled:
        return None
    summary = _intake_summary(case.intake)
    description = _intake_description(case.case_id, case.intake)
    key = await svc.create_patient_ticket(
        case_id=case.case_id,
        summary=summary,
        description=description,
    )
    if not key:
        return None
    log.info("jira_ticket_created", case_id=case.case_id, key=key)
    # Mover a "in progress" de inmediato para que la card caiga en la
    # columna de trabajo del tablero en vez de quedarse en el backlog.
    await svc.transition_in_progress(key)
    await cases_repo.record_jira_key(case.case_id, key)
    case.jira_key = key
    return key


async def on_report(case: TriageCase, report: TriageReport) -> None:
    """Publica el informe de IA finalizado como comentario en el ticket."""
    svc = get_jira_service()
    if not svc.is_enabled or not case.jira_key:
        return
    priority = _PRIORITY_ES.get(report.suggested_priority, report.suggested_priority)
    risk_lines = "\n".join(f"  • {r}" for r in (report.risk_factors or [])) or "  —"
    steps_lines = "\n".join(f"  • {s}" for s in (report.recommended_next_steps or [])) or "  —"
    body = (
        f"[Informe IA generado]\n"
        f"Prioridad sugerida: {priority.upper()}\n\n"
        f"Resumen clínico:\n{report.summary}\n\n"
        f"Factores de riesgo:\n{risk_lines}\n\n"
        f"Próximos pasos sugeridos:\n{steps_lines}\n\n"
        f"Aviso: {report.disclaimer}"
    )
    await svc.add_comment(ticket_key=case.jira_key, body=body)


async def on_delivered(case_id: str, jira_key: Optional[str], delivery: dict) -> None:
    """Publica el resultado de la entrega a Drive como comentario en el ticket."""
    svc = get_jira_service()
    if not svc.is_enabled or not jira_key:
        return
    filename = delivery.get("drive_file_id") or "informe.pdf"
    folder = delivery.get("folder") or "—"
    path = delivery.get("path") or "—"
    mode = delivery.get("mode", "?")
    body = (
        "[Informe entregado a la carpeta clínica]\n"
        f"Archivo: {filename}\n"
        f"Carpeta sincronizada por Drive Desktop: {folder}\n"
        f"Ruta del archivo: {path}\n"
        f"Modo de entrega: {mode}\n"
        f"Caso: {case_id}"
    )
    await svc.add_comment(ticket_key=jira_key, body=body)


async def close_case(jira_key: str) -> bool:
    """Recorre el workflow Jira hasta que el ticket llegue a un estado "done".

    Algunos workflows requieren saltos intermedios (p. ej. Por hacer →
    En curso → In Review → Listo) antes de que una transición "done" esté
    disponible. Obtenemos las transiciones disponibles, preferimos una con
    ``to.statusCategory`` ``done`` y, si no hay, avanzamos por una
    transición ``indeterminate`` y reintentamos. Un tope pequeño de saltos
    evita bucles infinitos en workflows rotos.
    """
    svc = get_jira_service()
    if not svc.is_enabled or not jira_key:
        return False
    for _ in range(4):
        transitions = await svc.list_transitions(jira_key)
        if not transitions:
            return False
        done = next(
            (t for t in transitions
             if (t.get("to") or {}).get("statusCategory", {}).get("key") == "done"),
            None,
        )
        if done:
            return await svc.transition(ticket_key=jira_key, transition_id=str(done["id"]))
        forward = next(
            (t for t in transitions
             if (t.get("to") or {}).get("statusCategory", {}).get("key") == "indeterminate"),
            None,
        )
        if not forward:
            log.warning("jira_close_no_path", key=jira_key,
                        available=[t.get("name") for t in transitions])
            return False
        if not await svc.transition(ticket_key=jira_key, transition_id=str(forward["id"])):
            return False
    return False
