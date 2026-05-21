"""Behaviour tests for the jira_hooks glue layer.

The hooks must never raise even when:
* Jira is disabled (default for the demo)
* the underlying service decides to no-op
* the case has no jira_key yet

A successful path persists the ticket key on the case AND in the repository.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas.triage import (
    AgentEvent, TriageCase, TriageIntake, TriageReport, VitalSigns,
)


def _case() -> TriageCase:
    intake = TriageIntake(
        symptoms="dolor torácico opresivo irradiado",
        age=54,
        sex="male",
        vital_signs=VitalSigns(heart_rate=102, oxygen_saturation=95.0),
    )
    return TriageCase(case_id="c-test", intake=intake, status="queued")


def _report() -> TriageReport:
    return TriageReport(
        case_id="c-test",
        suggested_priority="urgent",
        risk_factors=["HTA", "Dislipemia"],
        recommended_next_steps=["ECG inmediato", "Troponina"],
        retrieved_protocols=[{"title": "Manchester — Dolor torácico", "score": 50.2}],
        summary="Cuadro compatible con SCA.",
    )


# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_start_noop_when_disabled():
    from app.services import jira_hooks

    svc = MagicMock()
    svc.is_enabled = False
    case = _case()
    with patch("app.services.jira_hooks.get_jira_service", return_value=svc):
        key = await jira_hooks.on_start(case)
    assert key is None
    assert case.jira_key is None


@pytest.mark.asyncio
async def test_on_start_persists_key_on_success():
    from app.services import jira_hooks

    svc = MagicMock()
    svc.is_enabled = True
    svc.create_patient_ticket = AsyncMock(return_value="KAN-9")
    svc.transition_in_progress = AsyncMock(return_value=True)
    case = _case()

    repo = MagicMock()
    repo.record_jira_key = AsyncMock(return_value=None)
    with patch("app.services.jira_hooks.get_jira_service", return_value=svc), \
         patch("app.services.jira_hooks.cases_repo", repo):
        key = await jira_hooks.on_start(case)

    assert key == "KAN-9"
    assert case.jira_key == "KAN-9"
    svc.create_patient_ticket.assert_awaited_once()
    svc.transition_in_progress.assert_awaited_once_with("KAN-9")
    repo.record_jira_key.assert_awaited_once_with("c-test", "KAN-9")


@pytest.mark.asyncio
async def test_on_start_creation_failure_does_not_persist():
    from app.services import jira_hooks

    svc = MagicMock()
    svc.is_enabled = True
    svc.create_patient_ticket = AsyncMock(return_value=None)
    svc.transition_in_progress = AsyncMock()
    case = _case()
    repo = MagicMock()
    repo.record_jira_key = AsyncMock()
    with patch("app.services.jira_hooks.get_jira_service", return_value=svc), \
         patch("app.services.jira_hooks.cases_repo", repo):
        key = await jira_hooks.on_start(case)
    assert key is None
    assert case.jira_key is None
    svc.transition_in_progress.assert_not_called()
    repo.record_jira_key.assert_not_called()


@pytest.mark.asyncio
async def test_on_report_noop_when_no_jira_key():
    from app.services import jira_hooks

    svc = MagicMock()
    svc.is_enabled = True
    svc.add_comment = AsyncMock()
    case = _case()  # jira_key is None
    with patch("app.services.jira_hooks.get_jira_service", return_value=svc):
        await jira_hooks.on_report(case, _report())
    svc.add_comment.assert_not_called()


@pytest.mark.asyncio
async def test_on_report_posts_summary_when_key_present():
    from app.services import jira_hooks

    svc = MagicMock()
    svc.is_enabled = True
    svc.add_comment = AsyncMock(return_value=True)
    case = _case()
    case.jira_key = "KAN-9"

    with patch("app.services.jira_hooks.get_jira_service", return_value=svc):
        await jira_hooks.on_report(case, _report())

    svc.add_comment.assert_awaited_once()
    kwargs = svc.add_comment.call_args.kwargs
    assert kwargs["ticket_key"] == "KAN-9"
    body = kwargs["body"]
    assert "URGENTE" in body
    assert "Manchester" not in body  # protocols are not piped through (intentional)
    assert "ECG inmediato" in body
    assert "Aviso" in body


@pytest.mark.asyncio
async def test_on_delivered_includes_filename_and_path():
    from app.services import jira_hooks

    svc = MagicMock()
    svc.is_enabled = True
    svc.add_comment = AsyncMock(return_value=True)

    delivery = {
        "drive_file_id": "informe_c-test_2026-05-13_1500.pdf",
        "folder": "/app/reports",
        "path": "/app/reports/informe_c-test_2026-05-13_1500.pdf",
        "mode": "local_sync",
    }

    with patch("app.services.jira_hooks.get_jira_service", return_value=svc):
        await jira_hooks.on_delivered("c-test", "KAN-9", delivery)

    body = svc.add_comment.call_args.kwargs["body"]
    assert "informe_c-test_2026-05-13_1500.pdf" in body
    assert "/app/reports" in body
    assert "local_sync" in body


@pytest.mark.asyncio
async def test_close_case_uses_done_category_transition():
    """close_case now walks the workflow: it lists transitions and picks
    one whose target statusCategory is ``done`` instead of relying on a
    hardcoded transition ID. Works across any Jira workflow shape."""
    from app.services import jira_hooks

    svc = MagicMock()
    svc.is_enabled = True
    svc.list_transitions = AsyncMock(return_value=[
        {"id": "11", "name": "Por hacer", "to": {"statusCategory": {"key": "new"}}},
        {"id": "21", "name": "En curso", "to": {"statusCategory": {"key": "done"}}},
    ])
    svc.transition = AsyncMock(return_value=True)
    with patch("app.services.jira_hooks.get_jira_service", return_value=svc):
        ok = await jira_hooks.close_case("KAN-9")
    assert ok is True
    svc.transition.assert_awaited_once_with(ticket_key="KAN-9", transition_id="21")


@pytest.mark.asyncio
async def test_close_case_walks_through_indeterminate():
    """If no done-category transition is directly available, close_case
    advances through an indeterminate transition first, then retries."""
    from app.services import jira_hooks

    svc = MagicMock()
    svc.is_enabled = True
    svc.list_transitions = AsyncMock(side_effect=[
        [{"id": "21", "name": "En curso", "to": {"statusCategory": {"key": "indeterminate"}}}],
        [{"id": "41", "name": "Listo", "to": {"statusCategory": {"key": "done"}}}],
    ])
    svc.transition = AsyncMock(return_value=True)
    with patch("app.services.jira_hooks.get_jira_service", return_value=svc):
        ok = await jira_hooks.close_case("KAN-9")
    assert ok is True
    assert svc.transition.await_count == 2
    assert svc.transition.await_args_list[0].kwargs["transition_id"] == "21"
    assert svc.transition.await_args_list[1].kwargs["transition_id"] == "41"


@pytest.mark.asyncio
async def test_close_case_noop_when_disabled():
    from app.services import jira_hooks

    svc = MagicMock()
    svc.is_enabled = False
    with patch("app.services.jira_hooks.get_jira_service", return_value=svc):
        ok = await jira_hooks.close_case("KAN-9")
    assert ok is False


@pytest.mark.asyncio
async def test_on_report_skipped_silently_when_disabled():
    """The disabled path must NEVER touch add_comment."""
    from app.services import jira_hooks

    svc = MagicMock()
    svc.is_enabled = False
    svc.add_comment = AsyncMock()
    case = _case()
    case.jira_key = "KAN-1"
    with patch("app.services.jira_hooks.get_jira_service", return_value=svc):
        await jira_hooks.on_report(case, _report())
    svc.add_comment.assert_not_called()
