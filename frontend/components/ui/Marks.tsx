/* eslint-disable @next/next/no-img-element */
// Official event / league marks, a medal-tinted honor glyph, and the round
// player portrait used across the board, profile and card.

import type { Honor, TitleTally } from "@/lib/types";
import { EVENT_ICON, EVENT_LABEL, isEventKind, leagueIcon, type EventKey } from "@/lib/icons";
import { MEDAL_COLOR, MEDAL_METAL } from "@/lib/theme";
import { CupDomestic, CupIntl } from "@/components/profile/AchievementIcons";

type Medal = "gold" | "silver" | "bronze";

/** Worlds / MSI / First Stand / EWC mark, cast in a medal metal (default: gold). */
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

/** One podium finish as a glyph: official mark for Worlds / MSI / First Stand / EWC /
 *  the league, a cup silhouette for everything else. Medal shown by tint/ring. */
export function HonorMark({ honor, size = 20 }: { honor: Honor; size?: number }) {
  const label = honorLabel(honor);
  if (isEventKind(honor.kind)) {
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

/** "10× LCK champion", "3× LCK, 1× LPL champion"; titles with no known league read "other". */
function domesticLabel(t: TitleTally): string {
  const parts = Object.entries(t.leagues ?? {}).map(([lg, n]) => `${n}× ${lg}`);
  const known = Object.values(t.leagues ?? {}).reduce((a, b) => a + b, 0);
  const other = (t.domestic ?? 0) - known;
  if (!parts.length) return `${t.domestic}× domestic champion`;
  if (other > 0) parts.push(`${other}× other league`);
  return `${parts.join(", ")} champion`;
}

/** Trophy pills for a rankings row: Worlds / MSI / First Stand / EWC / league titles. */
export function TrophyPills({ titles, compact = false }: { titles?: TitleTally | null; compact?: boolean }) {
  if (!titles) return <span className="text-xs text-text-dim">—</span>;
  const pills: { key: string; node: React.ReactNode; n: number; label: string }[] = [];
  const ev = (k: EventKey, n?: number) =>
    n && pills.push({ key: k, n, label: `${n}× ${EVENT_LABEL[k]} champion`, node: <EventMark event={k} size={16} /> });
  ev("worlds", titles.worlds);
  ev("msi", titles.msi);
  ev("first_stand", titles.first_stand);
  ev("ewc", titles.ewc);
  if (titles.domestic) {
    pills.push({
      key: "dom",
      n: titles.domestic,
      label: domesticLabel(titles),
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

/**
 * Ask Leaguepedia's (Fandom) CDN for a width-scaled render of a photo. Shrinking a full-size
 * photo ~10x in the browser aliases fine detail (thin glasses frames break into dots); the
 * CDN resamples properly. Non-Leaguepedia URLs pass through unchanged.
 */
function scaledPhoto(src: string, width: number): string {
  if (!src.includes("/revision/latest")) return src;
  return src.replace(
    /\/revision\/latest(?:\/scale-to-width-down\/\d+)?/,
    `/revision/latest/scale-to-width-down/${width}`,
  );
}

/** Where the head sits in a photo, measured by fetch_player_images (all fractions 0..1). */
export type PhotoFocus = {
  cx?: number | null;   // head centre, of photo width
  ar?: number | null;   // photo width / height
  top?: number | null;  // top of the hair, of photo height
  neck?: number | null; // neck, of photo height
};

// Avatar framing, as fractions of the circle: the hair starts HEAD_TOP down and hair-to-neck
// spans HEAD_SPAN (calibrated on photos that looked right at a flat 1.3x zoom). Photos
// without a measurement keep that flat zoom.
const HEAD_TOP = 0.12;
const HEAD_SPAN = 0.68;
const ZOOM_MIN = 1;
const ZOOM_MAX = 1.6;
const ZOOM_DEFAULT = 1.3;
const TOP_DEFAULT = 0.09;

/**
 * Size, offset and object-position for a photo in a circle of side 1. The photo covers a
 * square box of side `zoom`; it's the box that is offset and zoomed, so a photo shot closer
 * (bigger head) gets less zoom and nobody's chin falls out of the circle.
 *
 * Horizontally, a photo of aspect ar > 1 overflows the box sideways by (ar - 1) box widths;
 * object-position p shifts it left by p of that, so the head lands at cx*ar - p*(ar - 1),
 * which should equal 0.5 for the head to sit in the middle.
 */
function frame(f: PhotoFocus | undefined) {
  const ar = f?.ar ?? 1.26;
  const hScale = ar >= 1 ? 1 : 1 / ar; // photo height per box side (taller photos overflow down)
  let zoom = ZOOM_DEFAULT;
  let top = TOP_DEFAULT;
  if (f?.top != null && f.neck != null && f.neck > f.top) {
    zoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, HEAD_SPAN / ((f.neck - f.top) * hScale)));
    // Keep the box covering the bottom of the circle even if that lifts the head a little.
    top = Math.max(HEAD_TOP - f.top * hScale * zoom, 1 - zoom);
  }
  const posX = f?.cx == null || ar <= 1 ? 0.5 : Math.min(1, Math.max(0, (f.cx * ar - 0.5) / (ar - 1)));
  return { zoom, top, posX, ar };
}

/** Round portrait in a gold ring (Leaguepedia photo, monogram fallback). */
export function Portrait({
  src,
  name,
  focus,
  size = 40,
  ring = "#c9a45c",
  className = "",
}: {
  src?: string | null;
  name: string;
  /** Head position in the photo; framed with a flat zoom when absent. */
  focus?: PhotoFocus;
  size?: number;
  ring?: string;
  className?: string;
}) {
  const fr = frame(focus);
  // On-screen width of the whole photo, for the CDN thumbnail (doubled for high-DPI screens).
  const w1 = Math.ceil((size * fr.zoom * Math.max(fr.ar, 1)) / 10) * 10;
  return (
    <span
      className={`relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full ${className}`}
      style={{
        width: size,
        height: size,
        background: `radial-gradient(circle at 50% 30%, ${ring}33, #07101a 72%)`,
        boxShadow: `inset 0 0 0 1.5px ${ring}, 0 0 0 2px #03070d, 0 0 12px ${ring}40`,
      }}
    >
      {src ? (
        <img
          src={scaledPhoto(src, w1 * 2)}
          srcSet={`${scaledPhoto(src, w1)} 1x, ${scaledPhoto(src, w1 * 2)} 2x`}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          // Zoom by sizing (not transform: scale, which upsamples a 44px raster and blurs it);
          // the box overflows the circle and centres sideways.
          className="max-w-none shrink-0 self-start object-cover"
          style={{
            width: size * fr.zoom,
            height: size * fr.zoom,
            marginTop: size * fr.top,
            objectPosition: `${(fr.posX * 100).toFixed(1)}% 0%`,
          }}
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
