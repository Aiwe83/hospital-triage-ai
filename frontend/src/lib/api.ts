import type {
  AgentEvent, DeliveryInfo, DeliveryProgressEvent, DeliveryResult,
  TriageCase, TriageIntake,
} from "./types";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function createTriage(intake: TriageIntake): Promise<{ case_id: string; stream_url: string }> {
  const res = await fetch(`${API}/triage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(intake),
  });
  if (!res.ok) throw new Error(`createTriage failed: ${res.status}`);
  return res.json();
}

export async function fetchCase(caseId: string): Promise<TriageCase> {
  const res = await fetch(`${API}/triage/${caseId}`);
  if (!res.ok) throw new Error(`fetchCase failed: ${res.status}`);
  return res.json();
}

export async function exportReport(caseId: string): Promise<DeliveryInfo> {
  const res = await fetch(`${API}/triage/${caseId}/export`, { method: "POST" });
  if (!res.ok) throw new Error(`exportReport failed: ${res.status}`);
  return res.json();
}

export async function triggerDelivery(caseId: string): Promise<{ status: string }> {
  const res = await fetch(`${API}/triage/${caseId}/deliver`, { method: "POST" });
  if (!res.ok) throw new Error(`triggerDelivery failed: ${res.status}`);
  return res.json();
}

export function openDeliveryStream(
  caseId: string,
  onEvent: (e: DeliveryProgressEvent) => void,
  onDone: (result: DeliveryResult) => void,
  onError?: (msg: string) => void,
): () => void {
  const es = new EventSource(`${API}/triage/${caseId}/deliver/events`);
  es.addEventListener("delivery_event", (msg) => {
    try {
      const parsed: DeliveryProgressEvent = JSON.parse((msg as MessageEvent).data);
      onEvent(parsed);
    } catch (err) {
      console.error("delivery_event parse failed", err);
    }
  });
  es.addEventListener("delivery_done", (msg) => {
    try {
      const result: DeliveryResult = JSON.parse((msg as MessageEvent).data);
      onDone(result);
    } catch (err) {
      console.error("delivery_done parse failed", err);
    }
    es.close();
  });
  es.addEventListener("delivery_error", (msg) => {
    try {
      const data = JSON.parse((msg as MessageEvent).data);
      onError?.(data.message ?? "delivery error");
    } catch {
      onError?.("delivery error");
    }
    es.close();
  });
  es.onerror = () => {
    onError?.("connection error");
  };
  return () => es.close();
}

export function reportPdfUrl(caseId: string): string {
  return `${API}/triage/${caseId}/report.pdf`;
}

export async function closeJiraCase(caseId: string): Promise<{ jira_key: string }> {
  const res = await fetch(`${API}/triage/${caseId}/jira/close`, { method: "POST" });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`closeJiraCase failed: ${res.status} ${detail}`);
  }
  return res.json();
}

export async function getJiraStatus(): Promise<{ enabled: boolean; project: string | null }> {
  const res = await fetch(`${API}/jira/status`);
  if (!res.ok) throw new Error(`getJiraStatus failed: ${res.status}`);
  return res.json();
}

export function openEventStream(
  caseId: string,
  onEvent: (e: AgentEvent) => void,
  onDone: () => void,
  onError?: (err: Event) => void,
): () => void {
  const es = new EventSource(`${API}/triage/${caseId}/events`);
  es.addEventListener("agent_event", (msg) => {
    try {
      const parsed: AgentEvent = JSON.parse((msg as MessageEvent).data);
      onEvent(parsed);
    } catch (err) {
      console.error("Failed to parse agent_event", err);
    }
  });
  es.addEventListener("done", () => {
    onDone();
    es.close();
  });
  es.onerror = (err) => {
    if (onError) onError(err);
    // EventSource reconecta solo; cerramos manualmente solo en errores terminales que maneja `done`.
  };
  return () => es.close();
}
