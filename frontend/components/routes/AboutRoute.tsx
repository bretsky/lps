// /about and /ko/about, /zh/about: what every number on the site means, straight from
// glossary.json (backend export_excel._GLOSSARY), grouped by lib/glossary.ts. Each term has a
// stable anchor, so other pages can deep-link to /about#<termId(term)>. The body is a client
// component (components/about/AboutBody) so it follows the page's / reader's language.
import type { Metadata } from "next";
import { loadGlossary, loadMeta } from "@/lib/data";
import { groupGlossary } from "@/lib/glossary";
import type { Locale } from "@/lib/i18n/config";
import { SEO } from "@/lib/i18n/seo";
import { pageMeta } from "@/lib/seo";
import type { Meta } from "@/lib/types";
import { AboutBody } from "@/components/about/AboutBody";
import { LanguageSwitcher } from "@/components/i18n/LanguageSwitcher";
import { DocTitle, T } from "@/components/i18n/T";
import { LocalizedLink } from "@/components/i18n/LocalizedLink";

export function aboutMetadata(locale: Locale): Metadata {
  return pageMeta({ title: SEO[locale].about, description: SEO[locale].aboutDesc, path: "/about", locale, localized: true });
}

const WEIGHT_KEY = "Weights (w_career, w_pace, w_peak, w_bonus)";

/** The four CLR weights from the workbook's About sheet, or null if the row is missing. */
function clrWeights(meta: Meta): number[] | null {
  const raw = meta.about?.[WEIGHT_KEY];
  if (typeof raw !== "string") return null;
  const nums = raw
    .split("(")[0]
    .split(",")
    .map((s) => Number(s.trim()));
  return nums.length === 4 && nums.every(Number.isFinite) ? nums : null;
}

export async function AboutRoute() {
  const [glossary, meta] = await Promise.all([loadGlossary(), loadMeta()]);

  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      <DocTitle k="about" />
      <nav className="mb-6 flex items-center justify-between gap-4 font-serif text-[11px] font-bold uppercase tracking-[0.25em]">
        <LocalizedLink path="/" className="text-text-dim hover:text-gold-bright">
          ◂ <T k="nav.rankings" />
        </LocalizedLink>
        <LanguageSwitcher />
      </nav>

      <AboutBody
        sections={groupGlossary(glossary)}
        resumeScoring={glossary.resume_scoring ?? null}
        weights={clrWeights(meta)}
        years={[meta.years[0], meta.years[1]]}
        ratedMinGames={meta.rated_min_games}
        buildId={meta.build_id}
        boardYears={[...(meta.asof_years ?? [])].sort((a, b) => b - a)}
      />
    </main>
  );
}
