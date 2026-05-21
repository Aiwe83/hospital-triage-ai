"""Esquemas Pydantic del flujo de triage.

¿Qué es esto y por qué existe?
-------------------------------
Pydantic es la librería que valida y serializa los datos que entran y
salen del backend. Cada clase declarada aquí es un "modelo": una caja
con campos tipados que:

  1. **Valida automáticamente** lo que llega por HTTP (FastAPI rechaza
     con 422 si falta un campo obligatorio o si el tipo es incorrecto).
  2. **Documenta el contrato** — el Swagger en /docs se genera leyendo
     justo estos modelos.
  3. **Sirve como única fuente de verdad** del shape de los datos: si
     mañana cambia un campo aquí, todo el código que lo use saltará
     en IDE / mypy / runtime.

Estructura del archivo (de arriba a abajo):
  * **Input**  — lo que el usuario envía cuando crea un caso.
  * **Trace**  — los "fotogramas" que cada agente emite mientras trabaja.
  * **Output** — el informe final + el caso completo persistido.

Glosario rápido para un junior:
  * ``BaseModel``         clase de Pydantic. Heredar de ella convierte
                          tu clase en un modelo validado.
  * ``Field(...)``        marca el campo como obligatorio (sin default).
  * ``Field(None)``       campo opcional con default ``None``.
  * ``ge=0`` ``le=100``   "greater or equal / less or equal" — rangos
                          numéricos.
  * ``Literal["a","b"]``  el campo SÓLO puede valer "a" o "b".
  * ``Optional[X]``       equivale a ``X | None``.
  * ``default_factory``   se usa cuando el default es un objeto mutable
                          (lista, dict, instancia). Si pusieras
                          ``default=[]`` todas las instancias compartirían
                          la MISMA lista — un bug clásico.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------- Input ----------
# Lo que el frontend manda en POST /triage. Modelo del paciente al
# llegar a urgencias: síntomas, edad, constantes vitales, etc.

class VitalSigns(BaseModel):
    """Constantes vitales del paciente.

    Todas son opcionales porque en triage real a veces no se han
    medido todavía (p. ej. el paciente acaba de llegar). Si llegan,
    pasan validación de rango básica.
    """

    # Pulsaciones por minuto. Rango duro acepta bradi/taqui-cardia
    # severas pero rechaza basura (negativos, valores >250 imposibles).
    heart_rate: Optional[int] = Field(None, ge=20, le=250, description="Pulsaciones por minuto")

    # Tensión arterial separada en sistólica/diastólica.
    # Rangos cubren shock profundo hasta crisis hipertensiva extrema.
    blood_pressure_systolic: Optional[int] = Field(None, ge=40, le=260)
    blood_pressure_diastolic: Optional[int] = Field(None, ge=20, le=200)

    # Frecuencia respiratoria. Apnea casi 0 hasta taquipnea extrema.
    respiratory_rate: Optional[int] = Field(None, ge=4, le=80)

    # SpO2 en porcentaje. Mínimo 50 — por debajo es incompatible con
    # vida sostenida, casi seguro error de medición.
    oxygen_saturation: Optional[float] = Field(None, ge=50, le=100)

    # Temperatura corporal en grados Celsius. Hipotermia severa 28 a
    # hipertermia 44 (más allá muerte celular). Bloquea typos tipo 60.
    temperature_celsius: Optional[float] = Field(None, ge=28, le=44)

    # Escala de dolor visual analógica 0–10 (estándar internacional).
    pain_score: Optional[int] = Field(None, ge=0, le=10)


class TriageIntake(BaseModel):
    """El "formulario de admisión" — lo único OBLIGATORIO para arrancar.

    Sin estos datos no podemos arrancar el workflow de los 6 agentes.
    El resto del estado (trace, report, delivery) se irá rellenando
    conforme el pipeline avance.
    """

    # `...` significa "obligatorio sin default". min_length=3 evita que
    # el frontend mande cadenas vacías que serían inútiles para el LLM.
    symptoms: str = Field(..., min_length=3)

    # Rango humanamente plausible. >130 años seguramente es un error de
    # entrada (un cero de más, un typo, etc.).
    age: int = Field(..., ge=0, le=130)

    # `Literal[...]` restringe los valores permitidos. "unknown" es el
    # default porque no siempre se documenta el sexo en triage rápido.
    sex: Optional[Literal["male", "female", "other", "unknown"]] = "unknown"

    # Texto libre — el clinical_analyst los usa como contexto extra.
    medical_history: Optional[str] = ""
    medications: Optional[str] = ""
    allergies: Optional[str] = ""

    # Si no se manda, se crea un VitalSigns vacío. Usamos
    # default_factory porque VitalSigns es un objeto mutable: con
    # default=VitalSigns() todas las TriageIntake compartirían la
    # misma instancia y modificarla en una afectaría a las demás.
    vital_signs: VitalSigns = Field(default_factory=VitalSigns)

    # Cómo llegó el paciente — relevante para priorización.
    arrival_mode: Optional[Literal["walk_in", "ambulance", "transfer"]] = "walk_in"


# ---------- Trace ----------
# El trace son los "eventos" que cada agente emite mientras trabaja.
# Sirve para dos cosas:
#   1. Mandar updates al frontend por SSE (Server-Sent Events) y
#      animar la escena de píxeles de los agentes.
#   2. Guardar un audit log de qué ha hecho cada agente — útil para
#      depurar y para mostrar transparencia al profesional sanitario.

# Lista cerrada de estados posibles. Si añades uno nuevo, Pydantic
# fallará en cualquier código que asigne un estado no presente aquí —
# es justo lo que queremos, te obliga a actualizar todos los sitios.
AgentStatus = Literal[
    "idle", "receiving_case", "thinking", "walking", "analyzing",
    "searching", "executing", "validating", "writing", "discussing",
    "completed", "blocked", "error",
]


class AgentEvent(BaseModel):
    """Un único frame de actividad de un agente.

    Cada nodo de LangGraph appende uno (o varios) de estos a
    ``TriageCase.agent_trace`` y emite paralelamente uno por SSE.
    """

    agent_id: str             # Nombre del agente ("clinical_analyst", etc.)
    status: AgentStatus       # Qué está haciendo ahora mismo
    message: str              # Texto humano (lo verá el operador)
    # utcnow() en lugar de now() para evitar problemas de zona horaria
    # cuando este JSON viaja al frontend o se guarda en Mongo.
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    # Bolsa libre para datos opcionales (p. ej. nombre del protocolo
    # encontrado por RAG). Se mantiene sin tipado fuerte a propósito —
    # cada agente puede meter lo que necesite sin tocar el esquema.
    data: dict = Field(default_factory=dict)


# ---------- Output ----------

# Las 4 prioridades estilo Manchester/ESI. El validator del informe
# garantiza que SIEMPRE caemos en una de ellas.
Priority = Literal["critical", "urgent", "standard", "non_urgent"]


class TriageReport(BaseModel):
    """El informe que produce el último agente (``report_writer``).

    Lo importante: NUNCA contiene un diagnóstico definitivo ni una
    dosis. Es soporte a la decisión, no medicina automatizada — esa
    distinción es legal, no sólo ética. El ``disclaimer`` lo deja
    explícito en el propio modelo.
    """

    case_id: str                            # Para correlacionar con el caso
    suggested_priority: Priority            # Sugerencia, no orden — la decide el clínico
    risk_factors: list[str]                 # "Signos de alarma" hallados
    recommended_next_steps: list[str]       # Pruebas/acciones sugeridas
    retrieved_protocols: list[dict]         # Protocolos clínicos vía RAG (Elasticsearch)
    summary: str                            # Texto breve resumen del cuadro

    # Disclaimer obligatorio. Está como default precisamente para que
    # NO se nos olvide nunca. El clinical_safety_validator lo verifica.
    disclaimer: str = (
        "Este sistema es únicamente soporte a la decisión clínica. "
        "La decisión médica final corresponde al profesional sanitario."
    )


class TriageCase(BaseModel):
    """El "expediente" completo de un caso — lo que persiste en Mongo.

    Empieza con sólo ``intake`` y ``case_id`` y se va enriqueciendo:
      1. Al iniciar: `status="queued"`, trace vacío.
      2. Mientras corren los agentes: trace acumula AgentEvent y
         `status="running"`.
      3. Al terminar: `report` rellenado, `status="completed"`.
      4. Si el operador entrega el informe a Drive: `delivery` lleva
         la metadata (ruta, modo, file_id).
      5. En paralelo el hook de Jira pone `jira_key` apuntando al
         ticket que rastrea el caso desde dentro de Atlassian.
    """

    case_id: str
    intake: TriageIntake
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Status simple de máquina de estados. "error" no se usa para
    # cualquier fallo — sólo para errores irrecuperables del workflow.
    status: Literal["queued", "running", "completed", "error"] = "queued"

    # Lista de eventos en orden cronológico (audit log).
    agent_trace: list[AgentEvent] = Field(default_factory=list)

    # Optional porque al crear el caso aún no existe.
    report: Optional[TriageReport] = None

    # Optional porque la entrega es un paso separado disparado por el
    # operador desde la UI ("Enviar a Drive"). Si no se entrega, queda None.
    delivery: Optional[dict] = None

    # Clave Jira (p. ej. "KAN-42") que el hook ``on_start`` setea al
    # crear el ticket. Queda None si la integración Jira está apagada
    # o si la creación falló — el flujo nunca se rompe por Jira.
    jira_key: Optional[str] = None
