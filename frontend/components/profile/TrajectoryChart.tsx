"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { CSSProperties, ReactNode } from "react";
import type {
  Medal,
  PlayerDetail,
  TournamentFamily,
  YearAchievements,
} from "@/lib/types";
import { fmt } from "@/lib/format";
import {
  CupIntl,
  CupDomestic,
  Laurel,
  Star,
  Shield,
} from "./AchievementIcons";
import { leagueIcon } from "@/lib/icons";

// Official event marks drawn as alpha masks so the medal tint (currentColor)
// still reads: gold / silver / bronze Worlds, MSI, First Stand and EWC logos.
function officialMark(src: string): IconComponent {
  function Mark({ className }: { className?: string }) {
    return (
      <span
        className={`mark-mask inline-block ${className ?? ""}`}
        style={{ "--mark": `url(${src})`, "--tint": "currentColor" } as CSSProperties}
      />
    );
  }
  return Mark;
}
const OfficialWorlds = officialMark("/icons/events/worlds.png");
const OfficialMsi = officialMark("/icons/events/msi.png");
const OfficialFirstStand = officialMark("/icons/events/first-stand.png");
const OfficialEwc = officialMark("/icons/events/ewc.png");

// Season-by-season LPS with High Noon peer ranks + notable achievements.
//
// Achievement badges: cup silhouette = tournament, tint = medal placement.
//   - Marks: official Worlds / MSI / First Stand / EWC logos, the league logo for domestic podiums,
//     cup silhouettes for other intl events and domestic cups
//   - Medals: gold (champion) / silver (finalist) / bronze (semifinalist)
//   - Awards: MVP (rose star), All-Pro (indigo shield) — no medal axis
//
// Layout is a three-row CSS grid (separate grid per row, same column template):
//   icons / bars+rank-line-overlay / year-labels
// HN ranks are shown as two line charts overlaid on the bars (gold=global, teal=lane).

type IconComponent = (p: { className?: string }) => ReactNode;

const CUP_ICON: Record<TournamentFamily, IconComponent> = {
  worlds: OfficialWorlds,
  msi: OfficialMsi,
  first_stand: OfficialFirstStand,
  ewc: OfficialEwc,
  intl: CupIntl,
  domestic: CupDomestic,
  cup: Laurel,
};

const CUP_LABEL: Record<TournamentFamily, string> = {
  worlds: "Worlds",
  msi: "MSI",
  first_stand: "First Stand",
  ewc: "Esports World Cup",
  intl: "Other international",
  domestic: "Domestic league",
  cup: "Domestic cup",
};

const MEDAL_TONE: Record<Medal, string> = {
  gold: "text-gold-bright",
  silver: "text-slate-300",
  bronze: "text-[#d18a55]",
};

const MEDAL_LABEL: Record<Medal, string> = {
  gold: "champion",
  silver: "finalist",
  bronze: "semifinalist",
};

const CUP_ORDER: TournamentFamily[] = ["worlds", "msi", "first_stand", "ewc", "intl", "domestic", "cup"];
const MEDAL_ORDER: Medal[] = ["gold", "silver", "bronze"];

const BAR_HEIGHT_PX = 128;

// Phase breakdown colour palette
const PHASE_COLORS = {
  reg:     "bg-cyan-600/70",
  playoff: "bg-violet-500/70",
  tourn:   "bg-amber-400/80",
} as const;

