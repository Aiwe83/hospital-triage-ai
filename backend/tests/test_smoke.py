"""Smoke tests — verify import graph and FastAPI routing without external services."""

import pytest
from fastapi.testclient import TestClient


def _client():
    # Build the app after env defaults are picked up.
    from app.main import app
    return TestClient(app)


def test_health_endpoint():
    with _client() as c:
        r = c.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert "llm_model" in body


def test_graph_builds():
    """The LangGraph must compile without runtime errors."""
    from app.agents.graph import build_triage_graph
    g = build_triage_graph()
    assert g is not None


def test_pdf_render():
    from datetime import datetime
    from app.schemas.triage import (
        TriageCase, TriageIntake, VitalSigns, AgentEvent, TriageReport,
    )
    from app.services.report_pdf import render_triage_pdf

    intake = TriageIntake(symptoms="dyspnea", age=62, vital_signs=VitalSigns(oxygen_saturation=89))
    report = TriageReport(
        case_id="abc",
        suggested_priority="urgent",
        risk_factors=["hypoxia"],
        recommended_next_steps=["oxygen therapy", "ABG"],
        retrieved_protocols=[{"title": "ESI 2", "id": "x", "score": 1.2}],
        summary="Likely respiratory distress. Recommend immediate clinical assessment.",
    )
    case = TriageCase(
        case_id="abc",
        intake=intake,
        status="completed",
        agent_trace=[AgentEvent(agent_id="triage_orchestrator", status="completed", message="ok", timestamp=datetime.utcnow())],
        report=report,
    )
    pdf = render_triage_pdf(case)
    assert pdf[:4] == b"%PDF"
