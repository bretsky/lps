import type { PlayerDetail } from "@/lib/types";
import { fmt } from "@/lib/format";

// CLR composition: career_value + pace_value + peak_value + resume_bonus = clr.
// Each segment renders proportional to its absolute value; negative segments
// (rare — a poor résumé can drag CLR slightly) render as a hatched deduction.
const PARTS = [
  {
    key: "career_value" as const,
    label: "Career",
    color: "bg-accent-hex/70",
    text: "text-accent-hex",
    tip: "Career volume — total sample-shrunk production across seasons.",
  },
  {
    key: "pace_value" as const,
    label: "Pace",
    color: "bg-[#3fbfe8]/70",
    text: "text-[#3fbfe8]",
    tip: "Per-year rate — production adjusted for career length.",
  },
  {
    key: "peak_value" as const,
    label: "Peak",
    color: "bg-tier-greats/70",
    text: "text-tier-greats",
    tip: "Peak seasons — reward for how high the ceiling was.",
  },
  {
    key: "resume_bonus" as const,
    label: "Résumé",
    color: "bg-accent-gold/80",
    text: "text-accent-gold",
    tip: "Hardware — Worlds/MSI/domestic titles + MVP/All-Pro awards.",
  },
];

export function ClrWaterfall({ player }: { player: PlayerDetail }) {
  const c = player.clr_components;
  const values = PARTS.map((p) => ({ ...p, v: c[p.key] ?? 0 }));
  const positiveTotal = values.reduce((s, p) => s + Math.max(0, p.v), 0) || 1;

  return (
    <section className="deco-panel">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="deco-title">
          CLR Composition
        </h2>
        <div className="text-xs text-text-dim">
          Career + Pace + Peak + Résumé ={" "}
          <span className="font-mono text-text">{fmt(player.clr, 1)}</span>
        </div>
      </div>

      <div className="flex h-6 w-full overflow-hidden rounded bg-bg-rail">
        {values.map((p) => {
          const w = Math.max(0, (p.v / positiveTotal) * 100);
          if (w <= 0) return null;
          return (
            <div
              key={p.key}
              className={`${p.color} flex items-center justify-center text-[10px] font-semibold text-bg`}
              style={{ width: `${w}%` }}
              title={`${p.label}: ${p.v.toFixed(2)}`}
            >
              {w > 6 && p.v.toFixed(1)}
            </div>
          );
        })}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {values.map((p) => (
          <div
            key={p.key}
            className="rounded border border-border/70 bg-bg-rail px-3 py-2"
            title={p.tip}
          >
            <div className="flex items-center gap-2">
              <span className={`inline-block h-2 w-2 shrink-0 rounded-sm ${p.color}`} />
              <span className={`text-xs uppercase tracking-wider ${p.text}`}>
                {p.label}
              </span>
            </div>
            <div className="mt-0.5 text-[10px] text-text-dim">
              {((Math.max(0, p.v) / positiveTotal) * 100).toFixed(0)}% of CLR
            </div>
          </div>
        ))}
      </div>

      {(c.intl_bonus != null || c.title_bonus != null || c.award_bonus != null) && (
        <div className="mt-3 flex flex-wrap gap-4 border-t border-border/60 pt-3 text-xs text-text-muted">
          <span className="uppercase tracking-wider text-text-dim">Résumé split:</span>
          {c.intl_bonus != null && (
            <span>
              Intl <span className="font-mono text-text">{fmt(c.intl_bonus, 1)}</span>
            </span>
          )}
          {c.title_bonus != null && (
            <span>
              Titles <span className="font-mono text-text">{fmt(c.title_bonus, 1)}</span>
            </span>
          )}
          {c.award_bonus != null && (
            <span>
              Awards <span className="font-mono text-text">{fmt(c.award_bonus, 1)}</span>
            </span>
          )}
        </div>
      )}
    </section>
  );
}
