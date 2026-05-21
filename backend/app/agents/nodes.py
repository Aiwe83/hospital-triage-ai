"""Implementación de los nodos LangGraph del workflow de triaje.

Cada nodo:
  1. emite un evento de inicio (status=thinking/analyzing/...)
  2. hace su trabajo (llamada al LLM + servicio si hace falta)
  3. emite un evento de finalización (status=completed) o de error
  4. devuelve un dict parcial de estado para fusionar en TriageState
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.events import bus
from app.agents.state import TriageState
from app.core.llm import get_chat_llm
from app.core.logging import get_logger
from app.schemas.triage import AgentEvent
from app.services.protocols import search_protocols
from app.services.mcp_client import fetch_hospital_context

log = get_logger(__name__)


# ---------- helpers ----------

async def _emit(case_id: str, event: AgentEvent) -> list[AgentEvent]:
    await bus.publish(case_id, event)
    return [event]


def _safe_json(content: str, fallback: dict | list) -> Any:
    try:
        return json.loads(content)
    except Exception:
        # Los modelos a menudo envuelven el JSON entre fences de markdown.
        stripped = content.strip().strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
        try:
            return json.loads(stripped)
        except Exception:
            log.warning("llm_json_parse_failed", content=content[:300])
            return fallback


async def _llm_json(system: str, user: str, fallback: Any) -> Any:
    """Llama al LLM y parsea JSON. Ante cualquier fallo devuelve el fallback.

    Mantiene vivo el workflow de demo cuando el gateway LLM no se puede
    alcanzar (DNS, SSL, auth, rate limit). El nodo sigue emitiendo sus
    eventos de trace.
    """
    try:
        llm = get_chat_llm()
        resp = await llm.ainvoke([SystemMessage(content=system), HumanMessage(content=user)])
        return _safe_json(resp.content, fallback)
    except Exception as e:
        log.warning("llm_call_failed", error=str(e))
        return fallback


def _heuristic_analysis(intake) -> dict:
    """Extracción determinista de señales de riesgo como fallback cuando el LLM no está disponible.

    Reglas conservadoras para que la salida de la demo siga siendo creíble offline.
    Etiquetas en castellano — estos mensajes llegan al agent trace y al PDF.
    """
    v = intake.vital_signs
    red_flags: list[str] = []
    concerning: list[str] = []
    risk: list[str] = []
    categories: list[str] = []

    text = (intake.symptoms or "").lower()
    cardiac_kw = ["dolor torácico", "dolor toracico", "opresivo", "irradiado", "sudoración", "sudoracion",
                  "chest pain", "diaphoresis", "radiating"]
    if any(k in text for k in cardiac_kw):
        red_flags.append("Posibles signos de síndrome coronario agudo")
        categories.append("cardiac")
    resp_kw = ["disnea", "sibilancias", "respiratorio", "tiraje", "ahogo",
               "short of breath", "shortness of breath", "dyspnea", "wheezing"]
    if any(k in text for k in resp_kw):
        categories.append("respiratory")
        if v.oxygen_saturation is not None and v.oxygen_saturation < 92:
            red_flags.append(f"Hipoxia (SpO₂ {v.oxygen_saturation}%)")
    stroke_kw = ["ictus", "hemiparesia", "disartria", "asimetría facial", "asimetria facial",
                 "afasia", "stroke", "facial droop", "slurred speech"]
    if any(k in text for k in stroke_kw):
        red_flags.append("Posibles signos de ictus")
        categories.append("neurological")
    fever_kw = ["fiebre", "escalofríos", "escalofrios", "fever", "chills"]
    if any(k in text for k in fever_kw):
        categories.append("infection_sepsis")
        if v.temperature_celsius and v.temperature_celsius >= 38.5:
            concerning.append(f"Fiebre {v.temperature_celsius} °C")
    abd_kw = ["dolor abdominal", "abdomen", "vómitos", "vomitos", "melenas",
              "abdominal", "belly", "vomit"]
    if any(k in text for k in abd_kw):
        categories.append("abdominal")
    airway_kw = ["inconsciente", "no responde", "síncope", "sincope", "parada cardíaca",
                 "parada cardiaca", "vía aérea", "via aerea",
                 "unconscious", "unresponsive", "syncope", "cardiac arrest", "airway"]
    if any(k in text for k in airway_kw):
        red_flags.append("Compromiso de la vía aérea o del nivel de consciencia")
        categories.append("airway_breathing_circulation")

    if v.heart_rate is not None and (v.heart_rate < 50 or v.heart_rate > 120):
        concerning.append(f"Frecuencia cardíaca {v.heart_rate} lpm")
    if v.respiratory_rate is not None and v.respiratory_rate >= 24:
        concerning.append(f"Taquipnea (FR {v.respiratory_rate})")
    if v.blood_pressure_systolic is not None and v.blood_pressure_systolic < 90:
        red_flags.append(f"Hipotensión (PAS {v.blood_pressure_systolic})")
    if v.oxygen_saturation is not None and v.oxygen_saturation < 90:
        red_flags.append(f"Hipoxia grave (SpO₂ {v.oxygen_saturation}%)")

    if intake.age >= 65:
        risk.append("Edad avanzada")
    if intake.medical_history:
        risk.append(f"Comorbilidades: {intake.medical_history}")

    if not categories:
        categories = ["general"]
    return {
        "risk_factors": risk,
        "red_flags": red_flags,
        "concerning_vitals": concerning,
        "suspected_categories": categories,
    }


# ---------- nodes ----------

async def orchestrator_node(state: TriageState) -> dict:
    case_id = state["case_id"]
    intake = state["intake"]
    start = await _emit(case_id, AgentEvent(
        agent_id="triage_orchestrator",
        status="receiving_case",
        message=f"Caso recibido: paciente de {intake.age} años. Delegando en los especialistas.",
        data={"age": intake.age, "arrival_mode": intake.arrival_mode},
    ))
    done = await _emit(case_id, AgentEvent(
        agent_id="triage_orchestrator",
        status="completed",
        message="Traspaso a los agentes especialistas completado.",
    ))
    return {"agent_trace": start + done}


async def clinical_analyst_node(state: TriageState) -> dict:
    case_id = state["case_id"]
    intake = state["intake"]

    start = await _emit(case_id, AgentEvent(
        agent_id="clinical_analyst",
        status="analyzing",
        message="Extrayendo señales de riesgo de los síntomas y las constantes.",
    ))

    system = (
        "Eres un analista clínico que da soporte a un flujo de triaje de Urgencias. "
        "NO emites diagnóstico. Solo extraes señales de riesgo y red flags. "
        "Redacta SIEMPRE en castellano (español de España). Mantén identificadores "
        "técnicos en inglés (categorías). Devuelve JSON estricto con las claves: "
        "risk_factors (list[str]), red_flags (list[str]), concerning_vitals "
        "(list[str]), suspected_categories (list[str])."
    )
    user = (
        f"Edad del paciente: {intake.age}\n"
        f"Sexo: {intake.sex}\n"
        f"Síntomas: {intake.symptoms}\n"
        f"Antecedentes: {intake.medical_history}\n"
        f"Medicación: {intake.medications}\n"
        f"Alergias: {intake.allergies}\n"
        f"Constantes: {intake.vital_signs.model_dump()}\n"
        f"Llegada: {intake.arrival_mode}\n"
        "Devuelve solo JSON."
    )

    analysis = await _llm_json(system, user, fallback=_heuristic_analysis(intake))
    # Si el LLM devolvió vacío, enriquecemos con la heurística para que los nodos posteriores tengan señal.
    if not analysis.get("suspected_categories"):
        heur = _heuristic_analysis(intake)
        for k, v in heur.items():
            if not analysis.get(k):
                analysis[k] = v

    done = await _emit(case_id, AgentEvent(
        agent_id="clinical_analyst",
        status="completed",
        message=f"Detectado(s) {len(analysis.get('red_flags', []))} red flag(s).",
        data=analysis,
    ))
    return {"agent_trace": start + done, "clinical_analysis": analysis}


async def protocol_researcher_node(state: TriageState) -> dict:
    case_id = state["case_id"]
    intake = state["intake"]
    analysis = state.get("clinical_analysis", {})

    start = await _emit(case_id, AgentEvent(
        agent_id="protocol_researcher",
        status="searching",
        message="Buscando en el corpus de protocolos (Elasticsearch BM25).",
    ))

    query_parts = [intake.symptoms]
    query_parts.extend(analysis.get("suspected_categories", []))
    query_parts.extend(analysis.get("red_flags", []))
    query = " ".join(p for p in query_parts if p)

    try:
        protocols = await search_protocols(query, limit=3)
        status = "completed"
        msg = f"Recuperado(s) {len(protocols)} protocolo(s)."
    except Exception as e:
        protocols = []
        status = "error"
        msg = f"Fallo en la búsqueda de protocolos: {e}"
        log.warning("protocol_search_failed", error=str(e))

    done = await _emit(case_id, AgentEvent(
        agent_id="protocol_researcher",
        status=status,
        message=msg,
        data={"query": query, "matches": len(protocols)},
    ))
    return {"agent_trace": start + done, "protocols": {"items": protocols, "query": query}}


async def hospital_systems_executor_node(state: TriageState) -> dict:
    case_id = state["case_id"]
    analysis = state.get("clinical_analysis", {})

    start = await _emit(case_id, AgentEvent(
        agent_id="hospital_systems_executor",
        status="executing",
        message="Invocando herramientas MCP del hospital (pruebas, recursos, tiempos de espera).",
    ))

    try:
        ctx = await fetch_hospital_context(
            suspected_categories=analysis.get("suspected_categories", []),
        )
        status = "completed"
        msg = "Llamadas a herramientas MCP completadas."
    except Exception as e:
        ctx = {
            "available_tests": [],
            "resources": {"available": False, "reason": "mcp_unavailable"},
            "estimated_wait_minutes": None,
            "fallback": True,
        }
        status = "blocked"
        msg = f"MCP no disponible, usando fallback: {e}"
        log.warning("mcp_unavailable", error=str(e))

    done = await _emit(case_id, AgentEvent(
        agent_id="hospital_systems_executor",
        status=status,
        message=msg,
        data=ctx,
    ))
    return {"agent_trace": start + done, "hospital_context": ctx}


async def clinical_safety_validator_node(state: TriageState) -> dict:
    case_id = state["case_id"]
    analysis = state.get("clinical_analysis", {})

    start = await _emit(case_id, AgentEvent(
        agent_id="clinical_safety_validator",
        status="validating",
        message="Validando reglas de seguridad y aviso clínico.",
    ))

    red_flags = analysis.get("red_flags", []) or []
    concerning = analysis.get("concerning_vitals", []) or []

    # Heurística determinista de prioridad. El LLM no decide la prioridad por sí solo.
    if any("airway" in f.lower() or "unconscious" in f.lower() or "cardiac arrest" in f.lower() for f in red_flags):
        priority = "critical"
    elif red_flags or len(concerning) >= 2:
        priority = "urgent"
    elif concerning:
        priority = "standard"
    else:
        priority = "non_urgent"

    safety = {
        "priority": priority,
        "disclaimer_required": True,
        "diagnosis_blocked": True,
        "reason": f"{len(red_flags)} red flag(s), {len(concerning)} constante(s) preocupante(s).",
    }

    priority_es = {
        "critical": "crítica",
        "urgent": "urgente",
        "standard": "estándar",
        "non_urgent": "no urgente",
    }.get(priority, priority)

    done = await _emit(case_id, AgentEvent(
        agent_id="clinical_safety_validator",
        status="completed",
        message=f"Prioridad sugerida: {priority_es}.",
        data=safety,
    ))
    return {"agent_trace": start + done, "safety": safety}


async def report_writer_node(state: TriageState) -> dict:
    from app.schemas.triage import TriageReport

    case_id = state["case_id"]
    intake = state["intake"]
    analysis = state.get("clinical_analysis", {})
    protocols = state.get("protocols", {}).get("items", []) or []
    hospital_ctx = state.get("hospital_context", {}) or {}
    safety = state.get("safety", {}) or {}

    start = await _emit(case_id, AgentEvent(
        agent_id="report_writer",
        status="writing",
        message="Redactando el informe de soporte al triaje.",
    ))

    system = (
        "Eres el redactor del informe de un sistema de soporte a la decisión clínica "
        "en Urgencias. Redacta SIEMPRE en castellano (español de España). "
        "Escribe un resumen clínico conciso de 3 a 5 frases. "
        "NO emites diagnóstico. Usa expresiones como 'sugiere', 'compatible con', "
        "'considerar'. Recuerda siempre que la decisión final corresponde al "
        "profesional sanitario. Devuelve JSON estricto con las claves: summary "
        "(str), recommended_next_steps (list[str]). Los pasos siguientes deben "
        "estar también en castellano."
    )
    user = (
        f"Paciente: edad {intake.age}, sexo {intake.sex}.\n"
        f"Síntomas: {intake.symptoms}\n"
        f"Constantes: {intake.vital_signs.model_dump()}\n"
        f"Factores de riesgo: {analysis.get('risk_factors', [])}\n"
        f"Red flags: {analysis.get('red_flags', [])}\n"
        f"Prioridad sugerida: {safety.get('priority')}\n"
        f"Pruebas disponibles: {hospital_ctx.get('available_tests', [])}\n"
        f"Tiempo estimado de espera: {hospital_ctx.get('estimated_wait_minutes')} minutos\n"
        f"Protocolos recuperados: {[p.get('title') for p in protocols]}\n"
        "Devuelve solo JSON."
    )
    # Resumen heurístico de fallback para que el informe sea informativo incluso offline.
    priority = safety.get("priority", "standard")
    rf = analysis.get("red_flags", []) or []
    cv = analysis.get("concerning_vitals", []) or []
    cats = analysis.get("suspected_categories", []) or []
    heuristic_steps = []
    if "respiratory" in cats:
        heuristic_steps += [
            "Oxígeno si SpO₂ < 94 %",
            "Radiografía de tórax",
            "Gasometría arterial",
        ]
    if "cardiac" in cats:
        heuristic_steps += [
            "ECG de 12 derivaciones en los primeros 10 minutos",
            "Troponina seriada",
            "Interconsulta a Cardiología",
        ]
    if "neurological" in cats:
        heuristic_steps += [
            "TC craneal sin contraste",
            "Glucemia capilar",
            "Valoración NIHSS",
        ]
    if "infection_sepsis" in cats:
        heuristic_steps += [
            "Dos hemocultivos",
            "Lactato",
            "Antibioterapia de amplio espectro si se confirma sospecha de sepsis",
        ]
    if "abdominal" in cats:
        heuristic_steps += [
            "Analítica con amilasa/lipasa",
            "Ecografía abdominal a demanda clínica",
            "Reevaluación de dolor cada 15 minutos",
        ]
    if "allergy" in cats:
        heuristic_steps += [
            "Adrenalina IM si signos de anafilaxia",
            "Antihistamínicos y corticoides",
            "Observación mínima de 4-6 horas",
        ]
    if "airway_breathing_circulation" in cats:
        heuristic_steps += [
            "Activación inmediata de equipo de reanimación",
            "Soporte de vía aérea y oxígeno",
            "Acceso intravenoso doble y monitorización continua",
        ]
    if not heuristic_steps:
        heuristic_steps = [
            "Valoración por el clínico responsable",
            "Reevaluación de constantes cada 15 minutos",
        ]

    priority_es = {
        "critical": "crítica",
        "urgent": "urgente",
        "standard": "estándar",
        "non_urgent": "no urgente",
    }.get(priority, priority)
    fallback_summary = (
        f"Paciente de {intake.age} años con síntomas: {intake.symptoms[:160]}. "
        f"Prioridad sugerida {priority_es}. "
        f"{len(rf)} red flag(s) y {len(cv)} constante(s) preocupante(s). "
        "Se requiere valoración por el clínico responsable para la decisión final."
    )

    composed = await _llm_json(system, user, fallback={
        "summary": fallback_summary,
        "recommended_next_steps": heuristic_steps,
    })

    report = TriageReport(
        case_id=case_id,
        suggested_priority=safety.get("priority", "standard"),
        risk_factors=analysis.get("risk_factors", []),
        recommended_next_steps=composed.get("recommended_next_steps", []),
        retrieved_protocols=[
            {"title": p.get("title"), "id": p.get("id"), "score": p.get("score")}
            for p in protocols
        ],
        summary=composed.get("summary", ""),
    )

    done = await _emit(case_id, AgentEvent(
        agent_id="report_writer",
        status="completed",
        message="Informe listo.",
        data={"priority": report.suggested_priority},
    ))
    return {"agent_trace": start + done, "report": report}
