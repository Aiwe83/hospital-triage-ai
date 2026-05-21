"use client";

import { useEffect } from "react";
import anime from "animejs";
import { triggerDelivery, openDeliveryStream, fetchCase } from "@/lib/api";
import { useTriageStore } from "@/store/triageStore";
import { t } from "@/lib/i18n";
import type { DeliveryStepId } from "@/lib/types";

const STEP_ORDER: DeliveryStepId[] = [
  "queued",
  "validating_report",
  "generating_pdf",
  "connecting_drive",
  "uploading",
  "verifying",
  "delivered",
];

export function DriveUploadCard() {
  const { caseId, report, deliveryState, deliveryEvents, startDelivery, pushDeliveryEvent, finishDelivery, failDelivery, setDelivery } =
    useTriageStore();

  // Pulsar la barra de progreso mientras se ejecuta
  useEffect(() => {
    if (deliveryState.status !== "running") return;
    const el = document.querySelector('[data-drive-bar]') as HTMLElement | null;
    if (el) {
      anime.remove(el);
      anime({ targets: el, opacity: [0.5, 1], duration: 700, direction: "alternate", loop: true });
    }
  }, [deliveryState.status]);

  if (!caseId || !report) return null;

  const start = async () => {
    if (deliveryState.status === "running") return;
    startDelivery();
    try {
      await triggerDelivery(caseId);
    } catch (err) {
      failDelivery((err as Error).message);
      return;
    }
    openDeliveryStream(
      caseId,
      (ev) => pushDeliveryEvent(ev),
      async (result) => {
        finishDelivery(result);
        // Refrescar el caso para captar la info final de entrega
        try {
          const c = await fetchCase(caseId);
          if (c.delivery) setDelivery(c.delivery);
        } catch {}
      },
      (msg) => failDelivery(msg),
    );
  };

  const activeIdx = deliveryState.step ? STEP_ORDER.indexOf(deliveryState.step) : -1;
  const isDone = deliveryState.status === "delivered";
  const isError = deliveryState.status === "error";
  const isRunning = deliveryState.status === "running";

  return (
    <div className="rounded-lg border border-accent-violet/30 bg-accent-violet/[0.04] p-3 space-y-3">
      <header className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[10px] uppercase tracking-widest text-accent-violet/80">
            {t.drive.cardTitle}
          </div>
          <p className="text-[11px] text-white/55 mt-1">{t.drive.cardHint}</p>
        </div>
        <span className="text-[9px] font-mono px-1.5 py-0.5 rounded border border-white/15 text-white/55">
          {deliveryState.result?.mode === "real" ? t.drive.realBadge : t.drive.mockBadge}
        </span>
      </header>

      {deliveryState.status === "idle" && (
        <button
          onClick={start}
          className="w-full rounded bg-accent-violet/80 hover:bg-accent-violet text-white font-semibold py-2 text-xs transition flex items-center justify-center gap-2"
        >
          <DriveIcon /> {t.drive.triggerButton}
        </button>
      )}

      {(isRunning || isDone || isError) && (
        <>
          <div className="text-[10px] uppercase tracking-widest text-white/40">
            {t.drive.statesLabel}
          </div>

          <ol className="space-y-1.5">
            {STEP_ORDER.filter((s) => s !== "delivered" || isDone).map((step, i) => {
              const idx = STEP_ORDER.indexOf(step);
              const past = idx < activeIdx || isDone;
              const current = idx === activeIdx && isRunning;
              const future = idx > activeIdx && !isDone;
              const errorHere = isError && idx === activeIdx;
              return (
                <li key={step} className="flex items-center gap-2 text-[11px]">
                  <StepDot state={errorHere ? "error" : past ? "done" : current ? "current" : "future"} />
                  <span
                    className={
                      errorHere
                        ? "text-accent-rose"
                        : past || isDone
                          ? "text-white/80"
                          : current
                            ? "text-accent-cyan"
                            : "text-white/30"
                    }
                  >
                    {t.drive.steps[step]}
                  </span>
                  {current && <span className="text-[9px] font-mono text-white/40 ml-auto">{deliveryState.progress}%</span>}
                </li>
              );
            })}
          </ol>

          {!isDone && (
            <div className="w-full h-1.5 rounded-full bg-white/5 overflow-hidden">
              <div
                data-drive-bar
                className={`h-full transition-all duration-300 ${isError ? "bg-accent-rose" : "bg-accent-violet"}`}
                style={{ width: `${deliveryState.progress}%` }}
              />
            </div>
          )}

          {isError && (
            <div className="text-[11px] text-accent-rose bg-accent-rose/10 border border-accent-rose/30 rounded p-2">
              {deliveryState.message || t.drive.steps.error}
              <button onClick={start} className="mt-2 block text-[10px] underline">
                {t.drive.retryButton}
              </button>
            </div>
          )}

          {isDone && deliveryState.result && (
            <div className="rounded border border-accent-emerald/40 bg-accent-emerald/10 p-2 space-y-1.5">
              <div className="text-[11px] text-accent-emerald font-semibold flex items-center gap-1.5">
                <CheckIcon /> {t.drive.deliveredAt}
              </div>
              <div className="text-[10px] font-mono text-white/70 space-y-0.5">
                {deliveryState.result.folder && (
                  <div>
                    {t.drive.targetFolder}: <span className="text-white">{deliveryState.result.folder}</span>
                  </div>
                )}
                {deliveryState.result.drive_file_id && (
                  <div>file_id: <span className="text-white/85">{deliveryState.result.drive_file_id}</span></div>
                )}
                {typeof deliveryState.result.size_bytes === "number" && (
                  <div>{t.drive.fileSize(deliveryState.result.size_bytes)}</div>
                )}
              </div>
              {deliveryState.result.drive_view_url && (
                <a
                  href={deliveryState.result.drive_view_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-block text-[11px] underline text-accent-emerald"
                >
                  {t.drive.openInDrive} ↗
                </a>
              )}
            </div>
          )}
        </>
      )}

      {deliveryEvents.length > 0 && (
        <div className="text-[9px] font-mono text-white/30">
          {deliveryEvents.length} eventos · último: {new Date(deliveryEvents[deliveryEvents.length - 1].timestamp).toLocaleTimeString()}
        </div>
      )}
    </div>
  );
}

function StepDot({ state }: { state: "done" | "current" | "future" | "error" }) {
  const styles: Record<string, string> = {
    done: "bg-accent-emerald shadow-[0_0_8px_#22d3a4]",
    current: "bg-accent-cyan shadow-[0_0_10px_#36d0ff] animate-pulse",
    future: "bg-white/10",
    error: "bg-accent-rose shadow-[0_0_8px_#ff5757]",
  };
  return <span className={`w-2 h-2 rounded-full shrink-0 ${styles[state]}`} />;
}

function DriveIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
      <path d="M12 18v-6m0 0l-3 3m3-3l3 3" />
      <path d="M3 15a4 4 0 014-4 5 5 0 0110 0 4 4 0 010 8H7a4 4 0 01-4-4z" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}>
      <path d="M5 13l4 4L19 7" />
    </svg>
  );
}
