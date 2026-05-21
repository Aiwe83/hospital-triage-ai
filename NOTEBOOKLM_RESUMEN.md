# hospital-triage-ai — Resumen para NotebookLM

Documento fuente para NotebookLM. Pegar como source única o dividir por secciones.

---

## 1. Qué es el proyecto

MVP de **soporte a la decisión clínica en triaje de urgencias hospitalarias** mediante orquestación multiagente con LangGraph. **No emite diagnósticos** — la decisión médica final pertenece siempre al profesional sanitario. Cada informe incluye el descargo: *"Este sistema es únicamente soporte a la decisión clínica."*

Forma parte del curso Python/IA de Viewnext (autor: Pablo Defranchi). Producción-like, ejecutable localmente con Docker Compose.

---

## 2. Stack técnico

| Capa         | Tecnología |
|--------------|------------|
| Frontend     | Next.js 15 (App Router) + React + TypeScript + Tailwind + Zustand + Anime.js |
| Backend      | Python 3.11 + FastAPI + LangGraph + LangChain + sse-starlette + ReportLab |
| Persistencia | MongoDB 7 (driver async Motor) |
| RAG          | Elasticsearch 8 (BM25 sobre protocolos médicos) |
| Herramientas | Servidor MCP local (FastAPI MCP) |
| Exportación  | PDF → MCP `send_report_to_drive` → Google Drive Desktop |
| Infra        | Docker Compose, 5 servicios con healthchecks |

Prohibido por diseño: PostgreSQL, Supabase, Qdrant, Chroma, servicios solo-cloud, Vue/Angular/Svelte.

---

## 3. Arquitectura

```
[Next.js UI] --REST/SSE--> [FastAPI] --LangGraph--> 6 agentes secuenciales
                              |                       |
                              v                       v
                          MongoDB              Elasticsearch (RAG BM25)
                                                      |
                                            Servidor MCP local (FastAPI)
                                                      |
                                      ┌───────────────┴───────────────┐
                                hospital_context              send_report_to_drive
                                                                      │
                                                       Carpeta local sincronizada
                                                                      │
                                                       Google Drive Desktop → nube
```

Servicios Docker: `htai-backend`, `htai-frontend`, `htai-mongo`, `htai-elasticsearch`, `htai-mcp`.

---

## 4. Los 6 agentes LangGraph

1. **`triage_orchestrator`** — recibe el caso, delega flujo.
2. **`clinical_analyst`** — extrae señales de riesgo de síntomas + constantes vitales.
3. **`protocol_researcher`** — RAG sobre protocolos médicos en Elasticsearch (BM25).
4. **`hospital_systems_executor`** — invoca herramientas MCP (pruebas, recursos, tiempo de espera).
5. **`clinical_safety_validator`** — reglas de seguridad innegociables + descargo obligatorio.
6. **`report_writer`** — compone informe preliminar de soporte al triaje.

Cada nodo añade a `agent_trace` un registro `{agent_id, status, message, timestamp}` y emite un evento SSE al frontend.

---

## 5. Capa visual = observabilidad de la IA

La escena pixelada del hospital **no es decoración**, es vista en tiempo real del estado de LangGraph.

- Los sprites animan solo en respuesta a eventos reales del backend (no animaciones falsas).
- Estados posibles: `idle`, `receiving_case`, `thinking`, `walking`, `analyzing`, `searching`, `executing`, `validating`, `writing`, `discussing`, `completed`, `blocked`, `error`.
- Código de color: rojo = error/fallo de herramienta; amarillo = esperando/bloqueado; verde = completado.

---

## 6. Reglas de seguridad innegociables

Aplicadas por `clinical_safety_validator` sobre cada informe:

- **Nunca producir diagnóstico definitivo.**
- **Nunca prescribir dosis.**
- **Incluir siempre el descargo** *"Este sistema es únicamente soporte a la decisión clínica."*

---

## 7. Gateway LLM

Proxy compatible con OpenAI (NextAI/Azure/OpenAI). Variables clave:

- `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` (ej. `gpt-5-chat-nextai`)
- `LLM_USER_EMAIL` reenviado como cabecera `email` / `X-User-Email`
- `LLM_PROVIDER`, `LLM_ORIGIN`, `LLM_ORIGIN_DETAIL` exigidos por el proxy aigen
- `LLM_TIMEOUT=60`

---

## 8. Integración Google Drive (deliberadamente mínima)

**No usa Google API, OAuth, service account ni proyecto GCP.** Funciona así:

