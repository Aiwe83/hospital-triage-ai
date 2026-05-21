"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { renderMarkdown } from "@/lib/md";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type DocKey = "readme" | "claude";

const DOCS: { key: DocKey; label: string; subtitle: string }[] = [
  { key: "readme", label: "README", subtitle: "Guía completa del proyecto" },
  { key: "claude", label: "CLAUDE", subtitle: "Reglas para asistentes de IA" },
];

const FETCH_TIMEOUT_MS = 8000;

export default function DocsPage() {
  const [active, setActive] = useState<DocKey>("readme");
  const [content, setContent] = useState<string>("");
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (key: DocKey) => {
    setStatus("loading");
    setError(null);
    setContent("");
    const ctrl = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
    try {
      const res = await fetch(`${API}/handbook/${key}`, { signal: ctrl.signal });
      clearTimeout(timeout);
      if (!res.ok) {
        const detail = await res.text().catch(() => "");
        throw new Error(`HTTP ${res.status} — ${detail || "respuesta sin cuerpo"}`);
      }
      const text = await res.text();
      setContent(text);
      setStatus("ready");
    } catch (e: unknown) {
      clearTimeout(timeout);
      const msg = e instanceof Error ? e.message : String(e);
      setError(msg);
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    void load(active);
  }, [active, load]);

  return (
    <main className="min-h-screen w-full bg-bg-base text-white/90 flex flex-col">
      <header className="sticky top-0 z-10 backdrop-blur bg-bg-base/85 border-b border-white/5 px-6 py-3 flex items-center gap-4">
        <Link
          href="/"
          className="text-[11px] font-mono uppercase tracking-widest px-3 py-1 rounded-full border border-white/10 text-white/55 hover:text-accent-cyan hover:border-accent-cyan/60 transition"
        >
          ← volver al triage
        </Link>
        <div className="ml-2">
          <div className="text-[10px] uppercase tracking-widest text-accent-cyan/70">Documentación del proyecto</div>
          <h1 className="text-sm font-semibold">Manual hospital-triage-ai</h1>
        </div>
        <nav className="ml-auto flex gap-2">
          {DOCS.map((d) => (
            <button
              key={d.key}
              onClick={() => setActive(d.key)}
              className={`text-[11px] font-mono uppercase tracking-widest px-3 py-1 rounded-full border transition ${
                active === d.key
                  ? "border-accent-cyan/60 bg-accent-cyan/10 text-accent-cyan"
                  : "border-white/10 bg-bg-panel/60 text-white/55 hover:text-white"
              }`}
              title={d.subtitle}
            >
              {d.label}
            </button>
          ))}
        </nav>
      </header>

      <section className="flex-1 overflow-y-auto scrollbar-thin px-6 py-6">
        <article className="max-w-4xl mx-auto md-doc">
          {status === "loading" && (
            <div className="text-white/55 text-sm">Cargando {active.toUpperCase()}…</div>
          )}
          {status === "error" && (
            <div className="border border-red-500/40 bg-red-500/5 rounded p-4">
              <div className="text-red-300 text-sm font-semibold mb-1">No se pudo cargar {active.toUpperCase()}.md</div>
              <div className="text-xs text-white/60 mb-3 break-words">{error}</div>
              <button
                onClick={() => load(active)}
                className="text-[11px] font-mono uppercase tracking-widest px-3 py-1 rounded-full border border-white/15 hover:border-accent-cyan/60 hover:text-accent-cyan"
              >
                Reintentar
              </button>
              <p className="text-[10px] text-white/40 mt-3">
                Si persiste: confirma que <code className="md-code">../README.md</code> y <code className="md-code">../CLAUDE.md</code> están montados en el contenedor backend (ver <code className="md-code">infra/docker-compose.yml</code>) y que <code className="md-code">{API}/handbook/{active}</code> responde 200.
              </p>
            </div>
          )}
          {status === "ready" && (
            <div
              className="md-content"
              dangerouslySetInnerHTML={{ __html: renderMarkdown(content) }}
            />
          )}
        </article>
      </section>
    </main>
  );
}
