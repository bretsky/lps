import type { PlayerDetail } from "@/lib/types";
import { fmt, laneLabel } from "@/lib/format";

// Level 5 — splits by team/league/lane, per-game rates, region context, HN peer rank.

export function SplitsPanel({ player }: { player: PlayerDetail }) {
  const teams = player.splits.teams ?? [];
  const leagues = player.splits.leagues ?? [];
  const lanes = player.splits.lanes ?? [];

  return (
    <section className="deco-panel">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="deco-title">
          Splits & Context
        </h2>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <SplitList title="Teams" items={teams} />
        <SplitList title="Leagues" items={leagues} />
        <SplitList
          title="Lanes"
          items={lanes.map((l) => ({ ...l, name: laneLabel(l.name) }))}
        />
      </div>

      <div className="mt-5 grid gap-3 border-t border-border/60 pt-4 sm:grid-cols-2 lg:grid-cols-4">
        <Rate
          label="LPS / Game"
          value={fmt(player.rates.pts_per_game_w, 3)}
          hint="Weighted per-game LPS (phase & stakes adjusted)."
        />
        <Rate
          label="Clutch Gap"
          value={fmt(player.rates.clutch_gap, 3)}
          hint="Difference in per-game production in higher-stakes games."
          signed
          numeric={player.rates.clutch_gap}
        />
        <Rate
          label="Intangibles"
          value={fmt(player.rates.avg_resid, 3)}
          hint="Avg residual — unmodeled per-game value (avg_resid)."
          signed
          numeric={player.rates.avg_resid}
        />
        <Rate
          label="SoS"
          value={fmt(player.rates.sched_strength, 2)}
          hint="Schedule strength — avg opponent quality faced."
        />
        <Rate
          label="Region Elo"
          value={fmt(player.region_elo, 0)}
          hint="Current region strength (season-avg Elo of primary league)."
        />
        <Rate
          label="Avg Contribution"
          value={fmt(player.rates.avg_contrib, 3)}
          hint="Per-game contribution above baseline (win-prob added)."
          signed
          numeric={player.rates.avg_contrib}
        />
        <Rate
          label="HN Rank (lane)"
          value={
            player.high_noon.hn_lane != null
              ? `#${fmt(player.high_noon.hn_lane, 1)}`
              : "—"
          }
          hint={
            player.high_noon.hn_lane_yrs
              ? `Best-N seasons: ${player.high_noon.hn_lane_yrs}`
              : "High Noon peer rank across best seasons within lane."
          }
        />
        <Rate
          label="HN Rank (global)"
          value={
            player.high_noon.hn_global != null
              ? `#${fmt(player.high_noon.hn_global, 1)}`
              : "—"
          }
          hint={
            player.high_noon.hn_global_yrs
              ? `Best-N seasons: ${player.high_noon.hn_global_yrs}`
              : "High Noon peer rank across best seasons vs all lanes."
          }
        />
      </div>
    </section>
  );
}

function SplitList({
  title,
  items,
}: {
  title: string;
  items: { name: string; clr: number }[];
}) {
  if (items.length === 0) {
    return (
      <div>
        <div className="mb-1.5 text-[10px] uppercase tracking-widest text-text-dim">
          {title}
        </div>
        <div className="text-xs text-text-dim">—</div>
      </div>
    );
  }
  const max = Math.max(...items.map((i) => Math.abs(i.clr))) || 1;
  return (
    <div>
      <div className="mb-1.5 text-[10px] uppercase tracking-widest text-text-dim">
        {title}
      </div>
      <ul className="space-y-1">
        {items.map((it) => {
          const w = (Math.max(0, it.clr) / max) * 100;
          return (
            <li key={it.name} className="text-xs">
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate text-text-muted" title={it.name}>
                  {it.name}
                </span>
                <span className="font-mono text-text">{fmt(it.clr, 1)}</span>
              </div>
              <div className="mt-0.5 h-1.5 overflow-hidden rounded-sm bg-bg-rail">
                <div
                  className="h-full bg-accent-hex/60"
                  style={{ width: `${w}%` }}
                />
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Rate({
  label,
  value,
  hint,
  signed = false,
  numeric,
}: {
  label: string;
  value: string;
  hint: string;
  signed?: boolean;
  numeric?: number | null;
}) {
  const tone =
    signed && numeric != null
      ? numeric > 0
        ? "text-emerald-400"
        : numeric < 0
          ? "text-rose-400"
          : "text-text"
      : "text-text";
  return (
    <div
      className="rounded border border-border/70 bg-bg-rail px-3 py-2"
      title={hint}
    >
      <div className="text-[10px] uppercase tracking-widest text-text-dim">
        {label}
      </div>
      <div className={`mt-0.5 font-mono text-base font-semibold ${tone}`}>
        {value}
      </div>
    </div>
  );
}