export function TrajectoryChart({ player }: { player: PlayerDetail }) {
  const breakdown = player.trajectory_breakdown ?? {};

  const entries = Object.entries(player.trajectory ?? {})
    .map(([y, v]) => [Number(y), v] as const)
    .sort((a, b) => a[0] - b[0]);

  if (entries.length === 0) return null;

  const values = entries.map(([, v]) => v);
  const posMax = Math.max(0.001, ...values);
  const negMin = Math.min(0, ...values);
  const span = posMax - negMin;
  const upperFrac = posMax / span;
  const lowerFrac = -negMin / span;

  const peakYear = player.career_lps.peak_year ?? null;
  const peakYears = pickPeakYears(
    player.career_lps.peak_years,
    peakYear,
    entries,
  );
  const ranks = player.hn_year_ranks ?? {};
  const achievements = player.year_achievements ?? {};
  const yearTeams = player.year_teams ?? {};
  // League each season's domestic podiums came from (for the league's own logo).
  const domLeague: Record<string, string> = {};
  for (const h of player.honors ?? []) {
    if (h.kind === "domestic" && h.league && !domLeague[h.year]) domLeague[h.year] = h.league;
  }

  const colTemplate = `minmax(4rem, auto) repeat(${entries.length}, minmax(4.5rem, 1fr))`;
  const gridStyle: CSSProperties = { gridTemplateColumns: colTemplate };

  return (
    <section className="deco-panel">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="deco-title">
          Season-by-Season
        </h2>
        <div className="text-xs text-text-dim">
          Peak {fmt(player.career_lps.peak_lps, 1)}
          {peakYear && <> ({peakYear})</>} · {entries.length} seasons
        </div>
      </div>

      <div className="overflow-x-auto">
        {/* Row 1: achievement icons */}
        <div className="grid gap-x-1.5" style={gridStyle}>
          <div />
          {entries.map(([year]) => (
            <AchievementCell
              key={`ach-${year}`}
              ach={achievements[String(year)] ?? {}}
              league={domLeague[String(year)]}
            />
          ))}
        </div>

        {/* Row 2: bars + rank line overlay (single spanning element) */}
        <div className="mt-1 grid gap-x-1.5" style={gridStyle}>
          <div />
          <BarAndRankOverlay
            entries={entries}
            ranks={ranks}
            yearTeams={yearTeams}
            peakYears={peakYears}
            breakdown={breakdown}
            posMax={posMax}
            negMin={negMin}
            upperFrac={upperFrac}
            lowerFrac={lowerFrac}
          />
        </div>

        {/* Row 3: year labels */}
        <div className="mt-1 grid gap-x-1.5" style={gridStyle}>
          <RowLabel>Year</RowLabel>
          {entries.map(([year]) => (
            <div
              key={`yr-${year}`}
              className="text-center text-[11px] font-semibold text-text-muted"
            >
              {year}
            </div>
          ))}
        </div>

        {/* Row 4: team logos / names */}
        <div className="mt-0.5 grid gap-x-1.5" style={gridStyle}>
          <RowLabel>Team</RowLabel>
          {entries.map(([year]) => {
            const teams = yearTeams[String(year)] ?? [];
            if (teams.length === 0) return <div key={`t-${year}`} />;
            const title = teams.map((t) => t.name).join(" / ");
            // Show up to 2 logos stacked; overflow indicated by "+N" badge
            const shown = teams.slice(0, 2);
            const extra = teams.length - shown.length;
            return (
              <div
                key={`t-${year}`}
                className="flex flex-col items-center gap-0.5"
                title={title}
              >
                {shown.map((t) =>
                  t.logo ? (
                    <img
                      key={t.name}
                      src={t.logo}
                      alt={t.name}
                      referrerPolicy="no-referrer"
                      className="h-4 w-4 object-contain"
                    />
                  ) : (
                    <span
                      key={t.name}
                      className="max-w-full truncate text-center text-[9px] text-text-dim"
                    >
                      {t.name}
                    </span>
                  ),
                )}
                {extra > 0 && (
                  <span className="text-[8px] text-text-dim">+{extra}</span>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <Legend />
    </section>
  );
}

// ─── Bar + rank line overlay ────────────────────────────────────────────────

type RankMap = Record<string, { global?: number | null; lane?: number | null }>;
type YearBreakdown = NonNullable<PlayerDetail["trajectory_breakdown"]>[string];

function BarAndRankOverlay({
  entries,
  ranks,
  yearTeams,
  peakYears,
  breakdown,
  posMax,
  negMin,
  upperFrac,
  lowerFrac,
}: {
  entries: readonly (readonly [number, number])[];
  ranks: RankMap;
  yearTeams: Record<string, { name: string; logo?: string }[]>;
  peakYears: Set<number>;
  breakdown: Record<string, YearBreakdown>;
  posMax: number;
  negMin: number;
  upperFrac: number;
  lowerFrac: number;
}) {
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  // Viewport anchor for the tooltip. It's portalled to <body> with fixed
  // positioning: the chart sits in an overflow-x scroller (which forces
  // overflow-y to auto) inside a clip-path panel, so an in-place tooltip
  // got clipped and spawned a vertical scrollbar.
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null);
  const plotRef = useRef<HTMLDivElement>(null);
  const n = entries.length;

  const hover = (i: number, el: HTMLElement) => {
    const col = el.getBoundingClientRect();
    const plot = plotRef.current?.getBoundingClientRect() ?? col;
    setHoveredIdx(i);
    setAnchor({ x: col.left + col.width / 2, y: plot.top + 4 });
  };

  // Fixed tooltip would drift from its bar on scroll — just dismiss it.
  useEffect(() => {
    if (hoveredIdx == null) return;
    const clear = () => setHoveredIdx(null);
    window.addEventListener("scroll", clear, true);
    window.addEventListener("resize", clear);
    return () => {
      window.removeEventListener("scroll", clear, true);
      window.removeEventListener("resize", clear);
    };
  }, [hoveredIdx]);

  const allRankVals = entries.flatMap(([y]) => {
    const r = ranks[String(y)];
    return [r?.global, r?.lane].filter((v): v is number => v != null);
  });
  const maxRank = allRankVals.length ? Math.max(...allRankVals) : 50;
  const RANK_PAD = BAR_HEIGHT_PX * 0.05;
  const RANK_SPAN = BAR_HEIGHT_PX * 0.9;
  const rankToYPx = (rank: number) =>
    RANK_PAD + ((rank - 1) / Math.max(1, maxRank - 1)) * RANK_SPAN;

  const colXPct = (i: number) => `${((i + 0.5) / n) * 100}%`;

  type Pt = { xPct: string; yPx: number; rank: number; year: number } | null;
  const globalPts: Pt[] = entries.map(([y], i) => {
    const r = ranks[String(y)]?.global;
    return r != null ? { xPct: colXPct(i), yPx: rankToYPx(r), rank: r, year: y } : null;
  });
  const lanePts: Pt[] = entries.map(([y], i) => {
    const r = ranks[String(y)]?.lane;
    return r != null ? { xPct: colXPct(i), yPx: rankToYPx(r), rank: r, year: y } : null;
  });

  const hasGlobal = globalPts.filter(Boolean).length > 1;
  const hasLane = lanePts.filter(Boolean).length > 1;

  const renderLines = (pts: Pt[], stroke: string) =>
    pts.flatMap((p, i) => {
      if (!p || i === 0) return [];
      const prev = pts[i - 1];
      if (!prev) return [];
      return (
        <line
          key={i}
          x1={prev.xPct} y1={prev.yPx}
          x2={p.xPct}    y2={p.yPx}
          stroke={stroke}
          strokeWidth="1.5"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      );
    });

  return (
    <div
      ref={plotRef}
      className="relative"
      style={{ height: `${BAR_HEIGHT_PX}px`, gridColumn: "2 / -1" }}
      onMouseLeave={() => setHoveredIdx(null)}
    >
      {/* Stacked bars */}
      <div className="absolute inset-0 flex gap-x-1.5">
        {entries.map(([year, v], i) => {
          const isPeak = peakYears.has(year);
          const bd = breakdown[String(year)];
          const reg = bd?.reg_pts ?? 0;
          const playoff = bd?.playoff_pts ?? 0;
          const tourn = bd?.tourn_pts ?? 0;
          const hasBreakdown = (reg + playoff + tourn) > 0.001;
          const barHeightPct = v > 0 ? (v / posMax) * 100 : 0;
          const negHeightPct = v < 0 ? (v / negMin) * 100 : 0;

          return (
            <div
              key={`bar-${year}`}
              className="flex flex-1 flex-col"
              onMouseEnter={(e) => hover(i, e.currentTarget)}
            >
              {/* Positive bar area */}
              <div
                className="flex flex-col justify-end"
                style={{ height: `${upperFrac * 100}%` }}
              >
                {v > 0 && (
                  hasBreakdown ? (
                    // Stacked: tourn on top, playoff middle, reg at bottom
                    <div
                      className={`w-full overflow-hidden rounded-t-sm ${isPeak ? "ring-2 ring-fuchsia-400 ring-inset" : ""}`}
                      style={{ height: `${barHeightPct}%` }}
                    >
                      <div className="flex h-full w-full flex-col-reverse">
                        {reg > 0 && (
                          <div
                            className={`${PHASE_COLORS.reg} w-full shrink-0`}
                            style={{ height: `${(reg / v) * 100}%` }}
                          />
                        )}
                        {playoff > 0 && (
                          <div
                            className={`${PHASE_COLORS.playoff} w-full shrink-0`}
                            style={{ height: `${(playoff / v) * 100}%` }}
                          />
                        )}
                        {tourn > 0 && (
                          <div
                            className={`${PHASE_COLORS.tourn} w-full shrink-0`}
                            style={{ height: `${(tourn / v) * 100}%` }}
                          />
                        )}
                      </div>
                    </div>
                  ) : (
                    // Fallback: solid bar
                    <div
                      className={`${isPeak ? "bg-fuchsia-400" : "bg-accent-hex/70"} w-full rounded-t-sm`}
                      style={{ height: `${barHeightPct}%` }}
                    />
                  )
                )}
              </div>
              {/* Negative bar area */}
              {lowerFrac > 0 && (
                <div
                  className="flex flex-col justify-start"
                  style={{ height: `${lowerFrac * 100}%` }}
                >
                  {v < 0 && (
                    <div
                      className="bg-rose-500/60 w-full rounded-b-sm"
                      style={{ height: `${negHeightPct}%` }}
                    />
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* SVG rank line overlay */}
      <svg
        className="absolute inset-0 overflow-visible"
        width="100%"
        height={BAR_HEIGHT_PX}
        style={{ pointerEvents: "none" }}
      >
        {hasGlobal && renderLines(globalPts, "rgba(241,213,143,0.9)")}
        {hasLane   && renderLines(lanePts,   "rgba(31,209,193,0.85)")}
        {globalPts.map(
          (p, i) =>
            p && (
              <circle
                key={`gd-${entries[i][0]}`}
                cx={p.xPct} cy={p.yPx}
                r={hoveredIdx === i ? 4 : 2.5}
                fill="rgb(241,213,143)"
                opacity={hoveredIdx === i ? 1 : 0.75}
              />
            ),
        )}
        {lanePts.map(
          (p, i) =>
            p && (
              <circle
                key={`ld-${entries[i][0]}`}
                cx={p.xPct} cy={p.yPx}
                r={hoveredIdx === i ? 4 : 2.5}
                fill="rgb(31,209,193)"
                opacity={hoveredIdx === i ? 1 : 0.75}
              />
            ),
        )}
      </svg>

      {/* Hover tooltip */}
      {hoveredIdx != null && anchor && createPortal((() => {
        const [year, v] = entries[hoveredIdx];
        const yr = ranks[String(year)];
        const teams = yearTeams[String(year)] ?? [];
        const bd = breakdown[String(year)];
        const isLeft = hoveredIdx / n < 0.2;
        const isRight = hoveredIdx / n > 0.78;
        const transform = isLeft
          ? "translateX(0%)"
          : isRight
            ? "translateX(-100%)"
            : "translateX(-50%)";
        return (
          <div
            className="pointer-events-none fixed z-50 rounded border border-border bg-bg-card/95 px-2 py-1.5 text-xs shadow-md"
            style={{ top: anchor.y, left: anchor.x, transform }}
          >
            <div className="font-mono font-semibold text-text">{year}</div>
            {teams.length > 0 && (
              <div className="text-text-dim">{teams.map((t) => t.name).join(" / ")}</div>
            )}
            <div className="font-semibold text-text-muted">{fmt(v, 2)} LPS</div>
            {bd && (
              <div className="mt-0.5 space-y-0.5">
                {(bd.reg_pts ?? 0) > 0 && (
                  <div style={{ color: "rgb(34,211,238)" }}>Regular {fmt(bd.reg_pts!, 2)}</div>
                )}
                {(bd.playoff_pts ?? 0) > 0 && (
                  <div style={{ color: "rgb(167,139,250)" }}>Playoffs {fmt(bd.playoff_pts!, 2)}</div>
                )}
                {(bd.tourn_pts ?? 0) > 0 && (
                  <div style={{ color: "rgb(251,191,36)" }}>Intl {fmt(bd.tourn_pts!, 2)}</div>
                )}
              </div>
            )}
            {yr?.global != null && (
              <div style={{ color: "rgb(241,213,143)" }}>Global #{yr.global}</div>
            )}
            {yr?.lane != null && (
              <div style={{ color: "rgb(31,209,193)" }}>Lane #{yr.lane}</div>
            )}
          </div>
        );
      })(), document.body)}
    </div>
  );
}

// ─── Supporting components ───────────────────────────────────────────────────

function RowLabel({ children }: { children: ReactNode }) {
  return (
    <div className="pr-2 text-right text-[10px] uppercase tracking-widest text-text-dim">
      {children}
    </div>
  );
}

function AchievementCell({ ach, league }: { ach: YearAchievements; league?: string }) {
  const lg = leagueIcon(league);
  const chips: ReactNode[] = [];

  for (const family of CUP_ORDER) {
    const medals = ach[family];
    if (!medals) continue;
    const Icon = CUP_ICON[family];
    for (const medal of MEDAL_ORDER) {
      const n = medals[medal] ?? 0;
      if (n <= 0) continue;
      if (family === "domestic" && lg) {
        chips.push(
          <span
            key={`${family}-${medal}`}
            title={`${league} ${MEDAL_LABEL[medal]}${n > 1 ? ` ×${n}` : ""}`}
            className={`inline-flex items-center gap-0.5 leading-none ${MEDAL_TONE[medal]}`}
          >
            <span
              className="inline-flex h-6 w-6 items-center justify-center rounded-full"
              style={{ boxShadow: "inset 0 0 0 1.5px currentColor" }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={lg.src} alt="" className="h-4 w-4 object-contain" style={{ filter: lg.invert ? "invert(1)" : undefined }} />
            </span>
            {n > 1 && <span className="text-[10px] font-bold tabular-nums">×{n}</span>}
          </span>,
        );
        continue;
      }
      chips.push(
        <IconChip
          key={`${family}-${medal}`}
          Icon={Icon}
          tone={MEDAL_TONE[medal]}
          title={`${CUP_LABEL[family]} ${MEDAL_LABEL[medal]}${n > 1 ? ` ×${n}` : ""}`}
          n={n}
        />,
      );
    }
  }
  if ((ach.mvp ?? 0) > 0) {
    chips.push(
      <IconChip
        key="mvp"
        Icon={Star}
        tone="text-rose-400"
        title={`MVP award${(ach.mvp ?? 0) > 1 ? ` ×${ach.mvp}` : ""}`}
        n={ach.mvp ?? 0}
      />,
    );
  }
  if ((ach.allpro ?? 0) > 0) {
    chips.push(
      <IconChip
        key="allpro"
        Icon={Shield}
        tone="text-indigo-300"
        title={`All-Pro selection${(ach.allpro ?? 0) > 1 ? ` ×${ach.allpro}` : ""}`}
        n={ach.allpro ?? 0}
      />,
    );
  }

  return (
    <div className="flex min-h-[1.5rem] flex-wrap items-start justify-center gap-1">
      {chips}
    </div>
  );
}

function IconChip({
  Icon,
  tone,
  title,
  n,
}: {
  Icon: IconComponent;
  tone: string;
  title: string;
  n: number;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-0.5 leading-none ${tone}`}
    >
      <Icon className="h-5 w-5" />
      {n > 1 && (
        <span className="text-[10px] font-bold tabular-nums">×{n}</span>
      )}
    </span>
  );
}

function Legend() {
  return (
    <div className="mt-4 space-y-2 border-t border-border/60 pt-3 text-[10px] text-text-muted">
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm bg-cyan-600/70" /> regular season
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm bg-violet-500/70" /> playoffs
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm bg-amber-400/80" /> international
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm ring-2 ring-fuchsia-400 ring-inset bg-transparent" /> peak yr
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm bg-rose-500/60" /> negative
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 rounded-sm" style={{ background: "rgb(241,213,143)" }} />
          HN global rank
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 rounded-sm" style={{ background: "rgb(31,209,193)" }} />
          HN lane rank
        </span>
        <span className="text-text-dim">(line top = rank #1)</span>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="uppercase tracking-widest text-text-dim">Cup = tournament:</span>
        {CUP_ORDER.map((f) => {
          const Icon = CUP_ICON[f];
          return (
            <span key={f} className="inline-flex items-center gap-1 text-accent-gold">
              <Icon className="h-4 w-4" />
              <span className="text-text-muted">{CUP_LABEL[f]}</span>
            </span>
          );
        })}
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="uppercase tracking-widest text-text-dim">Tint = placement:</span>
        {MEDAL_ORDER.map((m) => (
          <span key={m} className={`inline-flex items-center gap-1 ${MEDAL_TONE[m]}`}>
            <CupDomestic className="h-4 w-4" />
            <span className="text-text-muted">{MEDAL_LABEL[m]}</span>
          </span>
        ))}
        <span className="inline-flex items-center gap-1 text-rose-400">
          <Star className="h-4 w-4" />
          <span className="text-text-muted">MVP award</span>
        </span>
        <span className="inline-flex items-center gap-1 text-indigo-300">
          <Shield className="h-4 w-4" />
          <span className="text-text-muted">All-Pro selection</span>
        </span>
      </div>
    </div>
  );
}

function pickPeakYears(
  n: number | undefined,
  peakYear: number | null,
  entries: readonly (readonly [number, number])[],
): Set<number> {
  const out = new Set<number>();
  if (peakYear != null) out.add(peakYear);
  if (!n || n <= 1) return out;
  const ranked = [...entries].sort((a, b) => b[1] - a[1]).slice(0, n);
  for (const [y] of ranked) out.add(y);
  return out;
}