1. Backend genera PDF → llama `POST /tools/send_report_to_drive` del mcp-server.
2. mcp-server valida PDF y lo copia a `DRIVE_SYNC_FOLDER` como `informe_<patient>_<YYYY-MM-DD_HHMM>.pdf`.
3. **Google Drive Desktop** (en el host Windows/Mac) sincroniza esa carpeta a la nube automáticamente.

Readiness probe: `GET http://localhost:7800/tools/sync_status`. Si la carpeta no es escribible, fallback a modo `mock` para que la demo nunca se bloquee.

---

## 9. Endpoints clave del backend

| Método | Ruta | Propósito |
|--------|------|-----------|
| GET    | `/health` | Liveness + estado dependencias |
| POST   | `/triage` | Crear caso, ejecutar workflow LangGraph |
| GET    | `/triage/{id}` | Recuperar caso + trace + informe |
| GET    | `/triage/{id}/events` | Stream SSE por agente |
| POST   | `/triage/{id}/deliver` | Disparar entrega a Drive |
| GET    | `/triage/{id}/deliver/events` | SSE progreso entrega (7 pasos) |
| POST   | `/triage/{id}/jira/close` | Cerrar ticket Jira ligado al caso |

Swagger: `http://localhost:8000/docs`.

---

## 10. Estructura del repo

```
hospital-triage-ai/
├── backend/        FastAPI + LangGraph (6 agentes) + tests + seed scripts
│   └── app/        agents/ api/ core/ db/ schemas/ services/ main.py
├── frontend/       Next.js 15 (App Router, UI castellano)
├── mcp-server/     Servidor MCP local (server.py, jira_tools.py)
├── infra/          docker-compose.yml + Dockerfiles
├── reports/        PDFs generados (sincronizados a Drive)
├── docs/           Briefing: prompt V6, propuesta, guía Claude Code
├── data/, secrets/ Reservados (gitignored)
├── .env / .env.example
├── CLAUDE.md       Reglas Claude Code específicas
└── README.md
```

---

## 11. Setup y arranque

```bash
cp .env.example .env          # Rellenar claves LLM + DRIVE_SYNC_FOLDER
docker compose -f infra/docker-compose.yml up --build
```

Puertos: `3000` UI, `8000` API, `7800` MCP, `9200` ES, `27017` Mongo. Primer build ~3-5 min. Necesita ~4 GB RAM (ES reserva 512 MB de heap).

Smoke test:
```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/triage -H "Content-Type: application/json" \
  -d '{"patient":{"age":59,"sex":"M"},"symptoms":["chest pain","sweating"],"vitals":{"hr":118,"sbp":92}}'
```

---

## 12. Estilo de trabajo

- **Por fases** — no construir todo simultáneo. Validar cada fase (build + smoke + runtime) antes de seguir.
- Preferir editar ficheros existentes, evitar refactors amplios.
- Sin animaciones falsas desconectadas del estado real del backend.
- `REPORT_EXPORT_MODE=mock` por defecto; Drive/Gmail detrás de feature flag.

---

## 13. Troubleshooting frecuente

| Síntoma | Causa | Fix |
|---------|-------|-----|
| LLM `422 Field required: provider` | Proxy aigen exige cabeceras | Definir `LLM_PROVIDER`, `LLM_ORIGIN`, `LLM_ORIGIN_DETAIL` |
| Trace LangGraph vacío, caso instantáneo | LLM inalcanzable, fallback dispara | Revisar `LLM_BASE_URL`, logs `htai-backend` |
| Cambio en `.env` no aplica | `restart` no recarga env_file | `up -d --force-recreate <svc>` |
| ES sale con `max virtual memory areas` | `vm.max_map_count` bajo | `sudo sysctl -w vm.max_map_count=262144` |
| Entrega Drive `mode: mock` post-entrega | Timeout bridge expirado | Aumentar `DRIVE_BRIDGE_TIMEOUT`, sesión Claude activa |
| Curl con tildes rompe body | PowerShell mata UTF-8 | ASCII-only o `--data-binary @archivo.json` |

---

## 14. Preguntas que NotebookLM debería poder responder

- ¿Qué agentes componen el workflow y en qué orden ejecutan?
- ¿Cómo se sincroniza la UI con el estado del backend? (SSE + agent_trace)
- ¿Cómo se entrega un informe a Google Drive sin OAuth?
- ¿Qué reglas de seguridad clínica son innegociables?
- ¿Qué pasa si el LLM gateway falla? (fallback + estado bloqueado)
- ¿Cómo añadir un nuevo protocolo médico al RAG? (seed_protocols.py + Elasticsearch BM25)
- ¿Por qué Docker Compose y no Kubernetes? (MVP local, demo del curso)
