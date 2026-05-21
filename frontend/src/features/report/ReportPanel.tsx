"use client";

import { useState } from "react";
import { useTriageStore } from "@/store/triageStore";
import { reportPdfUrl, closeJiraCase } from "@/lib/api";
import { t } from "@/lib/i18n";
import { DriveUploadCard } from "./DriveUploadCard";
import type { Priority } from "@/lib/types";

const PRIORITY_COLOR: Record<string, string> = {
  critical: "#ff5757",
  urgent: "#f7b94c",
  standard: "#36d0ff",
  non_urgent: "#22d3a4",
};

export function ReportPanel() {
  const { caseId, report, running, jiraKey, jiraClosed, setJiraClosed } = useTriageStore();
  const [closing, setClosing] = useState(false);
  const [closeError, setCloseError] = useState<string | null>(null);

  const onCloseJira = async () => {
    if (!caseId) return;
    setClosing(true);
    setCloseError(null);
    try {
      await closeJiraCase(caseId);
      setJiraClosed(true);
    } catch (e) {
      setCloseError(e instanceof Error ? e.message : String(e));
    } finally {
      setClosing(false);
    }
  };

  return (
    <section className="flex-1 overflow-y-auto scrollbar-thin bg-bg-panel/40 px-4 py-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <div className="text-[10px] uppercase tracking-widest text-accent-violet/70">
            {t.report.sectionTag}
          </div>
          <h2 className="text-sm font-semibold mt-0.5">{t.report.title}</h2>
        </div>
        {report && caseId && (
          <a
            href={reportPdfUrl(caseId)}
            target="_blank"
            rel="noreferrer"
            className="text-[11px] px-2.5 py-1 rounded border border-accent-cyan/50 text-accent-cyan hover:bg-accent-cyan/10"
          >
            {t.report.openPdf}
          </a>
        )}
      </div>

      {!report ? (
        <div className="text-xs text-white/30 py-4">
          {running ? t.report.waiting : t.report.placeholder}
        </div>
      ) : (
        <div className="space-y-3">
          <PriorityBadge priority={report.suggested_priority} />

          <Block title={t.report.summary}>
            <p className="text-sm leading-relaxed text-white/85">{report.summary}</p>
          </Block>

          <Block title={t.report.riskFactors}>
            <ul className="text-sm text-white/75 space-y-1 leading-relaxed">
              {report.risk_factors.length === 0 ? <li className="text-white/30">—</li> :
                report.risk_factors.map((r, i) => <li key={i}>• {r}</li>)}
            </ul>
          </Block>

          <Block title={t.report.nextSteps}>
            <ul className="text-sm text-white/75 space-y-1 leading-relaxed">
              {report.recommended_next_steps.map((r, i) => <li key={i}>• {r}</li>)}
            </ul>
          </Block>

          <Block title={t.report.protocols}>
            <ul className="text-sm text-white/75 space-y-1 leading-relaxed">
              {report.retrieved_protocols.length === 0 ? <li className="text-white/30">—</li> :
                report.retrieved_protocols.map((p, i) => (
                  <li key={i}>
                    <span className="text-accent-emerald">●</span> {p.title}
                    {typeof p.score === "number" && (
                      <span className="text-white/30 ml-2">{t.report.score(p.score)}</span>
                    )}
                  </li>
                ))}
            </ul>
          </Block>

          <DriveUploadCard />

          {jiraKey && <JiraCard jiraKey={jiraKey} jiraClosed={jiraClosed} closing={closing} closeError={closeError} onClose={onCloseJira} />}

          <div className="text-[10px] text-white/40 italic pt-2 border-t border-white/5">
            {t.report.disclaimer}
          </div>
        </div>
      )}
    </section>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-widest text-accent-cyan/70 mb-1.5">{title}</div>
      {children}
    </div>
  );
}

function JiraCard({
  jiraKey,
  jiraClosed,
  closing,
  closeError,
  onClose,
}: {
  jiraKey: string;
  jiraClosed: boolean;
  closing: boolean;
  closeError: string | null;
  onClose: () => void;
}) {
  const baseUrl = (process.env.NEXT_PUBLIC_JIRA_URL || "https://pablodefranchi.atlassian.net").replace(/\/$/, "");
  const url = `${baseUrl}/browse/${jiraKey}`;
  return (
    <div className="border border-accent-violet/40 bg-accent-violet/5 rounded p-3 space-y-2">
      <div className="text-[10px] uppercase tracking-widest text-accent-violet/80">
        Ticket clínico · Jira
      </div>
      <div className="flex items-center justify-between gap-2">
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className="text-sm font-mono text-accent-violet hover:underline"
        >
          {jiraKey}
        </a>
        {jiraClosed ? (
          <span className="text-[11px] font-mono uppercase tracking-widest text-accent-emerald">
            ✓ caso cerrado
          </span>
        ) : (
          <button
            onClick={onClose}
            disabled={closing}
            className="text-[11px] font-mono uppercase tracking-widest px-2.5 py-1 rounded border border-accent-emerald/50 text-accent-emerald hover:bg-accent-emerald/10 disabled:opacity-40"
          >
            {closing ? "Cerrando…" : "Cerrar caso"}
          </button>
        )}
      </div>
      {closeError && (
        <div className="text-[11px] text-rose-300 break-words">{closeError}</div>
      )}
    </div>
  );
}

function PriorityBadge({ priority }: { priority: Priority }) {
  const color = PRIORITY_COLOR[priority] ?? "#7cf3ff";
  return (
    <div
      className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-mono uppercase tracking-widest"
      style={{ border: `1px solid ${color}66`, color, background: `${color}10` }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />
      {t.report.priority(t.priority[priority])}
    </div>
  );
}
