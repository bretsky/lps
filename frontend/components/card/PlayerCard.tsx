"use client";

import { useState } from "react";
import type { PlayerDetail, TierKey } from "@/lib/types";
import { fmt, fmtInt, fmtPct, laneLabel, yearsLabel } from "@/lib/format";
import { TierBadge } from "@/components/board/TierBadge";
import { CardRadar } from "./CardRadar";
import {
  CupWorlds,
  CupMsi,
  CupIntl,
  CupDomestic,
  Star,
  Shield,
} from "@/components/profile/AchievementIcons";

// ---------------------------------------------------------------------------
// Tier styling
// ---------------------------------------------------------------------------

const TIER_ACCENT: Record<TierKey, string> = {
  goats: "#c8a95a",
  legends: "#d97757",
  greats: "#a685e2",
  elite: "#6aa7e6",
  stars: "#5fbf94",
  contenders: "#8a94a3",
};

function tierFrame(tier: TierKey | null) {
  const color = TIER_ACCENT[tier ?? "contenders"];
  const isGoats = tier === "goats";
  const isLegends = tier === "legends";
  const spreadPx = isGoats ? 28 : isLegends ? 18 : 10;
  const opacity = isGoats ? "55" : isLegends ? "44" : "28";
  return {
    border: `1.5px solid ${color}`,
    boxShadow: `0 0 ${spreadPx}px ${color}${opacity}`,
    accentColor: color,
  };
}

// ---------------------------------------------------------------------------
// Resume ribbon data
// ---------------------------------------------------------------------------

const MEDAL_COLORS = ["#c8a95a", "#8a94a3", "#a0703a"] as const; // gold/silver/bronze

const RB_ROWS = [
  {
    label: "Worlds",
    Icon: CupWorlds,
    keys: ["wlds_title", "wlds_final", "wlds_semi"] as const,
  },
  {
    label: "MSI",
    Icon: CupMsi,
    keys: ["msi_title", "msi_final", "msi_semi"] as const,
  },
  {
    label: "Intl",
    Icon: CupIntl,
    keys: ["othr_intl_champ", "othr_intl_final", "othr_intl_semi"] as const,
  },
  {
    label: "Dom",
    Icon: CupDomestic,
    keys: ["dom_champ", "dom_final", "dom_cup"] as const,
  },
] as const;

function rbN(rb: PlayerDetail["resume_breakdown"], key: string): number {
  return rb?.[key]?.n ?? 0;
}

// ---------------------------------------------------------------------------
// CLR bar segments
// ---------------------------------------------------------------------------

const CLR_PARTS = [
  { key: "career_value" as const, label: "Career", color: "#4bd8d8" },
  { key: "pace_value" as const, label: "Pace", color: "#10b981" },
  { key: "peak_value" as const, label: "Peak", color: "#d946ef" },
  { key: "resume_bonus" as const, label: "Résumé", color: "#c8a95a" },
];

// ---------------------------------------------------------------------------
// Monogram avatar
// ---------------------------------------------------------------------------

