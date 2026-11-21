"use client";

/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import type { PlayerDetail } from "@/lib/types";
import { fmt, fmtInt, fmtPct, laneLabel, displayName, localRealName } from "@/lib/format";
import { TIER_COLORS, editionFor, editionLabel, upper, cardTeamLogo } from "@/lib/theme";
import { useLocale, useT } from "@/lib/i18n";
import { countryName } from "@/lib/i18n/countries";
import { TierBadge } from "@/components/board/TierBadge";
import { HolCrown, StatusDot } from "@/components/board/StatusBadges";
import { EventMark, LeagueMark } from "@/components/ui/Marks";
import { Star } from "./AchievementIcons";

/** Profile masthead: cutout portrait over a deco sunburst, engraved name,
 *  and a row of plaques (rank / lane rank / CLR) plus headline trophies. */
export function ProfileHeader({
  player,
  laneRank,
}: {
  player: PlayerDetail;
  laneRank: number | null;
}) {
  const m = useT();
  const locale = useLocale();
  const realName = localRealName(player, locale);
  const isHol = player.hall_of_legends;
  const tier = player.tier ?? "contenders";
  const accent = isHol ? "#f1d58f" : TIER_COLORS[tier];
  const edition = editionFor(player);
  const team = cardTeamLogo(player);
  const lanes =
    player.positions && player.positions.length > 1
      ? player.positions.map((p) => laneLabel(m, p.lane)).join(" / ")
      : laneLabel(m, player.position);
  const handle = displayName(player.playername);
  const gold = (player.honors ?? []).filter((h) => h.medal === "gold");
  const count = (k: string) => gold.filter((h) => h.kind === k).length;
  const mvp = player.resume_breakdown?.mvp?.n ?? 0;

  return (
    <header className="deco-panel !p-0 overflow-hidden">
      <div className="relative min-h-[300px]">
        {/* stage */}
        <div
          className="absolute inset-0"
          style={{
            background: `radial-gradient(ellipse 35% 80% at 22% 100%, ${accent}40, transparent 70%),
              repeating-conic-gradient(from -90deg at 22% 105%, rgba(241,213,143,0.07) 0deg 1.6deg, transparent 1.6deg 6.5deg),
              linear-gradient(90deg, #091726 0%, #060e19 55%, #050b14 100%)`,
          }}
        />
        <div
          className="absolute bottom-0 left-0 h-[120px] w-[55%]"
          style={{
            backgroundImage:
              "linear-gradient(rgba(31,209,193,0.4) 1px, transparent 1px), linear-gradient(90deg, rgba(31,209,193,0.4) 1px, transparent 1px)",
            backgroundSize: "32px 32px",
            transform: "perspective(200px) rotateX(60deg)",
            transformOrigin: "50% 100%",
            maskImage: "linear-gradient(to top, black, transparent 90%)",
            WebkitMaskImage: "linear-gradient(to top, black, transparent 90%)",
          }}
        />
        {/* watermark */}
        <div
          className="pointer-events-none absolute right-4 top-2 select-none font-display text-[150px] font-black uppercase leading-none outline-text"
          style={{ color: accent, opacity: 0.12 }}
          aria-hidden
        >
          {handle}
        </div>

        <div className="relative flex flex-col gap-6 px-4 pt-6 sm:px-6 md:flex-row md:items-end md:pt-0">
          {/* portrait */}
          <div className="relative mx-auto h-[260px] w-[300px] shrink-0 md:mx-0 md:mt-6 md:h-[290px]">
            {player.photo ? (
              // Glow lives on the wrapper: a mask clips its own element's filter output to the
              // border box, which squared off the drop-shadow when both sat on the <img>.
              <div
                className="absolute bottom-0 left-1/2 h-full -translate-x-1/2"
                style={{ filter: `drop-shadow(0 0 1px rgba(255,255,255,0.3)) drop-shadow(0 0 24px ${accent}55)` }}
              >
                <img
                  src={player.photo}
                  alt={handle}
                  referrerPolicy="no-referrer"
                  className="block h-full w-auto max-w-none object-contain"
                  style={{
                    maskImage: "linear-gradient(to bottom, black 80%, transparent 100%)",
                    WebkitMaskImage: "linear-gradient(to bottom, black 80%, transparent 100%)",
                  }}
                />
              </div>
            ) : (
              <div className="absolute inset-x-0 bottom-10 flex justify-center">
                <div
                  className="flex h-32 w-32 rotate-45 items-center justify-center border-2"
                  style={{ borderColor: accent, background: `${accent}14` }}
                >
                  <span className="-rotate-45 font-serif text-5xl font-bold" style={{ color: accent }}>
                    {handle[0]?.toUpperCase()}
                  </span>
                </div>
              </div>
            )}
            {player.photo_caption && (
              <span className="absolute bottom-1 right-0 text-[9px] uppercase tracking-[0.2em] text-text-dim">
                {m.profile.photo(player.photo_caption)}
              </span>
            )}
          </div>

          {/* identity */}
          <div className="min-w-0 flex-1 pb-6">
            <div className="flex flex-wrap items-center gap-2">
              {player.tier && <TierBadge tier={player.tier} size="md" />}
              <span className="font-serif text-[10px] font-bold uppercase tracking-[0.3em]" style={{ color: edition.color }}>
                {edition.kind === "tier" ? "" : editionLabel(m, edition)}
                {isHol && player.hol_year ? ` · ${player.hol_year}` : ""}
              </span>
            </div>
            {realName && (
              <div className="mt-3 text-[11px] font-semibold tracking-[0.25em] text-text-muted sm:tracking-[0.4em]">
                {upper(realName)}
                {player.country ? <span className="text-text-dim"> · {upper(countryName(player.country, locale))}</span> : null}
              </div>
            )}
            <div className="flex items-center gap-3">
              <StatusDot row={player} />
              <h1 className="truncate font-serif text-4xl font-extrabold tracking-[0.04em] text-metal sm:text-5xl md:text-6xl">
                {upper(handle)}
              </h1>
              {isHol && <HolCrown year={player.hol_year} />}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm font-semibold uppercase tracking-[0.18em] text-text-muted">
              {team && <img src={team.logo} alt={player.current_team ?? ""} aria-hidden referrerPolicy="no-referrer" className="h-5 w-5 object-contain" />}
              <span>{player.current_team ?? "—"}</span>
              <span className="text-gold">◆</span>
              <LeagueMark league={player.current_league} size={16} />
              <span>{player.current_league ?? "—"}</span>
              <span className="text-gold">◆</span>
              <span>{lanes}</span>
            </div>
            <div className="mt-1 font-mono text-xs text-text-dim">
              {m.profile.years(player.first_year, player.last_year, player.n_years)} ·{" "}
              {m.common.games(fmtInt(player.games))} · {m.common.winRate(fmtPct(player.win_rate))}
              {player.career_stats?.kda != null && <> · {m.common.kda(fmt(player.career_stats.kda, 2))}</>}
            </div>

            {/* headline trophies */}
            {(gold.length > 0 || mvp > 0) && (
              <div className="mt-4 flex flex-wrap items-center gap-4">
                {count("worlds") > 0 && <Trophy node={<EventMark event="worlds" size={30} />} n={count("worlds")} label={m.profile.trophy.worlds} />}
                {count("msi") > 0 && <Trophy node={<EventMark event="msi" size={30} />} n={count("msi")} label={m.profile.trophy.msi} />}
                {count("first_stand") > 0 && (
                  <Trophy node={<EventMark event="first_stand" size={30} />} n={count("first_stand")} label={m.profile.trophy.first_stand} />
                )}
                {count("ewc") > 0 && (
                  <Trophy node={<EventMark event="ewc" size={30} />} n={count("ewc")} label={m.profile.trophy.ewc} />
                )}
                {count("domestic") > 0 && (
                  <Trophy
                    node={<LeagueMark league={topLeague(player)} size={28} />}
                    n={count("domestic")}
                    label={m.profile.trophy.domestic}
                  />
                )}
                {mvp > 0 && <Trophy node={<Star className="h-7 w-7 text-gold-bright" />} n={mvp} label={m.profile.trophy.mvp} />}
              </div>
            )}
          </div>

          {/* plaques */}
          <div className="flex flex-wrap gap-3 pb-6 md:flex-col md:flex-nowrap md:items-stretch">
            <Plaque label="CLR" value={fmt(player.clr, 1)} big accent={accent} />
            <div className="flex flex-1 gap-3 md:flex-none">
              <Plaque label={m.profile.global} value={`#${player.rank}`} />
              {laneRank && player.position && <Plaque label={laneLabel(m, player.position)} value={`#${laneRank}`} />}
            </div>
            <Link
              href={`/card/${player.slug}`}
              className="deco-control w-full px-3 py-1.5 text-center font-serif text-[10px] font-bold uppercase tracking-[0.25em] text-gold-bright hover:border-gold hover:text-text"
            >
              {m.nav.viewCard} ▸
            </Link>
          </div>
        </div>
      </div>
    </header>
  );
}

