// Official event + league marks bundled under public/icons/ (built by
// backend/analysis/fetch_brand_icons.py from the LoL Esports CDN, Leaguepedia and Commons).

import type { HonorKind } from "./types";

export type EventKey = "worlds" | "msi" | "first_stand" | "ewc";

export const EVENT_ICON: Record<EventKey, string> = {
  worlds: "/icons/events/worlds.png",
  msi: "/icons/events/msi.png",
  first_stand: "/icons/events/first-stand.png",
  ewc: "/icons/events/ewc.png",
};

/** Honor kinds drawn with an official event mark (vs a cup silhouette / league logo). */
export function isEventKind(kind: HonorKind): kind is EventKey {
  return kind in EVENT_ICON;
}

export const EVENT_LABEL: Record<HonorKind, string> = {
  worlds: "Worlds",
  msi: "MSI",
  first_stand: "First Stand",
  ewc: "Esports World Cup",
  intl: "International",
  domestic: "League",
  cup: "Cup",
};

// League short names as they appear in the data (Oracle `league`, achievements
// `league` keys) -> bundled icon file. `invert` marks dark-on-transparent logos
// that need flipping to read on the site's dark surfaces.
const LEAGUE_FILES: Record<string, { file: string; invert?: boolean }> = {
  LCK: { file: "lck" },
  OGN: { file: "lck" },
  KR: { file: "lck" },
  LPL: { file: "lpl" },
  CN: { file: "lpl" },
  LEC: { file: "lec" },
  "EU LCS": { file: "eu-lcs" },
  EU: { file: "eu-lcs" },
  LCS: { file: "lcs" },
  "NA LCS": { file: "na-lcs" },
  NA: { file: "na-lcs" },
  CBLOL: { file: "cblol" },
  LMS: { file: "lms" },
  OPL: { file: "opl" },
  TCL: { file: "tcl" },
  LTA: { file: "lta" },
  "LTA N": { file: "lta-n" },
  "LTA S": { file: "lta-s" },
  LCP: { file: "lcp" },
  LCO: { file: "lco" },
  PCS: { file: "pcs", invert: true },
};

export function leagueIcon(league: string | null | undefined): { src: string; invert: boolean } | null {
  if (!league) return null;
  const hit = LEAGUE_FILES[league] ?? LEAGUE_FILES[league.toUpperCase()];
  return hit ? { src: `/icons/leagues/${hit.file}.png`, invert: !!hit.invert } : null;
}