function Monogram({ name, color }: { name: string; color: string }) {
  const letter = name.trim()[0]?.toUpperCase() ?? "?";
  return (
    <div
      className="flex h-16 w-16 select-none items-center justify-center rounded-full border-2 text-2xl font-bold"
      style={{ borderColor: color, color, backgroundColor: `${color}18` }}
    >
      {letter}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function PlayerCard({ player }: { player: PlayerDetail }) {
  const [flipped, setFlipped] = useState(false);

  const tier = player.tier ?? "contenders";
  const { border, boxShadow, accentColor } = tierFrame(tier);

  // CLR bar
  const c = player.clr_components;
  const posTotal = CLR_PARTS.reduce((s, p) => s + Math.max(0, c[p.key] ?? 0), 0) || 1;

  // Résumé
  const rb = player.resume_breakdown;
  const activeRbRows = RB_ROWS.filter((row) => row.keys.some((k) => rbN(rb, k) > 0));
  const mvp = rbN(rb, "mvp");
  const allpro = rbN(rb, "allpro");
  const hasAwards = mvp > 0 || allpro > 0;

  // High Noon
  const hn = player.high_noon;

  const faceStyle: React.CSSProperties = {
    position: "absolute",
    inset: 0,
    backfaceVisibility: "hidden",
    WebkitBackfaceVisibility: "hidden" as never,
    border,
    boxShadow,
    borderRadius: 12,
    backgroundColor: "#111821",
    overflow: "hidden",
    display: "flex",
    flexDirection: "column",
  };

  return (
    <div
      style={{ width: 300, height: 420, perspective: "1000px" }}
      className="relative cursor-pointer select-none"
      onClick={() => setFlipped((f) => !f)}
      role="button"
      aria-label={flipped ? "Flip to card front" : "Flip to card back"}
    >
      {/* Rotating inner wrapper */}
      <div
        style={{
          width: "100%",
          height: "100%",
          position: "relative",
          transformStyle: "preserve-3d",
          transition: "transform 0.55s cubic-bezier(0.4, 0, 0.2, 1)",
          transform: flipped ? "rotateY(180deg)" : "rotateY(0deg)",
        }}
      >
        {/* ================================================================
            FRONT
        ================================================================ */}
        <div style={faceStyle}>
          {/* Tier accent stripe */}
          <div
            style={{
              height: 3,
              flexShrink: 0,
              background: `linear-gradient(90deg, ${accentColor}00, ${accentColor}, ${accentColor}00)`,
            }}
          />

          <div className="flex flex-1 flex-col px-4 pb-3 pt-2.5">
            {/* Rank + tier */}
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs font-semibold text-text-dim">
                #{player.rank}
              </span>
              <TierBadge tier={tier} size="sm" />
            </div>

            {/* Identity */}
            <div className="mt-2.5 flex flex-col items-center text-center">
              <Monogram name={player.playername} color={accentColor} />
              <h2 className="mt-2 text-xl font-bold leading-tight text-text">
                {player.playername}
              </h2>
              <p className="mt-0.5 text-[11px] text-text-muted">
                {player.current_team ?? "—"} · {player.current_league ?? "—"} ·{" "}
                {laneLabel(player.position)}
              </p>
              <p className="text-[10px] text-text-dim">
                {yearsLabel(player.first_year, player.last_year, player.n_years)}
              </p>
            </div>

            {/* CLR headline */}
            <div className="mt-3 text-center">
              <div className="font-mono text-4xl font-bold leading-none text-text">
                {fmt(player.clr, 1)}
              </div>
              <div className="mt-0.5 text-[8px] uppercase tracking-widest text-text-dim">
                Career Legend Rating
              </div>
            </div>

            {/* CLR mini bar */}
            <div className="mt-2.5">
              <div className="flex h-2.5 w-full overflow-hidden rounded-sm bg-bg-rail">
                {CLR_PARTS.map((p) => {
                  const v = c[p.key] ?? 0;
                  const w = Math.max(0, (v / posTotal) * 100);
                  if (w <= 0) return null;
                  return (
                    <div
                      key={p.key}
                      style={{ width: `${w}%`, backgroundColor: p.color }}
                    />
                  );
                })}
              </div>
              <div className="mt-1 flex justify-between">
                {CLR_PARTS.map((p) => (
                  <div key={p.key} className="text-center">
                    <div
                      className="text-[7.5px] uppercase tracking-wide"
                      style={{ color: p.color }}
                    >
                      {p.label}
                    </div>
                    <div className="font-mono text-[8.5px] text-text-dim">
                      {fmt(c[p.key] ?? 0, 1)}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Résumé ribbons */}
            {(activeRbRows.length > 0 || hasAwards) && (
              <div className="mt-2.5 space-y-1 border-t border-border/60 pt-2">
                {activeRbRows.slice(0, 3).map((row) => (
                  <div key={row.label} className="flex items-center gap-1.5">
                    <span className="w-9 text-right text-[8px] uppercase tracking-wide text-text-dim">
                      {row.label}
                    </span>
                    <div className="flex gap-1.5">
                      {row.keys.map((k, ki) => {
                        const n = rbN(rb, k);
                        if (!n) return null;
                        return (
                          <span key={k} className="flex items-center gap-0.5">
                            <row.Icon
                              className="h-3 w-3"
                              style={{ color: MEDAL_COLORS[ki] } as React.CSSProperties}
                            />
                            <span
                              className="font-mono text-[9px]"
                              style={{ color: MEDAL_COLORS[ki] }}
                            >
                              ×{n}
                            </span>
                          </span>
                        );
                      })}
                    </div>
                  </div>
                ))}
                {hasAwards && (
                  <div className="flex items-center gap-1.5">
                    <span className="w-9 text-right text-[8px] uppercase tracking-wide text-text-dim">
                      Awd
                    </span>
                    <div className="flex gap-1.5">
                      {mvp > 0 && (
                        <span className="flex items-center gap-0.5">
                          <Star className="h-3 w-3 text-accent-gold" />
                          <span className="font-mono text-[9px] text-accent-gold">×{mvp}</span>
                        </span>
                      )}
                      {allpro > 0 && (
                        <span className="flex items-center gap-0.5">
                          <Shield className="h-3 w-3 text-accent-hex" />
                          <span className="font-mono text-[9px] text-accent-hex">×{allpro}</span>
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Footer stats */}
            <div className="mt-auto border-t border-border/60 pt-2">
              <div className="flex justify-between text-[9px] text-text-dim">
                <span>
                  CareerLPS{" "}
                  <span className="font-mono text-text-muted">
                    {fmtInt(player.career_lps?.total_score)}
                  </span>
                </span>
                <span>
                  Peak{" "}
                  <span className="font-mono text-text-muted">
                    {fmt(player.career_lps?.peak_lps)}
                  </span>
                </span>
                <span>
                  WR{" "}
                  <span className="font-mono text-text-muted">{fmtPct(player.win_rate)}</span>
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* ================================================================
            BACK
        ================================================================ */}
        <div
          style={{
            ...faceStyle,
            transform: "rotateY(180deg)",
          }}
        >
          {/* Tier accent stripe */}
          <div
            style={{
              height: 3,
              flexShrink: 0,
              background: `linear-gradient(90deg, ${accentColor}00, ${accentColor}, ${accentColor}00)`,
            }}
          />

          <div className="flex flex-1 flex-col px-4 pb-3 pt-2.5">
            {/* Compact header */}
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold text-text">{player.playername}</h2>
              <TierBadge tier={tier} size="sm" />
            </div>
            <p className="text-[8.5px] uppercase tracking-widest text-text-dim">
              Percentile profile
            </p>

            {/* Radar — stop click so toggle doesn't flip card */}
            <div
              className="mt-1 flex justify-center"
              onClick={(e) => e.stopPropagation()}
            >
              <CardRadar player={player} accentColor={accentColor} />
            </div>

            {/* HN + rate stats */}
            <div className="mt-auto border-t border-border/60 pt-2 text-[9px] text-text-dim">
              <div className="flex justify-between">
                {hn.hn_lane_best != null && (
                  <span>
                    HN Lane{" "}
                    <span className="font-mono text-text-muted">#{hn.hn_lane_best}</span>
                  </span>
                )}
                {hn.hn_global_best != null && (
                  <span>
                    HN Global{" "}
                    <span className="font-mono text-text-muted">#{hn.hn_global_best}</span>
                  </span>
                )}
                {player.rates?.pts_per_game != null && (
                  <span>
                    LPS/Gm{" "}
                    <span className="font-mono text-text-muted">
                      {player.rates.pts_per_game.toFixed(3)}
                    </span>
                  </span>
                )}
              </div>
              <p className="mt-2 text-center text-[8px] text-text-dim/60">
                Click anywhere to flip
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
