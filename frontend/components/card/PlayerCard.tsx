"use client";
/* eslint-disable @next/next/no-img-element */

import { useState } from "react";
import type { PlayerDetail, TierKey } from "@/lib/types";
import { displayName, fmt, fmtInt, fmtPct, laneLabel } from "@/lib/format";
import {
  TIER_COLORS,
  TIER_SINGULAR,
  TEAL,
  GOLD,
  cardTeamLogo,
  editionFor,
  upper,
  type Edition,
} from "@/lib/theme";
import { EventMark, HonorMark, LeagueMark } from "@/components/ui/Marks";
import { Star } from "@/components/profile/AchievementIcons";
import { CardRadar } from "./CardRadar";

// Card geometry (CSS px). Trading-card-ish proportions, a little taller to fit
// the stat tiles and trophy shelf under the portrait.
const W = 340;
const H = 520;
const CUT = 18;

const octagon = (inset: number, cut: number) => {
  const a = inset, b = W - inset, c = H - inset;
  return `${a + cut},${a} ${b - cut},${a} ${b},${a + cut} ${b},${c - cut} ${b - cut},${c} ${a + cut},${c} ${a},${c - cut} ${a},${a + cut}`;
};
const clipOct = (inset: number, cut: number) =>
  `polygon(${octagon(inset, cut)
    .split(" ")
    .map((p) => p.split(",").map((v) => `${v}px`).join(" "))
    .join(", ")})`;

const CLR_PARTS = [
  { key: "career_value" as const, label: "Career", color: "#1fd1c1" },
  { key: "pace_value" as const, label: "Pace", color: "#3fbfe8" },
  { key: "peak_value" as const, label: "Peak", color: "#b28bff" },
  { key: "resume_bonus" as const, label: "Résumé", color: "#e9c77a" },
];

// ---------------------------------------------------------------------------
// Shared chrome
// ---------------------------------------------------------------------------

/** Gold octagonal frame + inner neon hairline + deco corner hatching. */
function FrameLines({ accent }: { accent: string }) {
  const id = `metal-${accent.replace("#", "")}`;
  return (
    <svg
      className="pointer-events-none absolute inset-0"
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      aria-hidden
    >
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#7d5b28" />
          <stop offset="25%" stopColor="#f1d58f" />
          <stop offset="50%" stopColor="#a77d38" />
          <stop offset="70%" stopColor="#f6e2a8" />
          <stop offset="100%" stopColor="#8d672e" />
        </linearGradient>
      </defs>
      <polygon points={octagon(1.5, CUT)} fill="none" stroke={`url(#${id})`} strokeWidth={3} />
      <polygon
        points={octagon(8, CUT - 3)}
        fill="none"
        stroke={TEAL}
        strokeOpacity={0.55}
        strokeWidth={0.75}
        style={{ filter: `drop-shadow(0 0 3px ${TEAL})` }}
      />
      {/* Deco hatching echoing each chamfer */}
      {[0, 1, 2].map((i) => {
        const d = 14 + i * 6;
        return (
          <g key={i} stroke={`url(#${id})`} strokeWidth={0.9} opacity={0.75 - i * 0.2}>
            <line x1={8} y1={CUT + d} x2={CUT + d} y2={8} />
            <line x1={W - 8} y1={H - CUT - d} x2={W - CUT - d} y2={H - 8} />
          </g>
        );
      })}
      {/* Keystone lozenges at top / bottom centre */}
      <path d={`M${W / 2 - 7} 1.5 L${W / 2} -5 L${W / 2 + 7} 1.5 L${W / 2} 8 Z`} fill={`url(#${id})`} />
      <path d={`M${W / 2 - 7} ${H - 1.5} L${W / 2} ${H - 8} L${W / 2 + 7} ${H - 1.5} L${W / 2} ${H + 5} Z`} fill={`url(#${id})`} />
      <circle cx={W / 2} cy={H - 3} r={1.6} fill={accent} />
    </svg>
  );
}