function topLeague(p: PlayerDetail): string | null {
  const leagues = (p.honors ?? []).filter((h) => h.kind === "domestic" && h.medal === "gold" && h.league).map((h) => h.league!);
  if (!leagues.length) return p.current_league;
  return leagues.sort((a, b) => leagues.filter((x) => x === b).length - leagues.filter((x) => x === a).length)[0];
}

function Trophy({ node, n, label }: { node: React.ReactNode; n: number; label: string }) {
  const m = useT();
  return (
    <div className="flex items-center gap-2" title={m.profile.trophyTitle(n, label)}>
      {node}
      <div className="leading-none">
        <div className="font-display text-2xl font-black text-gold-bright">×{n}</div>
        <div className="text-[8px] font-bold uppercase tracking-[0.2em] text-text-dim">{label}</div>
      </div>
    </div>
  );
}

function Plaque({ label, value, big = false, accent }: { label: string; value: string; big?: boolean; accent?: string }) {
  return (
    <div
      className={`flex flex-col items-center justify-center ${big ? "min-w-[132px] flex-1 px-4 py-2 md:flex-none" : "min-w-[62px] flex-1 px-3 py-1.5"}`}
      style={{
        clipPath: "polygon(8px 0, calc(100% - 8px) 0, 100% 8px, 100% calc(100% - 8px), calc(100% - 8px) 100%, 8px 100%, 0 calc(100% - 8px), 0 8px)",
        background: big ? `linear-gradient(180deg, ${accent}22, rgba(5,11,20,0.85))` : "rgba(5,11,20,0.75)",
        boxShadow: `inset 0 0 0 1px ${big ? `${accent}aa` : "rgba(201,164,92,0.45)"}`,
      }}
    >
      <span className={`font-display font-black leading-none ${big ? "text-5xl text-metal" : "text-2xl text-text"}`}>{value}</span>
      <span className="mt-1 font-serif text-[8px] font-bold uppercase tracking-[0.28em] text-teal">{label}</span>
    </div>
  );
}
