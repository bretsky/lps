import type { Messages } from "./i18n/en";

export function fmt(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

export function fmtPct(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

export function fmtInt(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return Math.round(n).toString();
}

/** Lane name in the reader's language (`m` = useT()). */
export function laneLabel(m: Messages, lane: string | null | undefined): string {
  if (!lane) return "—";
  return m.lanes[lane as keyof Messages["lanes"]] ?? lane;
}

/** Player handle for display: drops the disambiguation suffix the pipeline adds to
 *  shared handles ("Knight (LPL)" -> "Knight", "Tatu (CBLOLA) #2" -> "Tatu").
 *  Keep using `playername` for keys, slugs and search. */
export function displayName(playername: string): string {
  let s = playername;
  for (let prev = ""; prev !== s; ) {
    prev = s;
    s = s.replace(/\s*(#\d+|\([^)]*\))\s*$/, "");
  }
  return s.trim() || playername;
}

/** The player's real name for the reader's language: their Hangul name on the Korean site and
 *  Chinese name on the Chinese site when Leaguepedia has one (export_web._local_names), else
 *  the romanized Players.Name. */
export function localRealName(
  p: { real_name?: string | null; name_ko?: string | null; name_zh?: string | null },
  locale: "en" | "ko" | "zh",
): string | null {
  return (locale === "ko" ? p.name_ko : locale === "zh" ? p.name_zh : null) || p.real_name || null;
}
