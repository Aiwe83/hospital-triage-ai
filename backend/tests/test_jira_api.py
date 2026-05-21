"""HTTP-level tests for the Jira FastAPI surface.

Covers the two routes added in this iteration:

* GET  /jira/status — exposes the current enabled flag
* POST /triage/{case_id}/jira/close — closes the case ticket

The tests run with the default ``.env`` (JIRA_ENABLED=false) so they do
not touch the real Atlassian Cloud.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app)


def test_jira_status_endpoint():
    with _client() as c:
        r = c.get("/jira/status")
        assert r.status_code == 200
        body = r.json()
        assert "enabled" in body
        assert isinstance(body["enabled"], bool)
        assert "project" in body


def test_jira_close_unknown_case_returns_404():
    with _client() as c:
        r = c.post("/triage/does-not-exist/jira/close")
        assert r.status_code == 404


def test_jira_close_without_ticket_returns_409():
    """Existing case but no jira_key (Jira disabled) → 409 with clear detail."""
    from app.schemas.triage import TriageCase, TriageIntake, VitalSigns
    from app.services.triage_service import triage_service

    intake = TriageIntake(symptoms="test", age=30, vital_signs=VitalSigns())
    case = TriageCase(case_id="test-case-1", intake=intake)
    triage_service._cases["test-case-1"] = case

    with _client() as c:
        r = c.post("/triage/test-case-1/jira/close")
    assert r.status_code == 409
    assert "no Jira ticket" in r.json()["detail"]

    del triage_service._cases["test-case-1"]


def test_jira_close_success_path():
    """Mocked close_case returns True → 200 with jira_key in body."""
    from app.schemas.triage import TriageCase, TriageIntake, VitalSigns
    from app.services.triage_service import triage_service

    intake = TriageIntake(symptoms="test", age=30, vital_signs=VitalSigns())
    case = TriageCase(case_id="test-case-2", intake=intake)
    case.jira_key = "KAN-42"
    triage_service._cases["test-case-2"] = case

    with patch("app.api.jira.jira_hooks.close_case", AsyncMock(return_value=True)):
        with _client() as c:
            r = c.post("/triage/test-case-2/jira/close")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "closed"
    assert body["jira_key"] == "KAN-42"

    del triage_service._cases["test-case-2"]


def test_jira_close_failure_returns_502():
    from app.schemas.triage import TriageCase, TriageIntake, VitalSigns
    from app.services.triage_service import triage_service

    intake = TriageIntake(symptoms="test", age=30, vital_signs=VitalSigns())
    case = TriageCase(case_id="test-case-3", intake=intake)
    case.jira_key = "KAN-43"
    triage_service._cases["test-case-3"] = case

    with patch("app.api.jira.jira_hooks.close_case", AsyncMock(return_value=False)):
        with _client() as c:
            r = c.post("/triage/test-case-3/jira/close")

    assert r.status_code == 502
    del triage_service._cases["test-case-3"]
