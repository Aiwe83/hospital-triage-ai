# CLAUDE.md — hospital-triage-ai

Instrucciones específicas del proyecto para Claude Code cuando trabaje en este repositorio.

## Misión

Construir un MVP autónomo de soporte a la decisión clínica de triaje con orquestación multiagente, listo para demo.
Calidad similar a producción, ejecutable localmente vía Docker.
**No** es una aplicación OpenClaw — OpenClaw es solo inspiración visual.

## Stack (fijo — no sustituir)

- Frontend: Next.js + React + TypeScript + Tailwind
- Backend: FastAPI + LangGraph + LangChain (Python 3.11)
- MongoDB (persistencia) + Elasticsearch (RAG, BM25)
- Servidor MCP local (solo uno) — simulación de herramientas hospitalarias
- Docker Compose para la infraestructura local

Prohibido: PostgreSQL, Supabase, Qdrant, Chroma, servicios solo en la nube, Vue/Angular/Svelte.

## Agentes (nodos LangGraph)

```
orchestrator -> clinical_analyst -> protocol_researcher
             -> hospital_systems_executor (MCP)
             -> clinical_safety_validator -> report_writer
```

Cada nodo debe añadir a `agent_trace`: `{agent_id, status, message, timestamp}`.
Cada nodo debe emitir un evento SSE para que la capa visual del frontend se sincronice en tiempo real.

## Capa visual = observabilidad de la IA

La escena pixelada del hospital **no es decoración**. Es una vista en tiempo real del estado de LangGraph.
- Los agentes solo animan en respuesta a eventos reales del backend.
- Estados: idle / receiving_case / thinking / walking / analyzing / searching / executing / validating / writing / discussing / completed / blocked / error.
- Rojo = error/fallo de herramienta; amarillo = esperando/bloqueado; verde = completado.

## Reglas de seguridad (innegociables)

- Nunca producir un diagnóstico definitivo.
- Nunca prescribir dosis.
- Incluir siempre el descargo: *"Este sistema es únicamente soporte a la decisión clínica."*
- `clinical_safety_validator` lo aplica sobre cada informe.

## Estilo de trabajo

- Por fases: no construir todas las fases simultáneamente.
- Validar cada fase antes de continuar (build, smoke test, verificación en runtime).
- Preferir editar ficheros existentes; evitar refactors amplios.
- Sin animaciones falsas desconectadas del estado del backend.

## Gateway LLM

Proxy compatible con OpenAI. Configurar vía env: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_USER_EMAIL`.
El email del usuario se reenvía como cabecera de identificación por el wrapper del cliente LLM.

## Exportación

Por defecto `REPORT_EXPORT_MODE=mock` — escribe el PDF en `/reports/`. Drive/Gmail reales detrás de feature flag.
