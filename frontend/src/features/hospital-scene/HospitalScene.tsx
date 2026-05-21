"use client";

import { useEffect, useRef } from "react";
import anime from "animejs";
import { useTriageStore } from "@/store/triageStore";
import { t } from "@/lib/i18n";
import type { AgentStatus } from "@/lib/types";
import { AGENTS, STATUS_COLOR } from "./agents";

const STATION_KEYS: Array<keyof typeof t.scene.stations> = [
  "orchestration", "analysis", "research", "systems", "safety", "report",
];

const STATIONS = [
  { x: 50, y: 14 },
  { x: 18, y: 38 },
  { x: 82, y: 38 },
  { x: 18, y: 68 },
  { x: 82, y: 68 },
  { x: 50, y: 92 },
];

const FLOW_EDGES: [number, number][] = [
  [0, 1], [0, 2], [1, 3], [2, 4], [3, 5], [4, 5],
];

export function HospitalScene() {
  const agents = useTriageStore((s) => s.agents);
  const running = useTriageStore((s) => s.running);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    Object.values(agents).forEach((a) => {
      const el = document.querySelector(`[data-agent-id="${a.id}"]`) as HTMLElement | null;
      if (!el) return;
      const isActive = isActiveStatus(a.status);
      anime.remove(el);
      if (isActive) {
        anime({
          targets: el,
          translateY: [-2, 2],
          direction: "alternate",
          loop: true,
          duration: 700,
          easing: "easeInOutSine",
        });
      } else if (a.status === "completed") {
        anime({ targets: el, scale: [1, 1.15, 1], duration: 700, easing: "easeOutBack" });
      } else if (a.status === "error" || a.status === "blocked") {
        anime({
          targets: el,
          translateX: [-3, 3],
          direction: "alternate",
          loop: 3,
          duration: 90,
          easing: "easeInOutQuad",
        });
      }
    });
  }, [agents]);

  return (
    <div className="relative flex-1 h-full overflow-hidden">
      <div className="absolute inset-0 grid-bg opacity-40" />
      <div className="absolute inset-0 bg-gradient-to-br from-transparent via-accent-violet/[0.04] to-accent-cyan/[0.06]" />

      <svg className="absolute inset-0 w-full h-full pointer-events-none">
        {FLOW_EDGES.map(([from, to], i) => {
          const f = STATIONS[from];
          const tgt = STATIONS[to];
          return (
            <line
              key={i}
              x1={`${f.x}%`}
              y1={`${f.y}%`}
              x2={`${tgt.x}%`}
              y2={`${tgt.y}%`}
              stroke="rgba(54, 208, 255, 0.16)"
              strokeWidth={1}
              strokeDasharray="4 6"
            />
          );
        })}
        {STATIONS.map((s, i) => (
          <g key={i}>
            <rect
              x={`calc(${s.x}% - 100px)`}
              y={`calc(${s.y}% - 38px)`}
              width={200}
              height={76}
              rx={10}
              fill="rgba(13, 20, 36, 0.55)"
              stroke="rgba(54, 208, 255, 0.18)"
              strokeWidth={1}
            />
            <text
              x={`${s.x}%`}
              y={`calc(${s.y}% - 16px)`}
              fill="rgba(124, 243, 255, 0.55)"
              fontSize={9}
              fontFamily="JetBrains Mono, ui-monospace, monospace"
              textAnchor="middle"
              letterSpacing={2}
            >
              {t.scene.stations[STATION_KEYS[i]]}
            </text>
          </g>
        ))}
      </svg>

      <div className="absolute top-3 left-1/2 -translate-x-1/2 z-10 px-4 py-1.5 rounded-full border border-white/10 bg-bg-panel/70 text-[11px] tracking-widest text-white/60 font-mono">
        {t.app.operationsCenter}
      </div>

      <div className={`absolute top-3 right-4 z-10 px-3 py-1 rounded-full text-[11px] font-mono ${running ? "bg-accent-emerald/20 text-accent-emerald" : "bg-white/5 text-white/40"}`}>
        {running ? t.app.live : t.app.standby}
      </div>

      <div ref={containerRef} className="absolute inset-0">
        {AGENTS.map((spec) => {
          const a = agents[spec.id];
          const status = a?.status ?? "idle";
          const colorOverride = STATUS_COLOR[status] || spec.color;
          return (
            <div
              key={spec.id}
              className="absolute -translate-x-1/2 -translate-y-1/2"
              style={{ left: `${spec.station.x}%`, top: `${spec.station.y}%` }}
            >
              <div data-agent-id={spec.id} className="relative flex flex-col items-center">
                <div
                  className="w-14 h-14 rounded-2xl flex items-center justify-center text-2xl border"
                  style={{
                    background: `radial-gradient(circle, ${colorOverride}22 0%, ${colorOverride}05 70%, transparent 100%)`,
                    borderColor: `${colorOverride}66`,
                    boxShadow: `0 0 24px ${colorOverride}55`,
                  }}
                >
                  <span>{spec.emoji}</span>
                </div>
                <div className="mt-1.5 text-[10px] font-mono uppercase tracking-widest text-white/80">
                  {t.agents[spec.id].label}
                </div>
                <div className="mt-0.5 text-[9px] font-mono uppercase tracking-wider" style={{ color: colorOverride }}>
                  {t.agentStatus[status]}
                </div>
                {a?.lastMessage && (
                  <div className="absolute top-full mt-7 w-48 text-[10px] text-white/55 text-center leading-snug">
                    {truncate(a.lastMessage, 90)}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="absolute bottom-3 left-3 z-10 flex gap-3 text-[10px] font-mono text-white/50">
        <LegendDot color="#22d3a4" label={t.scene.legend.completed} />
        <LegendDot color="#9b5dff" label={t.scene.legend.working} />
        <LegendDot color="#f7b94c" label={t.scene.legend.waiting} />
        <LegendDot color="#ff5757" label={t.scene.legend.error} />
        <LegendDot color="#3a4660" label={t.scene.legend.idle} />
      </div>
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="w-2 h-2 rounded-full" style={{ background: color, boxShadow: `0 0 8px ${color}` }} />
      {label}
    </span>
  );
}

function isActiveStatus(s: AgentStatus): boolean {
  return ["thinking", "analyzing", "searching", "executing", "validating", "writing", "walking", "discussing", "receiving_case"].includes(s);
}

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}