function Face({
  children,
  back = false,
  accent,
  shimmer,
}: {
  children: React.ReactNode;
  back?: boolean;
  accent: string;
  shimmer: boolean;
}) {
  return (
    <div
      className="absolute inset-0"
      style={{
        backfaceVisibility: "hidden",
        WebkitBackfaceVisibility: "hidden",
        transform: back ? "rotateY(180deg)" : undefined,
        filter: `drop-shadow(0 18px 30px rgba(0,0,0,0.65)) drop-shadow(0 0 22px ${accent}38)`,
      }}
    >
      <div
        className="absolute inset-0 overflow-hidden"
        style={{
          clipPath: clipOct(0, CUT),
          background: "linear-gradient(180deg, #0b1828 0%, #050b14 100%)",
        }}
      >
        {children}
        {shimmer && (
          <div
            className="pointer-events-none absolute inset-0 animate-sheen mix-blend-screen"
            style={{
              backgroundImage:
                "linear-gradient(115deg, transparent 38%, rgba(255,240,200,0.10) 46%, rgba(160,255,245,0.12) 50%, transparent 58%)",
              backgroundSize: "300% 100%",
            }}
          />
        )}
      </div>
      <FrameLines accent={accent} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Front pieces
// ---------------------------------------------------------------------------

function PhotoStage({ player, accent }: { player: PlayerDetail; accent: string }) {
  const name = displayName(player.playername);
  const wmSize = Math.min(150, Math.floor(560 / Math.max(3, name.length)));
  return (
    <div className="absolute inset-x-0 top-0" style={{ height: 336 }}>
      {/* sky: tier glow + gold sunburst rising from behind the player */}
      <div
        className="absolute inset-0"
        style={{
          background: `radial-gradient(ellipse 70% 55% at 50% 78%, ${accent}55, transparent 70%),
            repeating-conic-gradient(from -90deg at 50% 92%, rgba(241,213,143,0.10) 0deg 2.2deg, transparent 2.2deg 8deg),
            linear-gradient(180deg, #0a1a2c 0%, #071220 60%, #050b14 100%)`,
        }}
      />
      {/* neon floor grid receding to the horizon */}
      <div
        className="absolute inset-x-[-30%] bottom-0 h-[150px]"
        style={{
          backgroundImage: `linear-gradient(${TEAL}66 1px, transparent 1px), linear-gradient(90deg, ${TEAL}66 1px, transparent 1px)`,
          backgroundSize: "28px 28px",
          transform: "perspective(160px) rotateX(58deg)",
          transformOrigin: "50% 100%",
          maskImage: "linear-gradient(to top, rgba(0,0,0,0.9), transparent 85%)",
          WebkitMaskImage: "linear-gradient(to top, rgba(0,0,0,0.9), transparent 85%)",
        }}
      />
      {/* watermark handle */}
      <div
        className="absolute inset-x-0 top-[46px] select-none overflow-hidden whitespace-nowrap text-center font-display font-black uppercase leading-none outline-text"
        style={{ fontSize: wmSize, color: accent, opacity: 0.32, letterSpacing: "0.02em" }}
        aria-hidden
      >
        {name}
      </div>
      {player.photo ? (
        <img
          src={player.photo}
          alt={displayName(player.playername)}
          referrerPolicy="no-referrer"
          className="absolute bottom-[14px] left-1/2 h-[292px] w-auto max-w-none -translate-x-1/2 object-contain"
          style={{
            filter: `drop-shadow(0 0 1px rgba(255,255,255,0.35)) drop-shadow(0 0 16px ${accent}55)`,
          }}
        />
      ) : (
        <div className="absolute inset-x-0 bottom-[60px] flex justify-center">
          <div
            className="flex h-36 w-36 rotate-45 items-center justify-center border-2"
            style={{ borderColor: accent, background: `${accent}14`, boxShadow: `0 0 30px ${accent}40` }}
          >
            <span className="-rotate-45 font-serif text-6xl font-bold" style={{ color: accent }}>
              {name[0]?.toUpperCase()}
            </span>
          </div>
        </div>
      )}
      {/* floor fade into the nameplate */}
      <div
        className="absolute inset-x-0 bottom-0 h-24"
        style={{ background: "linear-gradient(to top, #050b14 8%, transparent)" }}
      />
    </div>
  );
}

function TeamBadge({ player }: { player: PlayerDetail }) {
  const team = cardTeamLogo(player);
  return (
    <div className="absolute left-[18px] top-[22px] flex h-[46px] w-[46px] items-center justify-center">
      <div
        className="absolute inset-[5px] rotate-45 border border-gold/80 bg-black/55 backdrop-blur-sm"
        style={{ boxShadow: `0 0 0 2px #050b14, 0 0 0 3px ${GOLD}55` }}
      />
      {team ? (
        <img
          src={team.logo}
          alt={team.name}
          title={team.name}
          referrerPolicy="no-referrer"
          className="relative h-[26px] w-[26px] object-contain"
        />
      ) : (
        <LeagueMark league={player.current_league} size={22} className="relative" />
      )}
    </div>
  );
}

function RankPlaque({ rank }: { rank: number }) {
  return (
    <div
      className="absolute right-[18px] top-[18px] flex w-[58px] flex-col items-center pb-1.5 pt-1"
      style={{
        clipPath: "polygon(0 0, 100% 0, 100% 80%, 50% 100%, 0 80%)",
        background: "linear-gradient(180deg, rgba(5,11,20,0.92), rgba(12,26,40,0.92))",
        boxShadow: `inset 0 0 0 1px ${GOLD}aa`,
      }}
    >
      <span className="font-serif text-[7px] font-bold tracking-[0.3em] text-gold">RANK</span>
      <span className="font-display text-[30px] font-black leading-[0.95] text-metal">{rank}</span>
    </div>
  );
}

/** Upper-Deck-style plate: chevron fans either side, edition medallion on top. */
function Nameplate({ player, edition }: { player: PlayerDetail; edition: Edition }) {
  const handle = displayName(player.playername);
  const handleSize = handle.length > 11 ? 20 : handle.length > 8 ? 24 : 28;
  return (
    <div className="absolute inset-x-0" style={{ top: 300, height: 104 }}>
      {/* chevron fans */}
      <svg className="absolute inset-0" width={W} height={104} viewBox={`0 0 ${W} 104`} aria-hidden>
        {[0, 1, 2, 3, 4].map((i) => (
          <g key={i} stroke={i % 2 ? TEAL : edition.color} strokeOpacity={i % 2 ? 0.6 : 0.85} strokeWidth={1.2}>
            <line x1={6} y1={104 - i * 9} x2={34 + i * 2} y2={36 - i * 2} />
            <line x1={W - 6} y1={104 - i * 9} x2={W - 34 - i * 2} y2={36 - i * 2} />
          </g>
        ))}
        <polygon
          points={`34,36 ${W - 34},36 ${W - 22},70 ${W - 34},104 34,104 22,70`}
          fill="url(#plateFill)"
          stroke={GOLD}
          strokeWidth={1.2}
        />
        <defs>
          <linearGradient id="plateFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#0f2032" />
            <stop offset="100%" stopColor="#060d17" />
          </linearGradient>
        </defs>
        <line x1={44} y1={40} x2={W - 44} y2={40} stroke={edition.color} strokeOpacity={0.35} strokeWidth={0.6} />
      </svg>

      {/* edition medallion */}
      <div className="absolute left-1/2 top-0 -translate-x-1/2">
        <EditionMedallion edition={edition} tier={player.tier ?? "contenders"} holYear={player.hol_year} />
      </div>

      {/* identity */}
      <div className="absolute inset-x-[40px] top-[44px] flex flex-col items-center text-center">
        {player.real_name && (
          <span className="max-w-full truncate text-[8.5px] font-semibold tracking-[0.32em] text-text-muted">
            {upper(player.real_name)}
          </span>
        )}
        <span
          className="max-w-full truncate font-serif font-extrabold leading-tight tracking-[0.06em] text-metal"
          style={{ fontSize: handleSize }}
        >
          {upper(handle)}
        </span>
        <span className="mt-0.5 flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-[0.22em] text-text-muted">
          <LeagueMark league={player.current_league} size={11} />
          {player.current_team ?? "—"}
          <span className="text-gold">◆</span>
          {laneLabel(player.position)}
        </span>
      </div>
    </div>
  );
}

function EditionMedallion({
  edition,
  tier,
  holYear,
}: {
  edition: Edition;
  tier: TierKey;
  holYear: number | null;
}) {
  const c = edition.color;
  return (
    <div className="relative flex h-[40px] w-[156px] items-center justify-center">
      <svg className="absolute inset-0" width={156} height={40} viewBox="0 0 156 40" aria-hidden>
        <polygon points="16,0 140,0 156,20 140,40 16,40 0,20" fill="#050b14" stroke={c} strokeWidth={1.4} />
        <polygon points="19,3.5 137,3.5 151.5,20 137,36.5 19,36.5 4.5,20" fill="none" stroke={c} strokeOpacity={0.35} strokeWidth={0.7} />
      </svg>
      <div className="relative flex items-center gap-1.5">
        {edition.kind === "worlds" && <EventMark event="worlds" size={20} />}
        {edition.kind === "hol" && <Star className="h-4 w-4" style={{ color: c }} />}
        <div className="flex flex-col items-center leading-none">
          {edition.kind === "tier" ? (
            <>
              <span className="font-display text-[19px] font-black uppercase tracking-wide" style={{ color: c }}>
                {TIER_SINGULAR[tier]}
              </span>
              <span className="mt-[1px] font-serif text-[6.5px] font-bold tracking-[0.35em] text-text-muted">EDITION</span>
            </>
          ) : (
            <>
              <span className="whitespace-nowrap font-serif text-[9.5px] font-extrabold tracking-[0.12em]" style={{ color: c }}>
                {upper(edition.label)}
              </span>
              <span className="mt-[2px] font-serif text-[6.5px] font-bold tracking-[0.35em] text-text-muted">
                {edition.kind === "hol" && holYear ? `INDUCTED ${holYear}` : "EDITION"}
              </span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function StatTile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div
      className="flex flex-1 flex-col items-center"
      style={{
        clipPath: "polygon(6px 0, calc(100% - 6px) 0, 100% 6px, 100% 100%, 0 100%, 0 6px)",
        background: "linear-gradient(180deg, rgba(31,209,193,0.10), rgba(5,11,20,0.6))",
        boxShadow: "inset 0 0 0 1px rgba(201,164,92,0.45)",
      }}
    >
      <span className="w-full bg-teal/15 py-[2px] text-center font-serif text-[7.5px] font-bold tracking-[0.28em] text-neon">
        {label}
      </span>
      <span className="pt-0.5 font-display text-[26px] font-extrabold leading-none text-text">{value}</span>
      <span className="pb-1 pt-0.5 text-[7.5px] font-semibold uppercase tracking-[0.18em] text-text-dim">{sub}</span>
    </div>
  );
}

function TrophyShelf({ player }: { player: PlayerDetail }) {
  const rb = player.resume_breakdown ?? {};
  const honors = player.honors ?? [];
  const n = (k: string) => rb[k]?.n ?? 0;
  const gold = honors.filter((h) => h.medal === "gold");
  const count = (kind: string) => gold.filter((h) => h.kind === kind).length;
  const domLeagues = gold.filter((h) => h.kind === "domestic").map((h) => h.league ?? "");
  const topLeague = domLeagues.sort(
    (a, b) => domLeagues.filter((x) => x === b).length - domLeagues.filter((x) => x === a).length,
  )[0];

  const items: { key: string; node: React.ReactNode; n: number; title: string }[] = [];
  const worlds = count("worlds") || n("wlds_title");
  const msi = count("msi") || n("msi_title");
  const fst = count("first_stand");
  const dom = count("domestic") || n("dom_champ");
  if (worlds) items.push({ key: "w", n: worlds, title: "Worlds titles", node: <EventMark event="worlds" size={22} /> });
  if (msi) items.push({ key: "m", n: msi, title: "MSI titles", node: <EventMark event="msi" size={22} /> });
  if (fst) items.push({ key: "f", n: fst, title: "First Stand titles", node: <EventMark event="first_stand" size={22} /> });
  if (dom)
    items.push({
      key: "d",
      n: dom,
      title: "Domestic titles",
      node: <LeagueMark league={topLeague || player.current_league} size={20} />,
    });
  if (n("mvp")) items.push({ key: "v", n: n("mvp"), title: "MVP awards", node: <Star className="h-5 w-5 text-gold-bright" /> });

  if (!items.length) {
    return (
      <div className="deco-rule text-[9px] font-semibold uppercase tracking-[0.3em] text-text-dim">
        <span>
          {player.first_year}–{player.last_year} · {player.n_years} seasons · {fmtInt(player.games)} games
        </span>
      </div>
    );
  }
  return (
    <div className="flex items-center justify-center gap-3">
      {items.slice(0, 5).map((it) => (
        <span key={it.key} title={`${it.n} ${it.title}`} className="flex items-center gap-1">
          {it.node}
          <span className="font-display text-[17px] font-black leading-none text-gold-bright">×{it.n}</span>
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function PlayerCard({ player }: { player: PlayerDetail }) {
  const [flipped, setFlipped] = useState(false);
  const tier = player.tier ?? "contenders";
  const edition = editionFor(player);
  const accent = edition.kind === "tier" ? TIER_COLORS[tier] : edition.color;
  const shimmer = edition.kind !== "tier" || tier === "goats" || tier === "legends";

  const c = player.clr_components;
  const posTotal = CLR_PARTS.reduce((s, p) => s + Math.max(0, c[p.key] ?? 0), 0) || 1;
  const hn = player.high_noon;
  const cl = player.career_lps;
  const recentHonors = (player.honors ?? []).filter((h) => h.medal === "gold").slice(0, 8);

  return (
    <div
      style={{ width: W, height: H, perspective: "1400px" }}
      className="relative cursor-pointer select-none"
      onClick={() => setFlipped((f) => !f)}
      role="button"
      aria-label={flipped ? "Flip to card front" : "Flip to card back"}
    >
      <div
        className="relative h-full w-full"
        style={{
          transformStyle: "preserve-3d",
          transition: "transform 0.7s cubic-bezier(0.4, 0, 0.2, 1)",
          transform: flipped ? "rotateY(180deg)" : "rotateY(0deg)",
        }}
      >
        {/* ========================= FRONT ========================= */}
        <Face accent={accent} shimmer={shimmer}>
          <PhotoStage player={player} accent={accent} />
          <TeamBadge player={player} />
          <RankPlaque rank={player.rank} />
          <Nameplate player={player} edition={edition} />

          <div className="absolute inset-x-[22px] flex gap-2" style={{ top: 414 }}>
            <StatTile label="CLR" value={fmt(player.clr, 1)} sub={`#${player.rank} all-time`} />
            <StatTile
              label="PEAK"
              value={fmt(cl?.peak_lps, 1)}
              sub={cl?.peak_year ? `LPS · ${cl.peak_year}` : "LPS"}
            />
            <StatTile label="WIN %" value={fmtPct(player.win_rate).replace("%", "")} sub={`${fmtInt(player.games)} games`} />
          </div>

          <div className="absolute inset-x-[22px]" style={{ top: 476 }}>
            <TrophyShelf player={player} />
          </div>
        </Face>

        {/* ========================= BACK ========================= */}
        <Face back accent={accent} shimmer={false}>
          <div
            className="absolute inset-0"
            style={{
              background: `repeating-conic-gradient(from -90deg at 50% 40%, rgba(241,213,143,0.045) 0deg 2deg, transparent 2deg 10deg),
                radial-gradient(ellipse 80% 45% at 50% 38%, ${accent}1c, transparent 70%)`,
            }}
          />
          <div className="relative flex h-full flex-col px-[22px] pb-[22px] pt-[20px]">
            <div className="flex items-center justify-between">
              <div className="min-w-0">
                <div className="truncate font-serif text-[17px] font-extrabold tracking-[0.06em] text-metal">
                  {upper(displayName(player.playername))}
                </div>
                <div className="text-[8px] font-semibold uppercase tracking-[0.28em] text-text-dim">
                  {edition.label} · {laneLabel(player.position)}
                </div>
              </div>
              <span className="font-display text-[26px] font-black leading-none" style={{ color: accent }}>
                #{player.rank}
              </span>
            </div>
            <div className="deco-rule mt-1.5 text-[7px] font-bold tracking-[0.35em] text-gold">
              <span>PERCENTILE PROFILE</span>
            </div>

            <div className="mt-0.5 flex justify-center" onClick={(e) => e.stopPropagation()}>
              <CardRadar player={player} accentColor={accent} />
            </div>

            {/* CLR anatomy */}
            <div className="mt-2">
              <div className="flex h-2 w-full overflow-hidden bg-black/50" style={{ boxShadow: "inset 0 0 0 1px rgba(201,164,92,0.35)" }}>
                {CLR_PARTS.map((p) => {
                  const w = Math.max(0, ((c[p.key] ?? 0) / posTotal) * 100);
                  return w > 0 ? (
                    <div key={p.key} style={{ width: `${w}%`, background: p.color, boxShadow: `0 0 6px ${p.color}` }} />
                  ) : null;
                })}
              </div>
              <div className="mt-1 flex justify-between">
                {CLR_PARTS.map((p) => (
                  <div key={p.key} className="text-center">
                    <div className="text-[7px] font-bold uppercase tracking-[0.18em]" style={{ color: p.color }}>
                      {p.label}
                    </div>
                    <div className="font-mono text-[9px] text-text-muted">{fmt(c[p.key] ?? 0, 1)}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* readouts */}
            <div className="mt-2 grid grid-cols-3 gap-x-2 gap-y-1.5 border-y border-gold-deep/50 py-2">
              <Readout label="Career LPS" value={fmtInt(cl?.total_score)} />
              <Readout label="Seasons" value={`${player.n_years}`} sub={`${player.first_year}–${player.last_year}`} />
              <Readout label="LPS / game" value={player.rates?.pts_per_game != null ? player.rates.pts_per_game.toFixed(3) : "—"} />
              <Readout label="Best lane rk" value={hn?.hn_lane_best != null ? `#${hn.hn_lane_best}` : "—"} />
              <Readout label="Best global rk" value={hn?.hn_global_best != null ? `#${hn.hn_global_best}` : "—"} />
              <Readout label="Peak years" value={`${cl?.peak_years ?? "—"}`} />
            </div>

            {/* honors ribbon */}
            <div className="mt-2 flex min-h-[28px] flex-wrap items-center justify-center gap-x-2 gap-y-1">
              {recentHonors.length ? (
                recentHonors.map((h, i) => (
                  <span key={i} className="flex items-center gap-0.5">
                    <HonorMark honor={h} size={15} />
                    <span className="font-mono text-[8px] text-text-dim">’{String(h.year).slice(2)}</span>
                  </span>
                ))
              ) : (
                <span className="text-[8px] uppercase tracking-[0.25em] text-text-dim">No titles yet</span>
              )}
            </div>

          </div>
        </Face>
      </div>
    </div>
  );
}

function Readout({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="text-center">
      <div className="font-display text-[17px] font-extrabold leading-none text-text">{value}</div>
      <div className="mt-0.5 text-[6.5px] font-bold uppercase tracking-[0.2em] text-teal">{label}</div>
      {sub && <div className="text-[6.5px] text-text-dim">{sub}</div>}
    </div>
  );
}
