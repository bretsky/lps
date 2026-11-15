export const LANE_LABELS: Record<string, string> = {
  top: "Top",
  jng: "Jungle",
  mid: "Mid",
  bot: "Bot",
  sup: "Support",
};

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

export function laneLabel(lane: string | null | undefined): string {
  if (!lane) return "—";
  return LANE_LABELS[lane] ?? lane;
}

export function yearsLabel(first: number, last: number, n: number): string {
  if (first === last) return `${first} · ${n}yr`;
  return `${first}–${last} · ${n}yr`;
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
