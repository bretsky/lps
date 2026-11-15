import type { PlayerDetail } from "@/lib/types";
import { fmt } from "@/lib/format";

// Level 3 — CareerLPS anatomy. Three orthogonal partitions of `total_score`:
//   phase      : reg / playoff / tourn  (WHEN)
//   components : base / contrib / wbonus (HOW the model built it)
//   sources    : kills / deaths / assists / damage / fb  (WHERE — sums to contrib)
// Plus a per-tournament bar (WLDs / MSI / EWC / …) drawn from `tournaments`.

const PHASE = [
  { key: "reg_pts", label: "Regular", color: "bg-slate-500/70" },
  { key: "playoff_pts", label: "Playoffs", color: "bg-indigo-500/70" },
  { key: "tourn_pts", label: "International", color: "bg-accent-hex/70" },
] as const;

const COMPONENTS = [
  {
    key: "base_pts",
    label: "Baseline",
    color: "bg-slate-500/70",
    hint: "Value earned by simply playing the position on a rated team.",
  },
  {
    key: "contrib_pts",
    label: "Contribution",
    color: "bg-emerald-500/70",
    hint: "Above-expected performance — the model's signal.",
  },
  {
    key: "wbonus_pts",
    label: "Win Bonus",
    color: "bg-sky-500/70",
    hint: "Reward for winning games the model did not predict (beta * (result - p_model)).",
  },
] as const;

const SOURCES = [
  { key: "kills_pts", label: "Kills", color: "bg-rose-500/70" },
  { key: "deaths_pts", label: "Deaths", color: "bg-amber-500/70" },
  { key: "assists_pts", label: "Assists", color: "bg-emerald-500/70" },
  { key: "damage_pts", label: "Damage", color: "bg-fuchsia-500/70" },
  { key: "fb_pts", label: "First Blood", color: "bg-accent-hex/70" },
] as const;

export function CareerLpsAnatomy({ player }: { player: PlayerDetail }) {
  const phaseVals = PHASE.map((p) => ({ ...p, v: player.phase[p.key] ?? 0 }));
  const compVals = COMPONENTS.map((c) => ({ ...c, v: player.components[c.key] ?? 0 }));
  const srcVals = SOURCES.map((s) => ({ ...s, v: player.sources[s.key] ?? 0 }));

  const tourneys = Object.entries(player.tournaments ?? {})
    .filter(([, v]) => Math.abs(v) > 0.001)
    .sort(([, a], [, b]) => b - a);

  const total = player.career_lps.total_score ?? null;

  return (
    <section className="deco-panel space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="deco-title">
          CareerLPS Anatomy
        </h2>
        <div className="text-xs text-text-dim">
          Total <span className="font-mono text-text">{fmt(total, 1)}</span>
          {player.career_lps.peak_year && (
            <>
              {" "}
              · Peak <span className="font-mono text-text">
                {fmt(player.career_lps.peak_lps, 1)}
              </span>{" "}
              ({player.career_lps.peak_year})
            </>
          )}
        </div>
      </div>

      <PartitionBar
        title="By phase"
        subtitle="Regular season / playoffs / international events"
        parts={phaseVals}
      />

      <PartitionBar
        title="By component"
        subtitle="Baseline / contribution / win bonus"
        parts={compVals.map((c) => ({ ...c, title: c.hint }))}
      />

      <PartitionBar
        title="By stat source"
        subtitle="Kills / Deaths / Assists / Damage / FB — sums to Contribution"
        parts={srcVals}
        signed
      />

      {tourneys.length > 0 && (
        <div>
          <div className="mb-1.5 text-[10px] uppercase tracking-widest text-text-dim">
            By tournament
          </div>
          <ul className="space-y-1">
            {tourneys.map(([name, v]) => (
              <TournamentRow
                key={name}
                name={name}
                value={v}
                max={tourneys[0][1]}
              />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

type Part = {
  key: string;
  label: string;
  color: string;
  v: number;
  title?: string;
};

function PartitionBar({
  title,
  subtitle,
  parts,
  signed = false,
}: {
  title: string;
  subtitle: string;
  parts: Part[];
  signed?: boolean;
}) {
  const denom = parts.reduce((s, p) => s + Math.max(0, p.v), 0) || 1;
  const shownParts = signed ? parts : parts.filter((p) => p.v > 0);
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <div className="text-[10px] uppercase tracking-widest text-text-dim">
          {title}
        </div>
        <div className="text-[10px] text-text-dim">{subtitle}</div>
      </div>
      <div className="flex h-5 w-full overflow-hidden rounded bg-bg-rail">
        {shownParts.map((p) => {
          const w = Math.max(0, (p.v / denom) * 100);
          if (w <= 0.5) return null;
          return (
            <div
              key={p.key}
              className={`${p.color} flex items-center justify-center text-[10px] font-semibold text-bg`}
              style={{ width: `${w}%` }}
              title={`${p.title ?? p.label}: ${p.v.toFixed(2)}`}
            >
              {w > 8 && p.v.toFixed(1)}
            </div>
          );
        })}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-muted">
        {parts.map((p) => {
          const pct = ((Math.max(0, p.v) / denom) * 100).toFixed(0);
          return (
            <span key={p.key} className="inline-flex items-center gap-1.5">
              <span className={`inline-block h-2 w-2 rounded-sm ${p.color}`} />
              {p.label}{" "}
              <span className="font-mono text-text-dim">{pct}%</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

function TournamentRow({
  name,
  value,
  max,
}: {
  name: string;
  value: number;
  max: number;
}) {
  const w = Math.max(0, (value / max) * 100);
  return (
    <li className="grid grid-cols-[5rem_1fr_4rem] items-center gap-3 text-xs">
      <span className="truncate text-text-muted">{name}</span>
      <div className="h-2 overflow-hidden rounded-sm bg-bg-rail">
        <div className="h-full bg-accent-hex/60" style={{ width: `${w}%` }} />
      </div>
      <span className="text-right font-mono text-text">{fmt(value, 1)}</span>
    </li>
  );
}
