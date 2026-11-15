// Groups the flat glossary (backend export_excel._GLOSSARY -> glossary.json) into the
// sections the /about page shows. Terms are matched by their exact glossary name; any
// term not listed here lands in "Other" so a new backend entry never silently vanishes.

import type { GlossaryJson } from "./types";

export type GlossaryEntry = GlossaryJson["entries"][number] & { id: string };

export interface GlossarySection {
  id: string;
  title: string;
  blurb: string;
  /** "cards" = full-width definitions; "table" = compact term/definition rows. */
  layout: "cards" | "table";
  entries: GlossaryEntry[];
}

type SectionSpec = Omit<GlossarySection, "entries"> & { terms: string[] };

const SECTIONS: SectionSpec[] = [
  {
    id: "clr",
    title: "Career Legend Rating",
    blurb: "The headline number: one score per career that counts bulk, pace, peak and hardware.",
    layout: "cards",
    terms: ["CLR", "CareerVal", "PaceVal", "PeakVal", "PeakYrs", "PeakAvg", "Resume"],
  },
  {
    id: "resume",
    title: "Résumé",
    blurb: "Big-stage results the box score can't see: placements, titles and awards. Every one has a fixed point value, listed in the tables below.",
    layout: "cards",
    terms: ["Intl", "Titles", "Awards", "Resume breakdown (# / Pt columns)"],
  },
  {
    id: "resume-categories",
    title: "Résumé categories",
    blurb: "The 14 categories a profile splits the résumé into, each with how many the player earned and the CLR points they add after repeat discounts.",
    layout: "table",
    terms: [
      "WldsChmp# / WldsChmpPt",
      "WldsFin# / WldsFinPt",
      "WldsElim# / WldsElimPt",
      "MSIChmp# / MSIChmpPt",
      "MSIFin# / MSIFinPt",
      "MSIElim# / MSIElimPt",
      "IntlChmp# / IntlChmpPt",
      "IntlFin# / IntlFinPt",
      "IntlElim# / IntlElimPt",
      "DomChmp# / DomChmpPt",
      "DomFin# / DomFinPt",
      "DomCup# / DomCupPt",
      "MVP# / MVPPt",
      "AllPro# / AllProPt",
    ],
  },
  {
    id: "lps",
    title: "Season score (LPS)",
    blurb: "How each season is scored from the games themselves, before it rolls up into CLR.",
    layout: "cards",
    terms: [
      "LPS",
      "LPS/Gm",
      "LPS/Gm·wt",
      "Con/Gm",
      "Con/Gm·wt",
      "Baseline",
      "Contribution",
      "WinBonus",
      "Kills/Deaths/Assists/Damage",
      "AvgContrib",
      "Intangibles",
      "Clutch",
      "Regular / Playoffs / Tourneys",
    ],
  },
  {
    id: "context",
    title: "Game context",
    blurb: "Supporting numbers that describe the games behind a season.",
    layout: "table",
    terms: ["AvgWinProb", "SoS", "BestGame / WorstGame", "#Trn", "RegElo", "<Tournament>"],
  },
  {
    id: "ranks",
    title: "Ranks & peers",
    blurb: "Where a player stands against the field, and where their value came from.",
    layout: "cards",
    terms: [
      "Rank",
      "BestRkLane / BestRkGlob",
      "HN3Lane / HN3Glob",
      "HN3LaneYrs / HN3GlobYrs",
      "Teams / Leagues / Lanes (by CLR)",
    ],
  },
];

/** URL-fragment id for a term, e.g. "LPS/Gm·wt" -> "lps-gm-wt", "#Trn" -> "trn". */
export function termId(term: string): string {
  return (
    term
      .toLowerCase()
      .replace(/%/g, " pct")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "term"
  );
}

/** Light typography for definitions written as plain ASCII for the workbook. */
export function tidy(text: string): string {
  return text.replace(/\s--\s/g, " — ").replace(/->/g, "→").replace(/\.\.(?=\w)/g, "–");
}

export function groupGlossary(glossary: GlossaryJson): GlossarySection[] {
  const seen = new Set<string>();
  const byTerm = new Map<string, GlossaryEntry>();
  for (const e of glossary.entries) {
    let id = termId(e.term);
    while (seen.has(id)) id += "-x";
    seen.add(id);
    byTerm.set(e.term, { ...e, id });
  }

  const used = new Set<string>();
  const sections: GlossarySection[] = SECTIONS.map(({ terms, ...s }) => {
    const entries = terms.flatMap((t) => {
      const e = byTerm.get(t);
      if (!e) return [];
      used.add(t);
      return [e];
    });
    return { ...s, entries };
  }).filter((s) => s.entries.length > 0);

  const rest = [...byTerm.values()].filter((e) => !used.has(e.term));
  if (rest.length) {
    sections.push({
      id: "other",
      title: "Other",
      blurb: "Everything else in the glossary.",
      layout: "table",
      entries: rest,
    });
  }
  return sections;
}
