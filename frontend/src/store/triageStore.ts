import { create } from "zustand";
import type {
  AgentEvent, AgentId, AgentStatus,
  DeliveryInfo, DeliveryProgressEvent, DeliveryResult, DeliveryStepId,
  TriageReport,
} from "@/lib/types";

export const AGENT_IDS: AgentId[] = [
  "triage_orchestrator",
  "clinical_analyst",
  "protocol_researcher",
  "hospital_systems_executor",
  "clinical_safety_validator",
  "report_writer",
];

export type AgentState = {
  id: AgentId;
  status: AgentStatus;
  lastMessage: string;
  lastTs: string | null;
  visited: boolean;
};

export type DeliveryState = {
  status: "idle" | "running" | "delivered" | "error";
  step: DeliveryStepId | null;
  progress: number;
  message: string;
  result: DeliveryResult | null;
};

type State = {
  caseId: string | null;
  running: boolean;
  events: AgentEvent[];
  agents: Record<AgentId, AgentState>;
  report: TriageReport | null;
  delivery: DeliveryInfo | null;
  jiraKey: string | null;
  jiraClosed: boolean;

  deliveryState: DeliveryState;
  deliveryEvents: DeliveryProgressEvent[];

  setCaseId: (id: string | null) => void;
  reset: () => void;
  pushEvent: (e: AgentEvent) => void;
  finish: () => void;
  setReport: (r: TriageReport | null) => void;
  setDelivery: (d: DeliveryInfo | null) => void;
  setJiraKey: (key: string | null) => void;
  setJiraClosed: (closed: boolean) => void;

  startDelivery: () => void;
  pushDeliveryEvent: (e: DeliveryProgressEvent) => void;
  finishDelivery: (result: DeliveryResult) => void;
  failDelivery: (message: string) => void;
};

const initialAgents = (): Record<AgentId, AgentState> =>
  AGENT_IDS.reduce((acc, id) => {
    acc[id] = { id, status: "idle", lastMessage: "", lastTs: null, visited: false };
    return acc;
  }, {} as Record<AgentId, AgentState>);

const initialDelivery = (): DeliveryState => ({
  status: "idle",
  step: null,
  progress: 0,
  message: "",
  result: null,
});

export const useTriageStore = create<State>((set, get) => ({
  caseId: null,
  running: false,
  events: [],
  agents: initialAgents(),
  report: null,
  delivery: null,
  jiraKey: null,
  jiraClosed: false,
  deliveryState: initialDelivery(),
  deliveryEvents: [],

  setCaseId: (id) => set({ caseId: id, running: !!id }),

  reset: () =>
    set({
      caseId: null,
      running: false,
      events: [],
      agents: initialAgents(),
      report: null,
      delivery: null,
      jiraKey: null,
      jiraClosed: false,
      deliveryState: initialDelivery(),
      deliveryEvents: [],
    }),

  pushEvent: (e) => {
    const agents = { ...get().agents };
    const existing = agents[e.agent_id];
    if (existing) {
      agents[e.agent_id] = {
        ...existing,
        status: e.status,
        lastMessage: e.message,
        lastTs: e.timestamp,
        visited: true,
      };
    }
    set({ events: [...get().events, e], agents });
  },

  finish: () => {
    // Red de seguridad: cuando termina el stream SSE, promovemos
    // a "completed" cualquier agente que no haya alcanzado un estado
    // terminal (completed/error/blocked). Evita que las estaciones se
    // queden visualmente atascadas en executing/validating si un nodo
    // olvidó emitir su evento final.
    const TERMINAL: AgentStatus[] = ["completed", "error", "blocked", "idle"];
    const agents = { ...get().agents };
    for (const id of AGENT_IDS) {
      const a = agents[id];
      if (a && a.visited && !TERMINAL.includes(a.status)) {
        agents[id] = { ...a, status: "completed" };
      }
    }
    set({ running: false, agents });
  },

  setReport: (r) => set({ report: r }),
  setDelivery: (d) => set({ delivery: d }),
  setJiraKey: (key) => set({ jiraKey: key }),
  setJiraClosed: (closed) => set({ jiraClosed: closed }),

  startDelivery: () =>
    set({
      deliveryState: { status: "running", step: "queued", progress: 0, message: "", result: null },
      deliveryEvents: [],
    }),

  pushDeliveryEvent: (e) =>
    set({
      deliveryEvents: [...get().deliveryEvents, e],
      deliveryState: {
        ...get().deliveryState,
        status: "running",
        step: e.step,
        progress: e.progress,
        message: e.message,
      },
    }),

  finishDelivery: (result) =>
    set({
      deliveryState: {
        status: "delivered",
        step: "delivered",
        progress: 100,
        message: "",
        result,
      },
    }),

  failDelivery: (message) =>
    set({
      deliveryState: {
        ...get().deliveryState,
        status: "error",
        step: "error",
        message,
      },
    }),
}));
