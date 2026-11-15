/* eslint-disable @next/next/no-img-element */
// Official event / league marks, a medal-tinted honor glyph, and the round
// player portrait used across the board, profile and card.

import type { Honor, TitleTally } from "@/lib/types";
import { EVENT_ICON, EVENT_LABEL, leagueIcon, type EventKey } from "@/lib/icons";
import { MEDAL_COLOR, MEDAL_METAL } from "@/lib/theme";
import { CupDomestic, CupIntl } from "@/components/profile/AchievementIcons";

type Medal = "gold" | "silver" | "bronze";

/** Worlds / MSI / First Stand mark, cast in a medal metal (default: gold). */
export function EventMark({
  event,
  medal = "gold",
  size = 20,
  title,
  className = "",
}: {
  event: EventKey;
  medal?: Medal;
  size?: number;
  title?: string;
  className?: string;
}) {
  return (
    <span
      role="img"
      aria-label={title ?? EVENT_LABEL[event]}
      title={title ?? EVENT_LABEL[event]}
      className={`mark-mask inline-block shrink-0 ${className}`}
      style={
        {
          width: size,
          height: size,
          "--mark": `url(${EVENT_ICON[event]})`,
          "--tint": MEDAL_METAL[medal],
        } as React.CSSProperties
      }
    />
  );
}

/** A league's own logo in its own colours; null when we have no mark for it. */
export function LeagueMark({
  league,
  size = 18,
  className = "",
}: {
  league: string | null | undefined;
  size?: number;
  className?: string;
}) {
  const icon = leagueIcon(league);
  if (!icon) return null;
  return (
    <img
      src={icon.src}
      alt={league ?? ""}
      title={league ?? ""}
      width={size}
      height={size}
      className={`inline-block shrink-0 object-contain ${className}`}
      style={{ width: size, height: size, filter: icon.invert ? "invert(1)" : undefined }}
    />
  );
}

/** One podium finish as a glyph: official mark for Worlds / MSI / First Stand /
 *  the league, a cup silhouette for everything else. Medal shown by tint/ring. */
export function HonorMark({ honor, size = 20 }: { honor: Honor; size?: number }) {
  const label = honorLabel(honor);
  if (honor.kind === "worlds" || honor.kind === "msi" || honor.kind === "first_stand") {
    return <EventMark event={honor.kind} medal={honor.medal} size={size} title={label} />;
  }
  if (honor.kind === "domestic" && leagueIcon(honor.league)) {
    return (
      <span
        title={label}
        className="relative inline-flex shrink-0 items-center justify-center rounded-full"
        style={{
          width: size + 6,
          height: size + 6,
          boxShadow: `inset 0 0 0 1.5px ${MEDAL_COLOR[honor.medal]}`,
          background: "radial-gradient(circle, rgba(255,255,255,0.06), transparent 70%)",
        }}
      >
        <LeagueMark league={honor.league} size={size - 4} />
      </span>
    );
  }
  const Cup = honor.kind === "intl" ? CupIntl : CupDomestic;
  return (
    <span title={label} className="inline-flex shrink-0" style={{ color: MEDAL_COLOR[honor.medal] }}>
      <Cup className="" style={{ width: size, height: size }} />
    </span>
  );
}

const PLACE: Record<Medal, string> = { gold: "Champion", silver: "Finalist", bronze: "Semifinalist" };

export function honorLabel(h: Honor): string {
  const what =
    h.kind === "domestic"
      ? h.league ?? "League"
      : h.kind === "cup" || h.kind === "intl"
        ? h.event ?? EVENT_LABEL[h.kind]
        : EVENT_LABEL[h.kind];
  return `${h.year} ${what} — ${PLACE[h.medal]}`;
}

/** Trophy pills for a rankings row: Worlds / MSI / First Stand / league titles. */
export function TrophyPills({ titles, compact = false }: { titles?: TitleTally | null; compact?: boolean }) {
  if (!titles) return <span className="text-xs text-text-dim">—</span>;
  const pills: { key: string; node: React.ReactNode; n: number; label: string }[] = [];
  const ev = (k: EventKey, n?: number) =>
    n && pills.push({ key: k, n, label: `${n}× ${EVENT_LABEL[k]} champion`, node: <EventMark event={k} size={16} /> });
  ev("worlds", titles.worlds);
  ev("msi", titles.msi);
  ev("first_stand", titles.first_stand);
  if (titles.domestic) {
    pills.push({
      key: "dom",
      n: titles.domestic,
      label: `${titles.domestic}× domestic champion${titles.league ? ` (mostly ${titles.league})` : ""}`,
      node: leagueIcon(titles.league) ? (
        <LeagueMark league={titles.league} size={15} />
      ) : (
        <CupDomestic className="h-4 w-4 text-gold" />
      ),
    });
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {pills.map((p) => (
        <span
          key={p.key}
          title={p.label}
          className={`inline-flex items-center gap-1 rounded-full border border-gold-deep/60 bg-black/40 ${
            compact ? "px-1.5 py-0.5" : "px-2 py-0.5"
          }`}
        >
          {p.node}
          <span className="font-display text-[13px] font-bold leading-none text-gold-bright">{p.n}</span>
        </span>
      ))}
    </div>
  );
}

/** Round portrait in a gold ring (Leaguepedia photo, monogram fallback). */
export function Portrait({
  src,
  name,
  size = 40,
  ring = "#c9a45c",
  className = "",
}: {
  src?: string | null;
  name: string;
  size?: number;
  ring?: string;
  className?: string;
}) {
  return (
    <span
      className={`relative inline-flex shrink-0 items-end justify-center overflow-hidden rounded-full ${className}`}
      style={{
        width: size,
        height: size,
        background: `radial-gradient(circle at 50% 30%, ${ring}33, #07101a 72%)`,
        boxShadow: `inset 0 0 0 1.5px ${ring}, 0 0 0 2px #03070d, 0 0 12px ${ring}40`,
      }}
    >
      {src ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          className="h-[118%] w-[118%] max-w-none object-cover object-top"
        />
      ) : (
        <span
          className="self-center font-serif font-bold"
          style={{ color: ring, fontSize: size * 0.42 }}
        >
          {name.trim()[0]?.toUpperCase() ?? "?"}
        </span>
      )}
    </span>
  );
}
