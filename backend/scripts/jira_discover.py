"""Script one-off de discovery para la integración con Jira.

Ejecútalo una vez tras rellenar JIRA_URL / JIRA_EMAIL / JIRA_API_TOKEN en
``.env``:

    docker exec htai-backend python -m scripts.jira_discover

Imprime:

* si las credenciales funcionan,
* el accountId del usuario (útil para futura asignación de médicos),
* los issue types declarados en el proyecto,
* un ticket de prueba creado al vuelo para poder leer las transiciones
  disponibles y los IDs que hay que copiar a
  ``JIRA_TRANSITION_ID_IN_PROGRESS`` y ``JIRA_TRANSITION_ID_DONE``.

El ticket de prueba se deja en el proyecto (con label
``triage-ia-discovery``) para que el operador verifique que aparece en el
board ``/2`` y ajuste el filtro del board si hace falta. Bórralo a mano
tras leer la salida.
"""

from __future__ import annotations

import asyncio
import base64
import sys

import httpx

from app.core.settings import get_settings


async def main() -> int:
    s = get_settings()
    if not s.jira_url or not s.jira_email or not s.jira_api_token:
        print("ERROR: JIRA_URL, JIRA_EMAIL and JIRA_API_TOKEN must be set in .env first.")
        return 2

    base = s.jira_url.rstrip("/")
    raw = f"{s.jira_email}:{s.jira_api_token}".encode("utf-8")
    headers = {
        "Authorization": "Basic " + base64.b64encode(raw).decode("ascii"),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        print(f"→ Verificando credenciales contra {base} ...")
        me = await client.get(f"{base}/rest/api/3/myself", headers=headers)
        if me.status_code != 200:
            print(f"   ✗ status={me.status_code} body={me.text[:300]}")
            print("   Confirma JIRA_EMAIL + JIRA_API_TOKEN (token, no contraseña).")
            return 2
        me_json = me.json()
        print(f"   ✓ Conectado como {me_json.get('displayName')} ({me_json.get('emailAddress')})")
        print(f"   accountId: {me_json.get('accountId')}")

        print(f"\n→ Leyendo proyecto {s.jira_project_key} ...")
        pj = await client.get(f"{base}/rest/api/3/project/{s.jira_project_key}", headers=headers)
        if pj.status_code != 200:
            print(f"   ✗ status={pj.status_code} body={pj.text[:300]}")
            print("   Revisa JIRA_PROJECT_KEY (ej. 'KAN').")
            return 2
        pj_json = pj.json()
        print(f"   ✓ Proyecto: {pj_json.get('name')} (key {pj_json.get('key')}, id {pj_json.get('id')})")
        issuetypes = [it["name"] for it in pj_json.get("issueTypes", [])]
        print(f"   Issue types disponibles: {issuetypes}")
        if s.jira_issuetype_name not in issuetypes:
            print(
                f"   ⚠ JIRA_ISSUETYPE_NAME='{s.jira_issuetype_name}' no está en la lista. "
                "Cambia .env al primero compatible (ej. 'Tarea' si la cuenta está en español)."
            )

        chosen_type = (
            s.jira_issuetype_name if s.jira_issuetype_name in issuetypes else (issuetypes[0] if issuetypes else "Task")
        )

        print(f"\n→ Creando ticket de prueba con issuetype='{chosen_type}' ...")
        create_body = {
            "fields": {
                "project": {"key": s.jira_project_key},
                "summary": "[discovery] Ticket de prueba — bórralo cuando hayas copiado los IDs",
                "issuetype": {"name": chosen_type},
                "labels": ["triage-ia-discovery"],
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Ticket creado por scripts/jira_discover.py para listar las transiciones disponibles.",
                                }
                            ],
                        }
                    ],
                },
            }
        }
        cr = await client.post(f"{base}/rest/api/3/issue", json=create_body, headers=headers)
        if cr.status_code not in (200, 201):
            print(f"   ✗ status={cr.status_code} body={cr.text[:500]}")
            print("   La cuenta puede no tener permisos de creación o el issuetype no es válido.")
            return 2
        key = cr.json().get("key")
        print(f"   ✓ Ticket creado: {key}")
        print(
            f"   Abre {base}/browse/{key} y verifica que también aparece en el board "
            f"{base}/jira/software/projects/{s.jira_project_key}/boards/2"
        )

        print(f"\n→ Listando transiciones disponibles para {key} ...")
        tr = await client.get(f"{base}/rest/api/3/issue/{key}/transitions", headers=headers)
        if tr.status_code != 200:
            print(f"   ✗ status={tr.status_code} body={tr.text[:300]}")
            return 2
        transitions = tr.json().get("transitions", [])
        if not transitions:
            print("   ⚠ Sin transiciones disponibles — workflow personalizado bloqueado.")
        for t in transitions:
            target = t.get("to", {}).get("name", "?")
            print(f"   • id={t['id']:>4}   nombre='{t['name']}'   ▶ destino '{target}'")

        print("\nCopia los IDs apropiados a tu .env:")
        print("   JIRA_TRANSITION_ID_IN_PROGRESS=<id de la transición hacia 'En curso' o equivalente>")
        print("   JIRA_TRANSITION_ID_DONE=<id de la transición hacia 'Listo' o equivalente>")
        print("Luego pon JIRA_ENABLED=true y reinicia el backend:")
        print("   docker compose -f infra/docker-compose.yml up -d --force-recreate backend")
        print("\n(Recuerda borrar manualmente el ticket de discovery cuando termines.)")
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
