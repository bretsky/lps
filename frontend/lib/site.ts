// Site-wide constants for search engines and link previews: the production origin (every
// canonical URL, the sitemap and og:image URLs are absolute against it) and the role-board
// URL slugs. No `fs` here, so client components can import it.

import type { Lane } from "./types";
import type { Locale } from "./i18n/config";

/** Production origin, no trailing slash. Override with NEXT_PUBLIC_SITE_URL when the domain moves. */
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "https://clr.brettselby.xyz").replace(/\/+$/, "");

export const SITE_NAME = "CLR · League of Legends All-Time Rankings";

/** URL slug of each role board (`/role/<slug>`), in the words people search with. */
export const ROLE_SLUGS: Record<Lane, string> = { top: "top", jng: "jungle", mid: "mid", bot: "adc", sup: "support" };
export const LANES: Lane[] = ["top", "jng", "mid", "bot", "sup"];
export const laneFromSlug = (s: string): Lane | null =>
  (LANES.find((l) => ROLE_SLUGS[l] === s) as Lane | undefined) ?? null;

/** Path of a board: today's all-roles board, a role board, or a frozen past season (`?lane=`),
 *  under /ko or /zh when `locale` is one of those. */
export function boardPath(asOf: number | null, lane: Lane | "all", locale: Locale | null = null): string {
  if (asOf !== null) return localePath(locale, `/asof/${asOf}`) + (lane === "all" ? "" : `?lane=${lane}`);
  return localePath(locale, lane === "all" ? "/" : `/role/${ROLE_SLUGS[lane]}`);
}

/** Languages with their own URLs (/ko/..., /zh/...); English pages are unprefixed. */
export const URL_LOCALES = ["ko", "zh"] as const satisfies readonly Locale[];

/** `path` (unprefixed, "/" for home) in `locale`'s URL space. */
export function localePath(locale: Locale | null, path: string): string {
  if (!locale || locale === "en") return path;
  return `/${locale}${path === "/" ? "" : path}`;
}

/** Split a pathname into its URL language and the unprefixed path ("/ko/role/mid" -> ko, "/role/mid"). */
export function splitLocalePath(pathname: string): { locale: Locale | null; path: string } {
  const m = pathname.match(/^\/(ko|zh)(\/.*)?$/);
  return m ? { locale: m[1] as Locale, path: m[2] || "/" } : { locale: null, path: pathname };
}

/** Pages that exist in every language: the boards, About and profiles (cards are English-only
 *  URLs, translated in the browser). */
export const hasLocalizedPages = (path: string) => /^\/($|role\/[a-z]+\/?$|about\/?$|player\/[a-z0-9-]+\/?$|asof\/\d+\/?$)/.test(path);

/** English plural role names as they appear in search queries ("greatest ADCs of all time"). */
export const ROLE_PLURAL: Record<Lane, string> = {
  top: "Top Laners",
  jng: "Junglers",
  mid: "Mid Laners",
  bot: "ADCs",
  sup: "Supports",
};
/** The same mid-sentence ("among mid laners", "among ADCs"). */
export const rolePluralLower = (l: Lane) => (l === "bot" ? ROLE_PLURAL[l] : ROLE_PLURAL[l].toLowerCase());
export const ROLE_SINGULAR: Record<Lane, string> = {
  top: "top laner",
  jng: "jungler",
  mid: "mid laner",
  bot: "ADC",
  sup: "support",
};

/** Share-image URLs (prerendered PNGs, see app/og/). */
export const ogPlayerImage = (slug: string) => `/og/player/${slug}.png`;
export const OG_SITE_IMAGE = "/og/site.png";
export const OG_SIZE = { width: 1200, height: 630 };
