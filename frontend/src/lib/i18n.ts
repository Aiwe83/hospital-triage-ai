/**
 * i18n ligero. Hoy solo se envía un locale (`es`); la forma permite
 * añadir más locales sin tocar los call sites — basta con reemplazar el
 * export por una función que elija locale desde cookies / headers.
 */

import type { AgentId, AgentStatus, Priority } from "./types";

type Dict = {
  app: {
    title: string;
    subtitle: string;
    operationsCenter: string;
    live: string;
    standby: string;
  };
  intake: {
    sectionTag: string;
    title: string;
    safetyHint: string;
    presetsLabel: string;
    presets: { respiratory: string; chestPain: string; pediatric: string };
    fields: {
      symptoms: string;
      symptomsPh: string;
      age: string;
      sex: string;
      arrival: string;
      history: string;
      medications: string;
      allergies: string;
      vitalsSection: string;
      hr: string; rr: string; sbp: string; dbp: string; spo2: string; temp: string; pain: string;
    };
    sex: { unknown: string; male: string; female: string; other: string };
    arrival: { walk_in: string; ambulance: string; transfer: string };
    buttons: {
      start: string;
      starting: string;
      running: string;
      sendDrive: string;
      sending: string;
      resendDrive: string;
    };
    caseLabel: string;
  };
  scene: {
    legend: { completed: string; working: string; waiting: string; error: string; idle: string };
    stations: {
      orchestration: string;
      analysis: string;
      research: string;
      systems: string;
      safety: string;
      report: string;
    };
  };
  agents: Record<AgentId, { label: string; role: string }>;
  agentStatus: Record<AgentStatus, string>;
  timeline: {
    sectionTag: string;
    eventsLabel: (n: number) => string;
    awaiting: string;
  };
  report: {
    sectionTag: string;
    title: string;
    openPdf: string;
    summary: string;
    riskFactors: string;
    nextSteps: string;
    protocols: string;
    delivery: string;
    priority: (p: string) => string;
    placeholder: string;
    waiting: string;
    score: (n: number) => string;
    disclaimer: string;
  };
  priority: Record<Priority, string>;
  drive: {
    cardTitle: string;
    cardHint: string;
    triggerButton: string;
    retryButton: string;
    statesLabel: string;
    steps: {
      queued: string;
      validating_report: string;
      generating_pdf: string;
      connecting_drive: string;
      uploading: string;
      verifying: string;
      delivered: string;
      error: string;
    };
    deliveredAt: string;
    openInDrive: string;
    fileSize: (n: number) => string;
    targetFolder: string;
    mockBadge: string;
    realBadge: string;
    progress: (pct: number) => string;
  };
};

