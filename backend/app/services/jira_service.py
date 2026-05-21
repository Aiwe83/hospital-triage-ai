"""Cliente REST ligero para Jira Cloud, usado por el workflow de triaje.

Decisiones de diseño:

* Usamos ``httpx`` directamente en lugar de meter ``atlassian-python-api``.
  Los cuatro endpoints que tocamos (crear issue, comentar, transiciones,
  user-search) son estables y suficientemente pequeños como para que una
  librería wrapper aportara más riesgo (logging de cabeceras auth, churn
  en el pin de versión) que valor.

* El servicio se puede instanciar de forma segura aunque Jira esté
  deshabilitado. El flag ``is_enabled`` hace que cada llamada sea un
  no-op, así el workflow de triaje sigue funcionando sin cambios cuando
  el operador no ha proporcionado un token.

* Los errores HTTP se tragan y se loguean. Un fallo de Jira nunca debe
  romper el flujo de triaje — Jira es un canal lateral, no una
  dependencia dura.

* La REST API de Atlassian usa Basic auth con el e-mail del usuario más
  un token API (NO la contraseña). Los tokens se crean en
  ``id.atlassian.com/manage-profile/security/api-tokens``.
"""

from __future__ import annotations

import base64
from typing import Any, Optional

import httpx

from app.core.logging import get_logger
from app.core.settings import get_settings

log = get_logger(__name__)


