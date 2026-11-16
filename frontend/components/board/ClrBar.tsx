"use client";

import type { IndexRow } from "@/lib/types";
import { useT } from "@/lib/i18n";

// Thin neon stacked bar: Career / Pace / Peak / Résumé shares of CLR, scaled to
// the board's top CLR. Widths sum to <= 100% (negative résumé clamped to 0).
export const CLR_SEGMENTS = [
  { key: "career_value", part: "career", color: "#1fd1c1" },
  { key: "pace_value", part: "pace", color: "#3fbfe8" },
  { key: "peak_value", part: "peak", color: "#b28bff" },
  { key: "resume_bonus", part: "resume", color: "#e9c77a" },
] as const;

export function ClrBar({ row, maxClr }: { row: IndexRow; maxClr: number }) {
  const m = useT();
  const denom = maxClr || 1;
  return (
    <div className="flex h-[5px] w-full overflow-hidden bg-black/60" style={{ boxShadow: "inset 0 0 0 1px rgba(201,164,92,0.25)" }}>
      {CLR_SEGMENTS.map((p) => {
        const v = row[p.key] ?? 0;
        const w = Math.max(0, (v / denom) * 100);
        if (w <= 0) return null;
        return (
          <div
            key={p.key}
            style={{ width: `${w}%`, background: p.color, boxShadow: `0 0 6px ${p.color}aa` }}
            title={`${m.parts[p.part]}: ${v.toFixed(1)}`}
          />
        );
      })}
    </div>
  );
}
