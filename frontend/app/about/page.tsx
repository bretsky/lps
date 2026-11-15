// About / glossary: what every number on the site means, straight from glossary.json
// (backend export_excel._GLOSSARY), grouped by lib/glossary.ts. Each term has a stable
// anchor, so other pages can deep-link to /about#<termId(term)>.
import type { Metadata } from "next";
import Link from "next/link";
import { loadGlossary, loadMeta } from "@/lib/data";
import { groupGlossary, tidy, type GlossarySection } from "@/lib/glossary";
import type { Meta } from "@/lib/types";

export const metadata: Metadata = {
  title: "About · LPS",
  description: "How LPS and the Career Legend Rating are built, and what every column on the site means.",
};

const WEIGHT_KEY = "Weights (w_career, w_pace, w_peak, w_bonus)";
const WEIGHT_LABELS = ["Career", "Pace", "Peak", "Résumé"];

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

function Section({ s }: { s: GlossarySection }) {
  return (
    <section id={s.id} className="deco-panel scroll-mt-6">
      <h2 className="deco-title">{s.title}</h2>
      <p className="mt-1.5 text-sm text-text-muted">{s.blurb}</p>

      {s.layout === "cards" ? (
        <dl className="mt-4 grid gap-3 md:grid-cols-2">
          {s.entries.map((e) => (
            <div
              key={e.id}
              id={e.id}
              className="group min-w-0 scroll-mt-6 border-l-2 border-gold-deep/70 bg-bg-card/60 px-4 py-3 target:border-teal target:bg-teal-deep/20"
            >
              <dt className="flex items-baseline justify-between gap-3">
                <span className="min-w-0 font-display text-xl font-bold uppercase tracking-wide text-gold-bright [overflow-wrap:anywhere]">
                  {e.term}
                </span>
                <a
                  href={`#${e.id}`}
                  className="font-mono text-xs text-text-dim opacity-0 transition-opacity hover:text-teal group-hover:opacity-100"
                  aria-label={`Link to ${e.term}`}
                >
                  #
                </a>
              </dt>
              <dd className="mt-1 text-[14px] leading-relaxed text-text [overflow-wrap:anywhere]">{tidy(e.definition)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <dl className="mt-4 divide-y divide-border">
          {s.entries.map((e) => (
            <div
              key={e.id}
              id={e.id}
              className="scroll-mt-6 grid gap-1 py-2.5 sm:grid-cols-[minmax(0,15rem)_1fr] sm:gap-4 target:bg-teal-deep/20"
            >
              <dt className="break-words font-mono text-[13px] font-medium text-gold-bright">{e.term}</dt>
              <dd className="min-w-0 text-[14px] leading-relaxed text-text [overflow-wrap:anywhere]">{tidy(e.definition)}</dd>
            </div>
          ))}
        </dl>
      )}
    </section>
  );
}

export default async function AboutPage() {
  const [glossary, meta] = await Promise.all([loadGlossary(), loadMeta()]);
  const sections = groupGlossary(glossary);
  const weights = clrWeights(meta);

  return (
    <main className="mx-auto max-w-6xl px-4 py-6">
      <nav className="mb-6 font-serif text-[11px] font-bold uppercase tracking-[0.25em]">
        <Link href="/" className="text-text-dim hover:text-gold-bright">
          ◂ All-time rankings
        </Link>
      </nav>

      <header className="text-center">
        <div className="deco-rule mx-auto max-w-md font-serif text-[11px] font-bold uppercase tracking-[0.45em] text-gold">
          <span>How it works</span>
        </div>
        <h1 className="mt-3 font-display text-[48px] font-black uppercase leading-[0.9] tracking-[0.02em] sm:text-[72px]">
          <span className="text-metal">About</span>{" "}
          <span className="font-serif text-[0.6em] font-semibold tracking-[0.12em] text-text">LPS</span>
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-[15px] leading-relaxed text-text-muted">
          LPS (League Performance Score) measures how much each player moved their team&apos;s chances of winning,
          game by game, against what an average player would have done in the same spot. Seasons are scored on their
          own, then rolled up into the <span className="text-gold-bright">Career Legend Rating</span>, which also
          counts titles, placements and awards.
        </p>
      </header>

      {/* current settings */}
      <div className="mx-auto mt-6 grid max-w-4xl grid-cols-2 gap-3 sm:grid-cols-4">
        {weights ? (
          weights.map((w, i) => (
            <div key={WEIGHT_LABELS[i]} className="deco-control px-3 py-2 text-center">
              <div className="font-serif text-[10px] font-bold uppercase tracking-[0.22em] text-text-muted">
                {WEIGHT_LABELS[i]} weight
              </div>
              <div className="font-display text-2xl font-black text-gold-bright">×{w}</div>
            </div>
          ))
        ) : null}
      </div>
      <p className="mt-3 text-center font-serif text-[10px] font-bold uppercase tracking-[0.25em] text-text-dim">
        Seasons {meta.years[0]}–{meta.years[1]} <span className="text-teal">◆</span> rated at {meta.rated_min_games}+
        games <span className="text-teal">◆</span> build {meta.build_id}
      </p>

      {/* contents */}
      <nav aria-label="Sections" className="mt-8 flex flex-wrap justify-center gap-2">
        {sections.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            className="deco-control px-3 py-1.5 font-serif text-[11px] font-bold uppercase tracking-[0.16em] text-text-muted hover:text-gold-bright"
          >
            {s.title}
          </a>
        ))}
      </nav>

      <div className="mt-6 space-y-6">
        {sections.map((s) => (
          <Section key={s.id} s={s} />
        ))}
      </div>

      <footer className="mt-10 border-t border-gold-deep/40 py-8 text-center">
        <p className="text-[11px] text-text-dim">
          Not endorsed by Riot Games · Data and photos from Oracle&apos;s Elixir and Leaguepedia · League marks © their
          owners
        </p>
      </footer>
    </main>
  );
}
