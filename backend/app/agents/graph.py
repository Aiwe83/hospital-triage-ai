"""Cableado LangGraph del workflow de triaje hospitalario."""

from functools import lru_cache
from langgraph.graph import StateGraph, START, END

from app.agents.state import TriageState
from app.agents.nodes import (
    orchestrator_node,
    clinical_analyst_node,
    protocol_researcher_node,
    hospital_systems_executor_node,
    clinical_safety_validator_node,
    report_writer_node,
)


@lru_cache
def build_triage_graph():
    g = StateGraph(TriageState)

    g.add_node("triage_orchestrator", orchestrator_node)
    g.add_node("clinical_analyst", clinical_analyst_node)
    g.add_node("protocol_researcher", protocol_researcher_node)
    g.add_node("hospital_systems_executor", hospital_systems_executor_node)
    g.add_node("clinical_safety_validator", clinical_safety_validator_node)
    g.add_node("report_writer", report_writer_node)

    g.add_edge(START, "triage_orchestrator")
    g.add_edge("triage_orchestrator", "clinical_analyst")

    # Tras el análisis, buscar protocolos y consultar sistemas hospitalarios en secuencia.
    # (La ejecución secuencial mantiene la animación visual fácil de seguir en directo.)
    g.add_edge("clinical_analyst", "protocol_researcher")
    g.add_edge("protocol_researcher", "hospital_systems_executor")
    g.add_edge("hospital_systems_executor", "clinical_safety_validator")
    g.add_edge("clinical_safety_validator", "report_writer")
    g.add_edge("report_writer", END)

    return g.compile()
