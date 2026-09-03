import type { IndexRow } from "@/lib/types";
import { fmt, fmtInt, fmtPct, laneLabel, yearsLabel } from "@/lib/format";
import { ClrBar } from "./ClrBar";
import { HolCrown, StatusDot } from "./StatusBadges";

export function PlayerRow({ row, maxClr }: { row: IndexRow; maxClr: number }) {
  const isHol = row.hall_of_legends;
  return (
    <div
      className={`grid grid-cols-[3rem_minmax(0,1fr)_5rem_5rem_6rem_5rem_1fr_5rem] items-center gap-3 border-b border-border/60 px-4 py-2 text-sm hover:bg-bg-card/60 ${
        isHol ? "bg-accent-gold/[0.06]" : ""
      }`}
    >
      <div className="flex items-center justify-end gap-1 font-mono text-text-muted">
        {isHol && <HolCrown year={row.hol_year} />}
        <span>{row.rank}</span>
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <StatusDot row={row} />
          <span className={`truncate font-semibold ${isHol ? "text-accent-gold" : ""}`}>
            {row.playername}
          </span>
        </div>
        <div className="truncate text-xs text-text-dim">
          {row.current_team ?? "—"} · {row.current_league ?? "—"}
        </div>
      </div>
      <div className="text-xs uppercase tracking-wide text-text-muted">
        {row.positions && row.positions.length > 1
          ? row.positions.map((p) => laneLabel(p.lane)).join(" / ")
          : laneLabel(row.position)}
      </div>
      <div className="text-xs text-text-muted">{yearsLabel(row.first_year, row.last_year, row.n_years)}</div>
      <div className="text-right">
        <div className="font-mono text-base font-bold text-text">{fmt(row.clr, 1)}</div>
        <div className="text-[10px] uppercase tracking-wide text-text-dim">CLR</div>
      </div>
      <div className="text-right text-xs text-text-muted">
        <div>{fmtInt(row.games)} G</div>
        <div className="text-text-dim">{fmtPct(row.win_rate)}</div>
      </div>
      <div className="pr-2">
        <ClrBar row={row} maxClr={maxClr} />
        <div className="mt-1 flex justify-between text-[10px] uppercase tracking-wider text-text-dim">
          <span>Career {fmt(row.career_value, 1)}</span>
          <span>Pace {fmt(row.pace_value, 1)}</span>
          <span>Peak {fmt(row.peak_value, 1)}</span>
          <span>Résumé {fmt(row.resume_bonus, 1)}</span>
        </div>
      </div>
      <div className="text-right text-xs text-text-muted">
        <div>Peak {fmt(row.peak_lps, 1)}</div>
        <div className="text-text-dim">CareerLPS {fmt(row.total_score, 0)}</div>
      </div>
    </div>
  );
}
