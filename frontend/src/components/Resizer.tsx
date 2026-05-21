"use client";

import { useCallback, useEffect, useRef } from "react";

type Axis = "x" | "y";

export function Resizer({
  axis,
  value,
  onChange,
  invert = false,
  className = "",
  title,
}: {
  axis: Axis;
  value: number;
  onChange: (px: number) => void;
  invert?: boolean;
  className?: string;
  title?: string;
}) {
  const startRef = useRef<{ pos: number; size: number } | null>(null);

  const onPointerMove = useCallback(
    (e: PointerEvent) => {
      const s = startRef.current;
      if (!s) return;
      const cur = axis === "x" ? e.clientX : e.clientY;
      const delta = cur - s.pos;
      const next = s.size + (invert ? -delta : delta);
      onChange(next);
    },
    [axis, invert, onChange],
  );

  const onPointerUp = useCallback(() => {
    startRef.current = null;
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  }, [onPointerMove]);

  const onPointerDown = (e: React.PointerEvent) => {
    e.preventDefault();
    startRef.current = {
      pos: axis === "x" ? e.clientX : e.clientY,
      size: value,
    };
    document.body.style.cursor = axis === "x" ? "col-resize" : "row-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  };

  useEffect(() => () => onPointerUp(), [onPointerUp]);

  const base =
    axis === "x"
      ? "w-1.5 h-full cursor-col-resize hover:bg-accent-cyan/40"
      : "h-1.5 w-full cursor-row-resize hover:bg-accent-cyan/40";
  return (
    <div
      role="separator"
      aria-orientation={axis === "x" ? "vertical" : "horizontal"}
      onPointerDown={onPointerDown}
      title={title ?? "Arrastra para redimensionar"}
      className={`shrink-0 bg-white/5 active:bg-accent-cyan/60 transition-colors ${base} ${className}`}
    />
  );
}
