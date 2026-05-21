"use client";

import { useTriageStore } from "@/store/triageStore";
import { useUiStore } from "@/store/uiStore";
import { Resizer } from "@/components/Resizer";
import { STATUS_COLOR } from "@/features/hospital-scene/agents";
import { t } from "@/lib/i18n";

export function TimelinePanel() {
  const events = useTriageStore((s) => s.events);
  const deliveryEvents = useTriageStore((s) => s.deliveryEvents);
  const timelineHeight = useUiStore((s) => s.timelineHeight);
  const setTimelineHeight = useUiStore((s) => s.setTimelineHeight);
  const presentationMode = useUiStore((s) => s.presentationMode);

  const all = [
    ...events.map((e) => ({
      kind: "agent" as const,
      ts: e.timestamp,
      who: t.agents[e.agent_id]?.label ?? e.agent_id,
      statusKey: e.status,
      statusLabel: t.agentStatus[e.status],
      color: STATUS_COLOR[e.status] ?? "#7cf3ff",
      message: e.message,
    })),
    ...deliveryEvents.map((d) => ({
      kind: "delivery" as const,
      ts: d.timestamp,
      who: "Google Drive",
      statusKey: d.step,
      statusLabel: t.drive.steps[d.step],
      color: d.step === "delivered" ? "#22d3a4" : d.step === "error" ? "#ff5757" : "#7cf3ff",
      message: d.message,
    })),
  ].sort((a, b) => (a.ts < b.ts ? -1 : 1));

  const rowTextSize = presentationMode ? "text-sm" : "text-xs";
  const labelSize = presentationMode ? "text-[12px]" : "text-[10px]";

  return (
    <section className="border-b border-white/5 bg-bg-panel/60 backdrop-blur-sm flex flex-col shrink-0" style={{ height: `${timelineHeight}px` }}>
      <header className="px-4 py-2.5 shrink-0">
        <div className="text-[10px] uppercase tracking-widest text-accent-cyan/70">
          {t.timeline.sectionTag}
        </div>
        <h2 className="text-sm font-semibold mt-0.5">{t.timeline.eventsLabel(all.length)}</h2>
      </header>
      <div className="flex-1 overflow-y-auto scrollbar-thin px-4 pb-3">
        {all.length === 0 ? (
          <div className="text-xs text-white/30 py-3">{t.timeline.awaiting}</div>
        ) : (
          <ol className="space-y-2">
            {all.map((e, i) => (
              <li key={i} className={`flex items-start gap-2 ${rowTextSize}`}>
                <span
                  className="mt-1.5 w-2 h-2 rounded-full shrink-0"
                  style={{ background: e.color, boxShadow: `0 0 8px ${e.color}` }}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
                    <span className="font-mono text-white/40 shrink-0">
                      {new Date(e.ts).toLocaleTimeString()}
                    </span>
                    <span className="font-mono text-white/85 shrink-0">{e.who}</span>
                    <span className={`font-mono uppercase ${labelSize}`} style={{ color: e.color }}>
                      {e.statusLabel}
                    </span>
                  </div>
                  <div className="text-white/65 leading-snug mt-0.5 break-words">{e.message}</div>
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>
      <Resizer axis="y" value={timelineHeight} onChange={setTimelineHeight} title="Arrastra para ajustar línea temporal" />
    </section>
  );
}
