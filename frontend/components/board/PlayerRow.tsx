import Link from "next/link";
import type { IndexRow } from "@/lib/types";
import { fmt, fmtInt, fmtPct, laneLabel, displayName } from "@/lib/format";
import { TIER_COLORS } from "@/lib/theme";
import { LeagueMark, Portrait, TrophyPills } from "@/components/ui/Marks";
import { ClrBar } from "./ClrBar";
import { HolCrown, StatusDot } from "./StatusBadges";

// Shared with the board's column header so the two stay aligned.
export const ROW_GRID =
  "grid grid-cols-[2.5rem_3rem_minmax(0,1fr)_6.5rem] sm:grid-cols-[2.5rem_3rem_minmax(0,1fr)_minmax(0,9rem)_6.5rem] md:grid-cols-[2.75rem_3rem_minmax(0,1fr)_5.5rem_minmax(0,9.5rem)_8rem] lg:grid-cols-[2.75rem_3rem_minmax(0,1fr)_5.5rem_6.5rem_minmax(0,10rem)_9rem_5rem] items-center gap-3";

export function PlayerRow({ row, maxClr }: { row: IndexRow; maxClr: number }) {
  const isHol = row.hall_of_legends;
  const tierColor = TIER_COLORS[row.tier];
  const podium = row.rank <= 3;
  return (
    <Link
      href={`/player/${row.slug}`}
      className={`${ROW_GRID} group relative border-b border-border/60 px-4 py-2 transition-colors hover:bg-teal/[0.06]`}
    >
      {/* active-row marker, like a selected ladder row */}
      <span
        className="absolute inset-y-0 left-0 w-[3px] opacity-0 transition-opacity group-hover:opacity-100"
        style={{ background: tierColor, boxShadow: `0 0 10px ${tierColor}` }}
      />
      <div className="text-right">
        <span
          className={`font-display text-2xl font-black leading-none ${podium ? "text-metal" : "text-text-muted"}`}
        >
          {row.rank}
        </span>
      </div>
      <Portrait src={row.photo} name={displayName(row.playername)} size={44} ring={isHol ? "#f1d58f" : tierColor} />
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <StatusDot row={row} />
          <span
            className={`truncate text-[15px] font-bold tracking-wide group-hover:text-gold-bright ${
              isHol ? "text-gold-bright" : "text-text"
            }`}
          >
            {displayName(row.playername)}
          </span>
          {isHol && <HolCrown year={row.hol_year} />}
        </div>
        <div className="flex items-center gap-1.5 truncate text-xs text-text-dim">
          <LeagueMark league={row.current_league} size={13} />
          <span className="truncate">
            {row.current_team ?? "—"}
            {row.real_name ? <span className="hidden xl:inline"> · {row.real_name}</span> : null}
          </span>
        </div>
      </div>
      <div className="hidden text-[11px] font-semibold uppercase tracking-[0.14em] text-text-muted md:block">
        {row.positions && row.positions.length > 1
          ? row.positions.map((p) => laneLabel(p.lane)).join(" / ")
          : laneLabel(row.position)}
      </div>
      <div className="hidden text-xs text-text-muted lg:block">
        <div className="font-mono">
          {row.first_year === row.last_year ? row.first_year : `${row.first_year}–${String(row.last_year).slice(2)}`}
        </div>
        <div className="text-[10px] text-text-dim">
          {fmtInt(row.games)} G · {fmtPct(row.win_rate)}
        </div>
      </div>
      <div className="hidden sm:block">
        <TrophyPills titles={row.titles} compact />
      </div>
      <div className="text-right">
        <div className="flex items-baseline justify-end gap-1.5">
          <span className="font-display text-[26px] font-extrabold leading-none text-text">{fmt(row.clr, 1)}</span>
        </div>
        <div className="mt-1 hidden md:block">
          <ClrBar row={row} maxClr={maxClr} />
        </div>
      </div>
      <div className="hidden text-right text-xs text-text-muted lg:block">
        <div className="font-mono">{fmt(row.peak_lps, 1)}</div>
        <div className="text-[10px] text-text-dim">LPS {fmt(row.total_score, 0)}</div>
      </div>
    </Link>
  );
}
