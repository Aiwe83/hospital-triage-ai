"""Servicio de orquestación: lanza el workflow LangGraph por caso."""

import asyncio
import uuid
from datetime import datetime
from typing import Dict

from app.agents.events import bus
from app.agents.graph import build_triage_graph
from app.core.logging import get_logger
from app.db.cases_repo import cases_repo
from app.schemas.triage import AgentEvent, TriageCase, TriageIntake
from app.services import jira_hooks

log = get_logger(__name__)


class TriageService:
    """Registro de casos en memoria + runner de LangGraph.

    La persistencia en MongoDB se monta por encima (ver cases_repo) — este
    servicio es el punto único de entrada para API y persistencia.
    """

    def __init__(self) -> None:
        self._cases: Dict[str, TriageCase] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    def get(self, case_id: str) -> TriageCase | None:
        return self._cases.get(case_id)

    async def start(self, intake: TriageIntake) -> TriageCase:
        case_id = uuid.uuid4().hex[:12]
        case = TriageCase(case_id=case_id, intake=intake, status="queued")
        self._cases[case_id] = case
        bus.open(case_id)

        await cases_repo.create(case)
        # Canal lateral: crear el ticket Jira en cuanto el caso existe para
        # que el operador lo vea en el tablero mientras los agentes trabajan.
        # Envuelto en try/except para que una caída de Jira nunca bloquee el
        # flujo de triaje.
        try:
            await jira_hooks.on_start(case)
        except Exception as e:
            log.warning("jira_on_start_failed", error=str(e), case_id=case_id)
        task = asyncio.create_task(self._run(case))
        self._tasks[case_id] = task
        return case

    async def _run(self, case: TriageCase) -> None:
        case.status = "running"
        await cases_repo.update_status(case.case_id, "running")
        graph = build_triage_graph()
        try:
            result = await graph.ainvoke({
                "case_id": case.case_id,
                "intake": case.intake,
                "agent_trace": [],
                "errors": [],
            })
            case.agent_trace = result.get("agent_trace", [])
            case.report = result.get("report")
            case.status = "completed"
            await cases_repo.complete(case)
            # Canal lateral: publicar el informe final de IA como comentario en Jira.
            if case.report is not None:
                try:
                    await jira_hooks.on_report(case, case.report)
                except Exception as e:
                    log.warning("jira_on_report_failed", error=str(e), case_id=case.case_id)
            await self._finalize_agent_states(case.case_id, case.agent_trace)
            await bus.publish(case.case_id, AgentEvent(
                agent_id="triage_orchestrator",
                status="completed",
                message="Triage workflow completed.",
                timestamp=datetime.utcnow(),
            ))
        except Exception as e:
            log.exception("triage_workflow_failed", case_id=case.case_id)
            case.status = "error"
            await cases_repo.update_status(case.case_id, "error", error=str(e))
            await bus.publish(case.case_id, AgentEvent(
                agent_id="triage_orchestrator",
                status="error",
                message=f"Workflow failed: {e}",
            ))
        finally:
            await bus.close(case.case_id)


    # Estados terminales — todo agente cuyo último evento no esté en este
    # conjunto se fuerza a `completed` al finalizar el workflow, para que
    # la UI nunca deje un nodo atascado en `executing` / `analyzing` /
    # `writing` / etc.
    _TERMINAL_STATES = {"completed", "blocked", "error", "idle"}
    _ALL_AGENTS = (
        "triage_orchestrator",
        "clinical_analyst",
        "protocol_researcher",
        "hospital_systems_executor",
        "clinical_safety_validator",
        "report_writer",
    )

    async def _finalize_agent_states(self, case_id: str, trace: list[AgentEvent]) -> None:
        """Emite eventos `completed` sintéticos para agentes que quedaron trabajando.

        Defensivo: cada nodo LangGraph ya emite su propio evento terminal,
        pero si algún nodo se interrumpe o se salta, esto garantiza que la
        UI no muestre un nodo bloqueado en `executing` / `writing` / etc.
        """
        latest: dict[str, str] = {}
        for ev in trace:
            latest[ev.agent_id] = ev.status
        for agent_id in self._ALL_AGENTS:
            status = latest.get(agent_id)
            if status is None or status in self._TERMINAL_STATES:
                continue
            log.info("finalize_force_completed", case_id=case_id, agent_id=agent_id, prev=status)
            await bus.publish(case_id, AgentEvent(
                agent_id=agent_id,
                status="completed",
                message="Etapa finalizada por el orquestador.",
                timestamp=datetime.utcnow(),
            ))


triage_service = TriageService()