class JiraService:
    """Una instancia por proceso, creada vía :func:`get_jira_service`."""

    def __init__(self) -> None:
        s = get_settings()
        self._enabled = s.jira_ready
        self._base = s.jira_url.rstrip("/")
        self._project = s.jira_project_key
        self._issuetype = s.jira_issuetype_name
        self._labels = s.jira_label_list
        self._timeout = s.jira_timeout
        self._transition_in_progress = s.jira_transition_id_in_progress
        self._transition_done = s.jira_transition_id_done
        # La cabecera de auth se calcula una vez y se reutiliza. El token
        # nunca llega a logs porque solo pasamos `self._headers` y nunca lo imprimimos.
        if self._enabled:
            raw = f"{s.jira_email}:{s.jira_api_token}".encode("utf-8")
            self._headers = {
                "Authorization": "Basic " + base64.b64encode(raw).decode("ascii"),
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        else:
            self._headers = {}

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def create_patient_ticket(
        self,
        *,
        case_id: str,
        summary: str,
        description: str,
        priority: Optional[str] = None,
    ) -> Optional[str]:
        """Crea un issue en el proyecto configurado y devuelve su key.

        Devuelve ``None`` ante cualquier fallo (incluido ``is_enabled == False``)
        para que el caller pueda continuar sin ramificar por excepciones.
        """
        if not self._enabled:
            return None

        # La descripción tiene que ir en Atlassian Document Format. Enviamos
        # un único párrafo de texto plano — suficiente para la demo, no hace
        # falta renderizado de markdown dentro de Jira.
        adf_description = {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": description}],
                }
            ],
        }
        fields: dict[str, Any] = {
            "project": {"key": self._project},
            "summary": summary[:250],  # límite duro de Jira ~255 chars
            "description": adf_description,
            "issuetype": {"name": self._issuetype},
            "labels": list({*self._labels, f"case-{case_id}"}),
        }
        payload = {"fields": fields}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(
                    f"{self._base}/rest/api/3/issue",
                    json=payload,
                    headers=self._headers,
                )
        except httpx.HTTPError as e:
            log.warning("jira_create_failed", error=str(e), case_id=case_id)
            return None
        if r.status_code not in (200, 201):
            log.warning(
                "jira_create_rejected",
                status=r.status_code,
                body=r.text[:400],
                case_id=case_id,
            )
            return None
        try:
            return r.json().get("key")
        except Exception:
            return None

    async def add_comment(self, *, ticket_key: str, body: str) -> bool:
        if not self._enabled or not ticket_key:
            return False
        adf = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": body}],
                    }
                ],
            }
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(
                    f"{self._base}/rest/api/3/issue/{ticket_key}/comment",
                    json=adf,
                    headers=self._headers,
                )
        except httpx.HTTPError as e:
            log.warning("jira_comment_failed", error=str(e), key=ticket_key)
            return False
        ok = r.status_code in (200, 201)
        if not ok:
            log.warning("jira_comment_rejected", status=r.status_code, body=r.text[:400])
        return ok

    async def transition(self, *, ticket_key: str, transition_id: str) -> bool:
        """Mueve un ticket a la transición indicada (por ID, no por nombre)."""
        if not self._enabled or not ticket_key or not transition_id:
            return False
        payload = {"transition": {"id": str(transition_id)}}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                r = await client.post(
                    f"{self._base}/rest/api/3/issue/{ticket_key}/transitions",
                    json=payload,
                    headers=self._headers,
                )
        except httpx.HTTPError as e:
            log.warning("jira_transition_failed", error=str(e), key=ticket_key)
            return False
        ok = r.status_code in (200, 204)
        if not ok:
            log.warning("jira_transition_rejected", status=r.status_code, body=r.text[:400])
        return ok

    async def transition_in_progress(self, ticket_key: str) -> bool:
        """Mueve el ticket a un estado en curso si el workflow tiene uno.

        Algunos workflows Kanban solo exponen dos estados (p. ej.
        ``Por hacer`` → ``En curso`` donde ``En curso`` ya pertenece a la
        categoría ``done``). En ese caso NO debemos avanzar al inicio —
        hacerlo cerraría el ticket antes de que llegue el informe.

        Estrategia: listar transiciones, preferir una cuyo destino esté en
        la categoría ``indeterminate`` (en curso). Caer al ID configurado
        solo si aterriza en ``indeterminate``.
        """
        if not self._enabled or not ticket_key:
            return False
        transitions = await self.list_transitions(ticket_key)
        forward = next(
            (t for t in transitions
             if (t.get("to") or {}).get("statusCategory", {}).get("key") == "indeterminate"),
            None,
        )
        if forward:
            return await self.transition(ticket_key=ticket_key, transition_id=str(forward["id"]))
        # Ningún estado indeterminate en este workflow — dejamos el ticket
        # en su columna "new" actual para que close_case lo avance luego.
        log.info("jira_no_in_progress_state", key=ticket_key,
                 hint="workflow has no indeterminate state; ticket stays in new column")
        return False

    async def transition_done(self, ticket_key: str) -> bool:
        """Mueve el ticket a un estado de la categoría ``done``.

        Prefiere una transición directa; si el ID configurado aterriza en
        un estado no-done buscamos cualquier transición cuyo destino esté
        en la categoría ``done``. El recorrido completo multi-salto vive en
        :func:`app.services.jira_hooks.close_case`.
        """
        if not self._enabled or not ticket_key:
            return False
        transitions = await self.list_transitions(ticket_key)
        done = next(
            (t for t in transitions
             if (t.get("to") or {}).get("statusCategory", {}).get("key") == "done"),
            None,
        )
        if done:
            return await self.transition(ticket_key=ticket_key, transition_id=str(done["id"]))
        log.warning("jira_no_done_transition_direct", key=ticket_key,
                    available=[t.get("name") for t in transitions])
        return False

    async def list_transitions(self, ticket_key: str) -> list[dict]:
        """Helper para el script de descubrimiento — obtiene las transiciones disponibles."""
        if not self._enabled:
            return []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(
                f"{self._base}/rest/api/3/issue/{ticket_key}/transitions",
                headers=self._headers,
            )
        if r.status_code != 200:
            log.warning("jira_list_transitions_rejected", status=r.status_code)
            return []
        return r.json().get("transitions", [])


_singleton: Optional[JiraService] = None


def get_jira_service() -> JiraService:
    global _singleton
    if _singleton is None:
        _singleton = JiraService()
    return _singleton
