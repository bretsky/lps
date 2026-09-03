import type { IndexRow } from "@/lib/types";

// Small stacked bar: Career / Pace / Peak / Résumé shares of CLR.
// Widths sum to <= 100% (negative résumé rare but clamp to 0).
export function ClrBar({ row, maxClr }: { row: IndexRow; maxClr: number }) {
  const denom = maxClr || 1;
  const parts = [
    { key: "career", v: row.career_value ?? 0, color: "bg-accent-hex/70" },
    { key: "pace", v: row.pace_value ?? 0, color: "bg-emerald-500/70" },
    { key: "peak", v: row.peak_value ?? 0, color: "bg-fuchsia-500/70" },
    { key: "resume", v: row.resume_bonus ?? 0, color: "bg-accent-gold/80" },
  ];
  return (
    <div className="flex h-2 w-full overflow-hidden rounded-sm bg-bg-rail">
      {parts.map((p) => {
        const w = Math.max(0, (p.v / denom) * 100);
        if (w <= 0) return null;
        return (
          <div
            key={p.key}
            className={p.color}
            style={{ width: `${w}%` }}
            title={`${p.key}: ${p.v.toFixed(1)}`}
          />
        );
      })}
    </div>
  );
}
