"use client";

import { useEffect } from "react";
import { IntakePanel } from "@/features/intake/IntakePanel";
import { HospitalScene } from "@/features/hospital-scene/HospitalScene";
import { TimelinePanel } from "@/features/timeline/TimelinePanel";
import { ReportPanel } from "@/features/report/ReportPanel";
import { Resizer } from "@/components/Resizer";
import { useUiStore } from "@/store/uiStore";

export default function Home() {
  const presentationMode = useUiStore((s) => s.presentationMode);
  const intakeWidth = useUiStore((s) => s.intakeWidth);
  const sidebarWidth = useUiStore((s) => s.sidebarWidth);
  const setIntakeWidth = useUiStore((s) => s.setIntakeWidth);
  const setSidebarWidth = useUiStore((s) => s.setSidebarWidth);
  const togglePresentation = useUiStore((s) => s.togglePresentationMode);

  useEffect(() => {
    const root = document.documentElement;
    if (presentationMode) {
      root.classList.add("ti-presentation");
      // Pedir pantalla completa al navegador para que el proyector /
      // Teams share solo vea la app, con el chrome de Windows oculto.
      // requestFullscreen devuelve una promesa que se rechaza si falta
      // el gesto de usuario (p. ej. rehidratación SSR); la tragamos
      // para que el boost de tipografía se siga aplicando.
      if (!document.fullscreenElement && root.requestFullscreen) {
        root.requestFullscreen().catch((err) => {
          console.warn("requestFullscreen rejected", err);
        });
      }
    } else {
      root.classList.remove("ti-presentation");
      if (document.fullscreenElement && document.exitFullscreen) {
        document.exitFullscreen().catch(() => {
          /* nothing to do — already exited */
        });
      }
    }
    return () => root.classList.remove("ti-presentation");
  }, [presentationMode]);

  // Mantener el toggle sincronizado cuando el usuario sale de pantalla completa con F11 / ESC.
  useEffect(() => {
    const onChange = () => {
      const fs = Boolean(document.fullscreenElement);
      const cls = document.documentElement.classList.contains("ti-presentation");
      if (!fs && cls) {
        // El navegador dejó pantalla completa — también bajamos el modo
        // presentación para que la etiqueta del botón y la clase de
        // tamaño de fuente se mantengan coherentes.
        useUiStore.getState().togglePresentationMode();
      }
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  return (
    <main className="h-screen w-screen flex overflow-hidden relative">
      <div className="shrink-0 h-full" style={{ width: `${intakeWidth}px` }}>
        <IntakePanel />
      </div>
      <Resizer axis="x" value={intakeWidth} onChange={setIntakeWidth} title="Arrastra para ajustar recepción" />

      <div className="flex-1 flex flex-col relative min-w-0">
        <button
          onClick={togglePresentation}
          title="Modo presentación (texto grande para Teams)"
          className={`absolute top-3 left-3 z-30 px-3 py-1 rounded-full text-[11px] font-mono uppercase tracking-widest border transition ${
            presentationMode
              ? "border-accent-cyan/60 bg-accent-cyan/10 text-accent-cyan"
              : "border-white/10 bg-bg-panel/70 text-white/55 hover:text-white"
          }`}
        >
          {presentationMode ? "■ presentación" : "▢ presentación"}
        </button>
        <div className="flex-1 flex overflow-hidden">
          <HospitalScene />
        </div>
      </div>

      <Resizer axis="x" value={sidebarWidth} onChange={setSidebarWidth} invert title="Arrastra para ajustar informe" />
      <div className="shrink-0 h-full border-l border-white/5 bg-bg-panel/60 flex flex-col" style={{ width: `${sidebarWidth}px` }}>
        <TimelinePanel />
        <ReportPanel />
      </div>
    </main>
  );
}
