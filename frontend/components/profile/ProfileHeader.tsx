import type { PlayerDetail } from "@/lib/types";
import { fmt, fmtInt, fmtPct, laneLabel, yearsLabel } from "@/lib/format";
import { TierBadge } from "@/components/board/TierBadge";
import { HolCrown, StatusDot } from "@/components/board/StatusBadges";

export function ProfileHeader({
  player,
  laneRank,
}: {
  player: PlayerDetail;
  laneRank: number | null;
}) {
  const isHol = player.hall_of_legends;
  const lanes =
    player.positions && player.positions.length > 1
      ? player.positions.map((p) => laneLabel(p.lane)).join(" / ")
      : laneLabel(player.position);

  return (
    <header
      className={`rounded-lg border border-border bg-bg-card p-5 ${
        isHol ? "ring-1 ring-accent-gold/40" : ""
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-6">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <StatusDot row={player} />
            <h1
              className={`truncate text-3xl font-bold tracking-tight ${
                isHol ? "text-accent-gold" : "text-text"
              }`}
            >
              {player.playername}
            </h1>
            {isHol && <HolCrown year={player.hol_year} />}
            {player.tier && <TierBadge tier={player.tier} size="md" />}
          </div>
          <div className="mt-1 text-sm text-text-muted">
            {player.current_team ?? "—"} · {player.current_league ?? "—"} ·{" "}
            <span className="uppercase tracking-wide">{lanes}</span>
          </div>
          <div className="mt-0.5 text-xs text-text-dim">
            {yearsLabel(player.first_year, player.last_year, player.n_years)} ·{" "}
            {fmtInt(player.games)} games · {fmtPct(player.win_rate)} win rate
          </div>
        </div>

        <div className="flex items-end gap-6">
          <Stat label="Global Rank" value={`#${player.rank}`} />
          {laneRank && player.position && (
            <Stat
              label={`${laneLabel(player.position)} Rank`}
              value={`#${laneRank}`}
            />
          )}
          <div className="text-right">
            <div className="font-mono text-4xl font-bold leading-none text-text">
              {fmt(player.clr, 1)}
            </div>
            <div className="mt-1 text-[10px] uppercase tracking-widest text-text-dim">
              Career Legend Rating
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-right">
      <div className="font-mono text-xl font-semibold text-text-muted">{value}</div>
      <div className="mt-1 text-[10px] uppercase tracking-widest text-text-dim">
        {label}
      </div>
    </div>
  );
}
