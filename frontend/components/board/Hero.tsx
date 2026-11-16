"use client";

/* eslint-disable @next/next/no-img-element */
// Rankings masthead, in the manner of a hall-of-fame induction poster: the
// all-time top five as cutouts rising out of a deco sunburst over a neon floor,
// with their names set along the bottom.

import { displayName, localRealName } from "@/lib/format";
import { useLocale, useT } from "@/lib/i18n";
import { LanguageSwitcher } from "@/components/i18n/LanguageSwitcher";
import Link from "next/link";
import type { IndexRow } from "@/lib/types";
import { TIER_COLORS } from "@/lib/theme";

// Stage slot per leaderboard rank (#1 centre, #2 left, #3 right, #4 / #5 outer):
// [left %, height px, z, opacity]
const SLOTS: [number, number, number, number][] = [
  [50, 330, 5, 1],
  [31, 280, 4, 0.92],
  [69, 280, 4, 0.92],
  [14, 235, 3, 0.75],
  [86, 235, 3, 0.75],
];
// Left-to-right reading order of the stage, for the name roll beneath it.
const STAGE_ORDER = [3, 1, 0, 2, 4];

export function Hero({ rows, asOf = null }: { rows: IndexRow[]; asOf?: number | null }) {
  const m = useT();
  const locale = useLocale();
  const top = rows.slice(0, 5);
  const roll = STAGE_ORDER.map((i) => top[i]).filter(Boolean);

  return (
    <section className="relative overflow-hidden border-b border-gold-deep/50">
      {/* sunburst + floor */}
      <div
        className="absolute inset-0"
        style={{
          background: `radial-gradient(ellipse 45% 60% at 50% 88%, rgba(241,213,143,0.22), transparent 70%),
            repeating-conic-gradient(from -90deg at 50% 92%, rgba(241,213,143,0.07) 0deg 1.6deg, transparent 1.6deg 6deg),
            radial-gradient(ellipse 80% 70% at 50% 100%, rgba(12,111,116,0.35), transparent 70%),
            linear-gradient(180deg, #03070d 0%, #071322 70%, #03070d 100%)`,
        }}
      />
      <div
        className="absolute inset-x-[-20%] bottom-0 h-[180px]"
        style={{
          backgroundImage:
            "linear-gradient(rgba(31,209,193,0.45) 1px, transparent 1px), linear-gradient(90deg, rgba(31,209,193,0.45) 1px, transparent 1px)",
          backgroundSize: "44px 44px",
          transform: "perspective(240px) rotateX(62deg)",
          transformOrigin: "50% 100%",
          maskImage: "linear-gradient(to top, black, transparent 90%)",
          WebkitMaskImage: "linear-gradient(to top, black, transparent 90%)",
        }}
      />
      {/* horizon line */}
      <div className="neon-line absolute inset-x-0 bottom-[150px] h-px opacity-60" />

      <div className="relative mx-auto max-w-6xl px-4">
        <div className="absolute right-4 top-3 z-10 flex items-center gap-5">
          <LanguageSwitcher />
          <Link
            href="/about"
            className="font-serif text-[11px] font-bold uppercase tracking-[0.25em] text-text-dim hover:text-gold-bright"
          >
            {m.nav.about} ▸
          </Link>
        </div>
        {/* masthead */}
        <div className="pt-10 text-center">
          <div className="deco-rule mx-auto max-w-md font-serif text-[11px] font-bold uppercase tracking-[0.45em] text-gold">
            <span>{m.hero.kicker}</span>
          </div>
          <h1 className="mt-3 font-display text-[56px] font-black uppercase leading-[0.85] tracking-[0.02em] sm:text-[88px]">
            <span className="text-metal">{m.hero.titleA}</span>{" "}
            <span className="font-serif text-[0.62em] font-semibold tracking-[0.12em] text-text">{m.hero.titleB}</span>
          </h1>
          <p className="mt-3 font-serif text-[11px] font-semibold uppercase tracking-[0.32em] text-text-muted">
            {m.hero.subtitle}
            {asOf !== null && (
              <>
                {" "}
                <span className="text-teal">◆</span> <span className="text-gold">{m.hero.asOf(asOf)}</span>
              </>
            )}
          </p>
        </div>

        {/* stage */}
        <div className="relative mx-auto mt-4 h-[230px] max-w-4xl sm:h-[350px]">
          {top.map((r, i) => {
            const slot = SLOTS[i];
            const rank = r.rank;
            return (
              <Link
                key={r.slug}
                href={`/card/${r.slug}`}
                className="group absolute bottom-0 -translate-x-1/2 transition-transform duration-300 hover:-translate-y-1"
                style={{ left: `${slot[0]}%`, zIndex: slot[2], opacity: slot[3] }}
                title={m.hero.viewCard(rank, displayName(r.playername))}
              >
                {r.photo ? (
                  // Glow lives on the wrapper: a mask clips its own element's filter output to the
                  // border box, which squared off the drop-shadow when both sat on the <img>.
                  <span
                    className="block"
                    style={{
                      filter: `drop-shadow(0 0 1px rgba(255,255,255,0.3)) drop-shadow(0 0 22px ${TIER_COLORS[r.tier]}55)`,
                    }}
                  >
                    <img
                      src={r.photo}
                      alt={displayName(r.playername)}
                      referrerPolicy="no-referrer"
                      className="block w-auto max-w-none object-contain"
                      style={{
                        height: `min(${slot[1]}px, ${Math.round(slot[1] / 5.4)}vw)`,
                        maskImage: "linear-gradient(to bottom, black 72%, transparent 100%)",
                        WebkitMaskImage: "linear-gradient(to bottom, black 72%, transparent 100%)",
                      }}
                    />
                  </span>
                ) : (
                  <div style={{ height: slot[1] * 0.6 }} />
                )}
                <span
                  className="absolute left-1/2 top-[6%] -translate-x-1/2 font-display text-5xl font-black outline-text"
                  style={{ color: TIER_COLORS[r.tier], opacity: 0.55, zIndex: -1 }}
                  aria-hidden
                >
                  {rank}
                </span>
              </Link>
            );
          })}
        </div>

        {/* name roll, poster style */}
        <div className="relative flex flex-wrap items-end justify-center gap-y-3 pb-7 pt-4">
          {roll.map((r, i) => (
            <Link
              key={r.slug}
              href={`/player/${r.slug}`}
              className={`group flex flex-col items-center px-4 text-center sm:px-6 ${
                i > 0 ? "border-l border-gold-deep/70" : ""
              }`}
            >
              <span className="text-[9px] font-semibold uppercase tracking-[0.28em] text-text-muted">
                {localRealName(r, locale) ?? `#${r.rank}`}
              </span>
              <span className="font-display text-2xl font-black uppercase leading-none tracking-wide text-text group-hover:text-gold-bright sm:text-[28px]">
                <span className="mr-1.5 text-metal">{r.rank}</span>
                {displayName(r.playername)}
              </span>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
