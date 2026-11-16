// Shared visual vocabulary: tier colours, medal metals, and the card "edition" a player is
// printed as. Tier names and other words are in lib/i18n. Keep TIER_COLORS in sync with `tier.*` in
// tailwind.config.ts.

import type { Messages } from "./i18n/en";
import type { PlayerDetail, TierKey } from "./types";

export const TIER_COLORS: Record<TierKey, string> = {
  goats: "#f1cf7c",
  legends: "#e8874f",
  greats: "#b28bff",
  elite: "#3fbfe8",
  stars: "#3fd29e",
  contenders: "#8b8e95",
};

export const GOLD = "#c9a45c";
export const GOLD_BRIGHT = "#f1d58f";
export const TEAL = "#1fd1c1";

/** Medal finishes as metal gradients (used as mask fills for event marks). */
export const MEDAL_METAL: Record<"gold" | "silver" | "bronze", string> = {
  gold: "linear-gradient(135deg, #8d672e 0%, #f6e2a8 35%, #c9a45c 60%, #fff1c4 80%, #a77d38 100%)",
  silver: "linear-gradient(135deg, #6f7680 0%, #f2f5f8 35%, #a9b1ba 60%, #ffffff 80%, #858d97 100%)",
  bronze: "linear-gradient(135deg, #5e3418 0%, #e6a170 35%, #a5602f 60%, #f3c09a 80%, #6d3d1d 100%)",
};

export const MEDAL_COLOR: Record<"gold" | "silver" | "bronze", string> = {
  gold: "#e9c77a",
  silver: "#c9d0d8",
  bronze: "#d18a55",
};

export interface Edition {
  kind: "hol" | "worlds" | "tier";
  tier: TierKey;
  color: string;
}

/** Card edition: Hall of Legends > World Champion > the player's tier. */
export function editionFor(p: PlayerDetail): Edition {
  const tier = p.tier ?? "contenders";
  if (p.hall_of_legends) return { kind: "hol", tier, color: GOLD_BRIGHT };
  if ((p.resume_breakdown?.wlds_title?.n ?? 0) > 0) return { kind: "worlds", tier, color: GOLD_BRIGHT };
  return { kind: "tier", tier, color: TIER_COLORS[tier] };
}

/** "Hall of Legends", "World Champion", "GOAT Edition", in the reader's language. */
export function editionLabel(m: Messages, e: Edition): string {
  return e.kind === "hol" ? m.edition.hol : e.kind === "worlds" ? m.edition.worlds : m.edition.tier(m.tiers[e.tier].one);
}

/** Team logo for the card corner: the team the photo was taken on, else the latest. */
export function cardTeamLogo(p: PlayerDetail): { name: string; logo: string } | null {
  const yt = p.year_teams ?? {};
  const photoTeam = p.photo_caption?.split(" · ")[0]?.toLowerCase();
  const years = Object.keys(yt).sort().reverse();
  if (photoTeam) {
    for (const y of years) {
      const hit = yt[y].find((t) => t.logo && t.name.toLowerCase() === photoTeam);
      if (hit?.logo) return { name: hit.name, logo: hit.logo };
    }
  }
  for (const y of years) {
    const hit = yt[y].find((t) => t.logo);
    if (hit?.logo) return { name: hit.name, logo: hit.logo };
  }
  return null;
}

/** "Lee Sang-hyeok" -> "LEE SANG-HYEOK"; null-safe. */
export function upper(s: string | null | undefined): string {
  return (s ?? "").toUpperCase();
}
