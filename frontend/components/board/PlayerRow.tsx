"use client";

import Link from "next/link";
import type { IndexRow } from "@/lib/types";
import { fmt, fmtInt, fmtPct, laneLabel, displayName, localRealName } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n";
import { TIER_COLORS } from "@/lib/theme";
import { LeagueMark, Portrait, TrophyPills } from "@/components/ui/Marks";
import { ClrBar } from "./ClrBar";
import { HolCrown, StatusDot } from "./StatusBadges";

// Shared with the board's column header so the two stay aligned.
export const ROW_GRID =
  "grid grid-cols-[2.5rem_3rem_minmax(0,1fr)_6.5rem] sm:grid-cols-[2.5rem_3rem_minmax(0,1fr)_minmax(0,9rem)_6.5rem] md:grid-cols-[2.75rem_3rem_minmax(0,1fr)_5.5rem_minmax(0,9.5rem)_8rem] lg:grid-cols-[2.75rem_3rem_minmax(0,1fr)_5.5rem_6.5rem_minmax(0,10rem)_9rem_5rem] items-center gap-3";

/** Rank movement since the previous season's board, under the rank number:
 *  ▲n up, ▼n down, – unchanged, NEW = not yet rated then. Nothing when there's no
 *  previous board to compare with (`prevYear` null, e.g. the first frozen year). */
function RankMove({ rank, prev, prevYear }: { rank: number; prev: number | null | undefined; prevYear: number | null }) {
  const m = useT();
  if (prevYear === null || prev === undefined) return null;
  const base = "block font-mono text-[10px] font-bold leading-none mt-1";
  if (prev === null)
    return (
      <span className={`${base} tracking-wider text-teal`} title={m.row.notRated(prevYear)}>
        {m.row.isNew}
      </span>
    );
  const d = prev - rank;
  if (d === 0)
    return (
      <span className={`${base} text-text-dim`} title={m.row.rankSame(prev, prevYear)}>
        –
      </span>
    );
  return (
    <span
      className={`${base} ${d > 0 ? "text-emerald-400" : "text-rose-400"}`}
      title={m.row.rankMove(d > 0, Math.abs(d), prev, prevYear)}
    >
      {d > 0 ? "▲" : "▼"}
      {Math.abs(d)}
    </span>
  );
}

/** CLR gained (or lost) since the previous season's board, beside the CLR value. Nothing
 *  without a previous board, or for a player who hadn't played yet (the rank says NEW). */
function ClrMove({ clr, prev, prevYear }: { clr: number; prev: number | null | undefined; prevYear: number | null }) {
  const m = useT();
  if (prevYear === null || prev === null || prev === undefined) return null;
  const d = Math.round((clr - prev) * 10) / 10;
  if (d === 0)
    return (
      <span className="font-mono text-[11px] font-bold text-text-dim" title={m.row.clrSame(fmt(prev, 1), prevYear)}>
        ±0
      </span>
    );
  return (
    <span
      className={`font-mono text-[11px] font-bold ${d > 0 ? "text-emerald-400" : "text-rose-400"}`}
      title={m.row.clrMove(fmt(prev, 1), prevYear, `${d > 0 ? "+" : "−"}${Math.abs(d).toFixed(1)}`)}
    >
      {d > 0 ? "+" : "−"}
      {Math.abs(d).toFixed(1)}
    </span>
  );
}

export function PlayerRow({ row, maxClr, prevYear = null }: { row: IndexRow; maxClr: number; prevYear?: number | null }) {
  const m = useT();
  const realName = localRealName(row, useLocale());
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
        <RankMove rank={row.rank} prev={row.rank_prev} prevYear={prevYear} />
      </div>
      <Portrait
        src={row.photo}
        focus={{ cx: row.photo_cx, ar: row.photo_ar, top: row.photo_top, neck: row.photo_neck }}
        name={displayName(row.playername)}
        size={44}
        ring={isHol ? "#f1d58f" : tierColor}
      />
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
            {realName ? <span className="hidden xl:inline"> · {realName}</span> : null}
          </span>
        </div>
      </div>
      <div className="hidden text-[11px] font-semibold uppercase tracking-[0.14em] text-text-muted md:block">
        {row.positions && row.positions.length > 1
          ? row.positions.map((p) => laneLabel(m, p.lane)).join(" / ")
          : laneLabel(m, row.position)}
      </div>
      <div className="hidden text-xs text-text-muted lg:block">
        <div className="font-mono">
          {row.first_year === row.last_year ? row.first_year : `${row.first_year}–${String(row.last_year).slice(2)}`}
        </div>
        <div className="text-[10px] text-text-dim">
          {m.row.gamesWin(fmtInt(row.games), fmtPct(row.win_rate))}
        </div>
      </div>
      <div className="hidden sm:block">
        <TrophyPills titles={row.titles} compact />
      </div>
      <div className="text-right">
        <div className="flex items-baseline justify-end gap-1.5">
          <ClrMove clr={row.clr} prev={row.clr_prev} prevYear={prevYear} />
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