const es: Dict = {
  app: {
    title: "Hospital Triage IA",
    subtitle: "Soporte a la decisión clínica multiagente",
    operationsCenter: "TRIAGE HOSPITALARIO IA · CENTRO DE OPERACIONES",
    live: "● EN VIVO",
    standby: "○ EN ESPERA",
  },
  intake: {
    sectionTag: "Recepción de paciente",
    title: "Caso clínico",
    safetyHint: "Soporte a la decisión clínica. No sustituye al criterio médico.",
    presetsLabel: "Casos de ejemplo",
    presets: {
      respiratory: "Disnea aguda (62 años, EPOC)",
      chestPain: "Dolor torácico (54 años, fumador)",
      pediatric: "Fiebre pediátrica (3 años)",
    },
    fields: {
      symptoms: "Síntomas",
      symptomsPh: "Describa el motivo de consulta…",
      age: "Edad",
      sex: "Sexo",
      arrival: "Llegada",
      history: "Antecedentes",
      medications: "Medicación",
      allergies: "Alergias",
      vitalsSection: "Constantes vitales",
      hr: "FC",
      rr: "FR",
      sbp: "PAS",
      dbp: "PAD",
      spo2: "SpO₂",
      temp: "Temp",
      pain: "Dolor",
    },
    sex: { unknown: "desconocido", male: "hombre", female: "mujer", other: "otro" },
    arrival: { walk_in: "por sus medios", ambulance: "ambulancia", transfer: "traslado" },
    buttons: {
      start: "Iniciar flujo de triage",
      starting: "Enviando…",
      running: "Ejecutando triage…",
      sendDrive: "Enviar informe al consultorio (Google Drive)",
      sending: "Enviando a Drive…",
      resendDrive: "Reenviar a Google Drive",
    },
    caseLabel: "caso",
  },
  scene: {
    legend: { completed: "completado", working: "trabajando", waiting: "esperando", error: "error", idle: "en reposo" },
    stations: {
      orchestration: "CENTRO DE ORQUESTACIÓN",
      analysis: "ANÁLISIS CLÍNICO",
      research: "INVESTIGACIÓN DE PROTOCOLOS",
      systems: "SISTEMAS HOSPITALARIOS",
      safety: "VALIDACIÓN DE SEGURIDAD",
      report: "SÍNTESIS DE INFORME",
    },
  },
  agents: {
    triage_orchestrator:        { label: "Orquestador", role: "Coordina el flujo de triage" },
    clinical_analyst:           { label: "Analista clínico", role: "Extracción de señales de riesgo" },
    protocol_researcher:        { label: "Investigador de protocolos", role: "RAG sobre Elasticsearch" },
    hospital_systems_executor:  { label: "Sistemas hospitalarios", role: "Ejecución de herramientas MCP" },
    clinical_safety_validator:  { label: "Validador de seguridad", role: "Prioridad y aviso clínico" },
    report_writer:              { label: "Redactor de informe", role: "Síntesis del informe final" },
  },
  agentStatus: {
    idle: "en reposo",
    receiving_case: "recibiendo caso",
    thinking: "razonando",
    walking: "en tránsito",
    analyzing: "analizando",
    searching: "buscando",
    executing: "ejecutando",
    validating: "validando",
    writing: "redactando",
    discussing: "deliberando",
    completed: "completado",
    blocked: "esperando",
    error: "error",
  },
  timeline: {
    sectionTag: "Línea temporal de agentes",
    eventsLabel: (n) => `${n} evento${n === 1 ? "" : "s"}`,
    awaiting: "Esperando eventos del flujo de triage…",
  },
  report: {
    sectionTag: "Informe de soporte al triage",
    title: "Resultado de la decisión asistida",
    openPdf: "Abrir PDF",
    summary: "Resumen",
    riskFactors: "Factores de riesgo",
    nextSteps: "Próximos pasos sugeridos",
    protocols: "Protocolos recuperados",
    delivery: "Envío",
    priority: (p) => `Prioridad: ${p}`,
    placeholder: "Envíe un caso para generar un informe.",
    waiting: "Los agentes siguen trabajando…",
    score: (n) => `puntuación ${n.toFixed(2)}`,
    disclaimer:
      "Este sistema es únicamente soporte a la decisión clínica. La decisión médica final corresponde al profesional sanitario.",
  },
  priority: {
    critical: "crítica",
    urgent: "urgente",
    standard: "estándar",
    non_urgent: "no urgente",
  },
  drive: {
    cardTitle: "Envío al consultorio · Google Drive",
    cardHint: "El informe se sincroniza con la carpeta clínica del facultativo.",
    triggerButton: "Enviar informe a Google Drive",
    retryButton: "Reintentar envío",
    statesLabel: "Estado de la sincronización",
    steps: {
      queued: "En cola",
      validating_report: "Validando informe",
      generating_pdf: "Generando PDF",
      connecting_drive: "Conectando con Google Drive",
      uploading: "Subiendo archivo",
      verifying: "Verificando integridad",
      delivered: "Entregado",
      error: "Error en el envío",
    },
    deliveredAt: "Entregado",
    openInDrive: "Abrir en Drive",
    fileSize: (n) => `${(n / 1024).toFixed(1)} KB`,
    targetFolder: "Carpeta destino",
    mockBadge: "Simulación segura",
    realBadge: "Integración real",
    progress: (pct) => `${pct}%`,
  },
};

export const dict = es;
export const t = es;
