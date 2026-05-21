import type { AgentId, AgentStatus } from "@/lib/types";

export interface AgentSpec {
  id: AgentId;
  label: string;
  role: string;
  color: string;       // color de glow principal
  station: { x: number; y: number };  // coords en % dentro de la escena
  emoji: string;        // pictograma simple (sustituido por sprites después)
}

export const AGENTS: AgentSpec[] = [
  {
    id: "triage_orchestrator",
    label: "Orchestrator",
    role: "Coordinates triage flow",
    color: "#36d0ff",
    station: { x: 50, y: 18 },
    emoji: "🎯",
  },
  {
    id: "clinical_analyst",
    label: "Clinical Analyst",
    role: "Risk signal extraction",
    color: "#9b5dff",
    station: { x: 22, y: 42 },
    emoji: "🩺",
  },
  {
    id: "protocol_researcher",
    label: "Protocol Researcher",
    role: "Elasticsearch RAG",
    color: "#22d3a4",
    station: { x: 78, y: 42 },
    emoji: "📚",
  },
  {
    id: "hospital_systems_executor",
    label: "Hospital Systems",
    role: "MCP tool execution",
    color: "#f7b94c",
    station: { x: 22, y: 72 },
    emoji: "🏥",
  },
  {
    id: "clinical_safety_validator",
    label: "Safety Validator",
    role: "Priority + disclaimer",
    color: "#ff6e7f",
    station: { x: 78, y: 72 },
    emoji: "🛡️",
  },
  {
    id: "report_writer",
    label: "Report Writer",
    role: "Final report synthesis",
    color: "#7cf3ff",
    station: { x: 50, y: 88 },
    emoji: "✍️",
  },
];

export const STATUS_COLOR: Record<AgentStatus, string> = {
  idle: "#3a4660",
  receiving_case: "#36d0ff",
  thinking: "#9b5dff",
  walking: "#7cf3ff",
  analyzing: "#9b5dff",
  searching: "#22d3a4",
  executing: "#f7b94c",
  validating: "#ff6e7f",
  writing: "#7cf3ff",
  discussing: "#36d0ff",
  completed: "#22d3a4",
  blocked: "#f7b94c",
  error: "#ff5757",
};

export const STATUS_LABEL: Record<AgentStatus, string> = {
  idle: "idle",
  receiving_case: "receiving case",
  thinking: "thinking",
  walking: "walking",
  analyzing: "analyzing",
  searching: "searching",
  executing: "executing",
  validating: "validating",
  writing: "writing",
  discussing: "discussing",
  completed: "completed",
  blocked: "blocked",
  error: "error",
};
