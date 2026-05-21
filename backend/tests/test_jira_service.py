"""Tests unitarios para JiraService — lógica pura, sin API real de Jira.

Ejercitamos la superficie de los casos reales:

* el camino deshabilitado devuelve None / False sin tocar httpx
* el camino habilitado serializa payloads exactamente como Atlassian espera (ADF)
* errores HTTP y respuestas 4xx/5xx degradan limpiamente en vez de levantar

httpx se parchea a nivel de módulo para que las aserciones sean deterministas.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_jira_service(monkeypatch, **env):
    """Construye un JiraService con los overrides de env dados y caché limpia."""
    import importlib
    from app.core import settings as settings_mod
    from app.services import jira_service as jira_mod

    # Limpiar caché de settings + sobrescribir env para que settings vea nuestros valores.
    settings_mod.get_settings.cache_clear()
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))

    # Reset del singleton para que cada test tenga un JiraService nuevo con settings nuevos.
    jira_mod._singleton = None
    importlib.reload(jira_mod)
    return jira_mod.get_jira_service()


def _mock_async_client(response: MagicMock):
    """Devuelve un callable que imita ``httpx.AsyncClient`` como context manager."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(return_value=response)
    client.get = AsyncMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
# Tests del camino deshabilitado
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disabled_create_returns_none(monkeypatch):
    """JIRA_ENABLED=false → ninguna llamada HTTP, devuelve None."""
    svc = _fresh_jira_service(monkeypatch, JIRA_ENABLED="false")
    assert svc.is_enabled is False
    with patch("app.services.jira_service.httpx.AsyncClient") as mock_client:
        key = await svc.create_patient_ticket(
            case_id="c1", summary="s", description="d",
        )
    assert key is None
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_comment_returns_false(monkeypatch):
    svc = _fresh_jira_service(monkeypatch, JIRA_ENABLED="false")
    with patch("app.services.jira_service.httpx.AsyncClient") as mock_client:
        ok = await svc.add_comment(ticket_key="KAN-1", body="x")
    assert ok is False
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_transition_returns_false(monkeypatch):
    svc = _fresh_jira_service(monkeypatch, JIRA_ENABLED="false")
    with patch("app.services.jira_service.httpx.AsyncClient") as mock_client:
        ok = await svc.transition(ticket_key="KAN-1", transition_id="31")
    assert ok is False
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_enabled_without_token_is_disabled(monkeypatch):
    """JIRA_ENABLED=true pero JIRA_API_TOKEN vacío → sigue deshabilitado."""
    svc = _fresh_jira_service(
        monkeypatch,
        JIRA_ENABLED="true",
        JIRA_EMAIL="someone@example.com",
        JIRA_API_TOKEN="",
    )
    assert svc.is_enabled is False


# ---------------------------------------------------------------------------
# Tests del camino habilitado (httpx mockeado)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enabled_create_serializes_adf_and_returns_key(monkeypatch):
    svc = _fresh_jira_service(
        monkeypatch,
        JIRA_ENABLED="true",
        JIRA_URL="https://example.atlassian.net",
        JIRA_EMAIL="me@example.com",
        JIRA_API_TOKEN="tkn",
        JIRA_PROJECT_KEY="KAN",
        JIRA_ISSUETYPE_NAME="Task",
    )
    assert svc.is_enabled is True

    response = MagicMock(status_code=201)
    response.json = MagicMock(return_value={"key": "KAN-42"})
    client = _mock_async_client(response)

    with patch("app.services.jira_service.httpx.AsyncClient", return_value=client):
        key = await svc.create_patient_ticket(
            case_id="abcd1234", summary="hello", description="body",
        )

    assert key == "KAN-42"
    # Verificar la estructura del payload de la request (Atlassian Document Format).
    args, kwargs = client.post.call_args
    assert args[0].endswith("/rest/api/3/issue")
    fields = kwargs["json"]["fields"]
    assert fields["project"]["key"] == "KAN"
    assert fields["issuetype"]["name"] == "Task"
    assert fields["summary"] == "hello"
    assert "case-abcd1234" in fields["labels"]
    # ADF: doc → paragraph → text
    desc = fields["description"]
    assert desc["type"] == "doc"
    assert desc["content"][0]["content"][0]["text"] == "body"
    # La cabecera Authorization tiene que ir, pero nunca se loguea aquí.
    assert "Authorization" in kwargs["headers"]
    assert kwargs["headers"]["Authorization"].startswith("Basic ")


@pytest.mark.asyncio
async def test_enabled_create_swallows_http_error(monkeypatch):
    """Un error de red NO debe propagarse — Jira es canal lateral."""
    import httpx

    svc = _fresh_jira_service(
        monkeypatch,
        JIRA_ENABLED="true",
        JIRA_EMAIL="me@example.com",
        JIRA_API_TOKEN="tkn",
    )
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(side_effect=httpx.ConnectError("dns fail"))

    with patch("app.services.jira_service.httpx.AsyncClient", return_value=client):
        key = await svc.create_patient_ticket(case_id="c", summary="s", description="d")
    assert key is None


@pytest.mark.asyncio
async def test_enabled_create_returns_none_on_4xx(monkeypatch):
    svc = _fresh_jira_service(
        monkeypatch,
        JIRA_ENABLED="true",
        JIRA_EMAIL="me@example.com",
        JIRA_API_TOKEN="tkn",
    )
    response = MagicMock(status_code=401, text="Unauthorized")
    client = _mock_async_client(response)
    with patch("app.services.jira_service.httpx.AsyncClient", return_value=client):
        key = await svc.create_patient_ticket(case_id="c", summary="s", description="d")
    assert key is None


@pytest.mark.asyncio
async def test_enabled_transition_uses_id_not_name(monkeypatch):
    svc = _fresh_jira_service(
        monkeypatch,
        JIRA_ENABLED="true",
        JIRA_EMAIL="me@example.com",
        JIRA_API_TOKEN="tkn",
    )
    response = MagicMock(status_code=204)
    client = _mock_async_client(response)
    with patch("app.services.jira_service.httpx.AsyncClient", return_value=client):
        ok = await svc.transition(ticket_key="KAN-7", transition_id="31")
    assert ok is True
    args, kwargs = client.post.call_args
    assert args[0].endswith("/rest/api/3/issue/KAN-7/transitions")
    assert kwargs["json"] == {"transition": {"id": "31"}}


@pytest.mark.asyncio
async def test_summary_truncation(monkeypatch):
    """El campo summary de Jira tope ~255 chars — truncamos a 250."""
    svc = _fresh_jira_service(
        monkeypatch,
        JIRA_ENABLED="true",
        JIRA_EMAIL="me@example.com",
        JIRA_API_TOKEN="tkn",
    )
    response = MagicMock(status_code=201)
    response.json = MagicMock(return_value={"key": "KAN-1"})
    client = _mock_async_client(response)
    long_summary = "a" * 500
    with patch("app.services.jira_service.httpx.AsyncClient", return_value=client):
        await svc.create_patient_ticket(case_id="c", summary=long_summary, description="d")
    fields = client.post.call_args.kwargs["json"]["fields"]
    assert len(fields["summary"]) == 250
