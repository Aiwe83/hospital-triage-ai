export type AgentId =
  | "triage_orchestrator"
  | "clinical_analyst"
  | "protocol_researcher"
  | "hospital_systems_executor"
  | "clinical_safety_validator"
  | "report_writer";

export type AgentStatus =
  | "idle" | "receiving_case" | "thinking" | "walking" | "analyzing"
  | "searching" | "executing" | "validating" | "writing" | "discussing"
  | "completed" | "blocked" | "error";

export interface AgentEvent {
  agent_id: AgentId;
  status: AgentStatus;
  message: string;
  timestamp: string;
  data?: Record<string, unknown>;
}

export interface VitalSigns {
  heart_rate?: number | null;
  blood_pressure_systolic?: number | null;
  blood_pressure_diastolic?: number | null;
  respiratory_rate?: number | null;
  oxygen_saturation?: number | null;
  temperature_celsius?: number | null;
  pain_score?: number | null;
}

export interface TriageIntake {
  symptoms: string;
  age: number;
  sex?: "male" | "female" | "other" | "unknown";
  medical_history?: string;
  medications?: string;
  allergies?: string;
  vital_signs: VitalSigns;
  arrival_mode?: "walk_in" | "ambulance" | "transfer";
}

export type Priority = "critical" | "urgent" | "standard" | "non_urgent";

export interface TriageReport {
  case_id: string;
  suggested_priority: Priority;
  risk_factors: string[];
  recommended_next_steps: string[];
  retrieved_protocols: { id?: string; title?: string; score?: number }[];
  summary: string;
  disclaimer: string;
}

export interface DeliveryInfo {
  mode: string;
  status: string;
  destination?: Record<string, unknown> | null;
  artifact?: { type: string; path?: string; size_bytes?: number };
  timestamp?: string;
  note?: string;
}

export type DeliveryStepId =
  | "queued"
  | "validating_report"
  | "generating_pdf"
  | "connecting_drive"
  | "uploading"
  | "verifying"
  | "delivered"
  | "error";

export interface DeliveryProgressEvent {
  case_id: string;
  step: DeliveryStepId;
  progress: number;
  message: string;
  timestamp: string;
  data?: Record<string, unknown>;
}

export interface DeliveryResult {
  case_id: string;
  status: "delivered" | "error";
  mode: string;
  drive_file_id?: string | null;
  drive_view_url?: string | null;
  folder?: string | null;
  size_bytes?: number;
  path?: string;
  finished_at: string;
  note?: string;
}

export interface TriageCase {
  case_id: string;
  intake: TriageIntake;
  status: "queued" | "running" | "completed" | "error";
  agent_trace: AgentEvent[];
  report: TriageReport | null;
  delivery?: DeliveryInfo | null;
  jira_key?: string | null;
}
