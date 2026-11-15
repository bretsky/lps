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

// Champion square icons, hotlinked from Riot's Data Dragon. Pinned version: a champion
// released after it 404s (ChampionIcon falls back to its initial), so bump this when the
// data gains a new champion. 16.22.1 covers every champion in the data as of Nov 2026.
const DDRAGON_VERSION = "16.22.1";

// Display names (Oracle / Leaguepedia) whose Data Dragon id isn't just the name with
// punctuation and spaces stripped.
const CHAMPION_ID_EXCEPTIONS: Record<string, string> = {
  Wukong: "MonkeyKing",
  "Nunu & Willump": "Nunu",
  "Renata Glasc": "Renata",
  LeBlanc: "Leblanc",
  "Cho'Gath": "Chogath",
  "Kai'Sa": "Kaisa",
  "Kha'Zix": "Khazix",
  "Vel'Koz": "Velkoz",
  "Bel'Veth": "Belveth",
};

export function championIcon(name: string): string {
  const id = CHAMPION_ID_EXCEPTIONS[name] ?? name.replace(/[^A-Za-z0-9]/g, "");
  return `https://ddragon.leagueoflegends.com/cdn/${DDRAGON_VERSION}/img/champion/${id}.png`;
}
