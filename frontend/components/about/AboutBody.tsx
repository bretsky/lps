"use client";

// The /about page body. A client component so every heading, the résumé tables and the
// backend-translated glossary text (entries' `i18n`) follow the reader's language.
import { SiteLinks } from "@/components/SiteLinks";
import { Fragment } from "react";
import { tidy, type GlossaryEntry, type GlossarySection } from "@/lib/glossary";
import { localized, useLocale, useT, type Locale, type Messages } from "@/lib/i18n";
import type { ResumeScoring } from "@/lib/types";

/** A point value for the tables: up to three decimals, trailing zeros dropped (0.375, 3, 0.12). */
function pts(x: number): string {
  return String(Number(x.toFixed(3)));
}

const TH = "px-2 py-1.5 font-serif text-[10px] font-bold uppercase tracking-[0.16em] text-text-muted";
const TD = "px-2 py-1.5 text-right tabular-nums";
const H3 = "font-display text-lg font-bold uppercase tracking-wide text-gold-bright";

const PART_KEYS = ["career", "pace", "peak", "resume"] as const;

type SectionId = keyof Messages["about"]["sections"];
function sectionTitle(m: Messages, s: { id: string; title: string }): string {
  return m.about.sections[s.id as SectionId]?.title ?? s.title;
}

/** The résumé's point tables: every number is what that achievement adds to CLR. */
function ResumeTables({ rs }: { rs: ResumeScoring }) {
  const m = useT();
  const locale = useLocale();
  const t = m.about.rs;
  const intl = rs.events.filter((e) => e.kind === "intl");
  const cups = rs.events.filter((e) => e.kind === "cup");
  const round = (r: ResumeScoring["rounds"][number]) => localized(r.label, r.i18n, locale);
  const eventRows = (rows: ResumeScoring["events"]) =>
    rows.map((e) => (
      <tr key={e.code} className="border-t border-border">
        <td className="px-2 py-1.5 text-left text-text">{localized(e.name, e.i18n, locale)}</td>
        <td className={`${TD} text-text-muted`}>{e.anchored ? t.set : pts(e.tournament_weight)}</td>
        {rs.rounds.map((r) => (
          <td key={r.key} className={`${TD} ${r.key === "champion" ? "font-semibold text-gold-bright" : "text-text"}`}>
            {pts(e.points[r.key])}
          </td>
        ))}
      </tr>
    ));
  const steps = rs.example.steps;

  return (
    <section id="resume-points" className="deco-panel scroll-mt-6">
      <h2 className="deco-title">{t.title}</h2>
      <p className="mt-1.5 text-sm text-text-muted">{t.intro(pts(rs.weight))}</p>

      <div className="mt-4 space-y-6 text-[14px] leading-relaxed">
        <div>
          <h3 className={H3}>{t.intlTitle}</h3>
          <p className="mt-1 text-text">
            {t.intlBody(
              pts(rs.champ_per_weight * rs.weight),
              rs.rounds
                .filter((r) => r.key !== "champion")
                .map((r) => [round(r), String(Math.round(r.share * 1000) / 10)] as [string, string]),
            )}
          </p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse text-[13px]">
              <thead>
                <tr>
                  <th className={`${TH} text-left`}>{t.event}</th>
                  <th className={`${TH} text-right`}>{t.weight}</th>
                  {rs.rounds.map((r) => (
                    <th key={r.key} className={`${TH} text-right`}>
                      {round(r)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {eventRows(intl)}
                {cups.length ? (
                  <tr className="border-t border-border">
                    <td
                      colSpan={2 + rs.rounds.length}
                      className="px-2 pb-1 pt-3 text-left font-serif text-[10px] font-bold uppercase tracking-[0.16em] text-text-muted"
                    >
                      {t.cupsRow}
                    </td>
                  </tr>
                ) : null}
                {eventRows(cups)}
              </tbody>
            </table>
          </div>
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          <div className="min-w-0">
            <h3 className={H3}>{t.domTitle}</h3>
            <p className="mt-1 text-text">
              {t.domBody(pts(rs.domestic.champion), pts(rs.domestic.finalist), rs.domestic.year)}
            </p>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full border-collapse text-[13px]">
                <thead>
                  <tr>
                    <th className={`${TH} text-left`}>{t.league}</th>
                    <th className={`${TH} text-right`}>{t.strength}</th>
                    <th className={`${TH} text-right`}>{t.titleCol}</th>
                    <th className={`${TH} text-right`}>{t.runnerUp}</th>
                  </tr>
                </thead>
                <tbody>
                  {rs.domestic.leagues.map((l) => (
                    <tr key={l.league} className="border-t border-border">
                      <td className="px-2 py-1.5 text-left text-text">{l.league}</td>
                      <td className={`${TD} text-text-muted`}>{Math.round(l.strength * 100)}%</td>
                      <td className={`${TD} font-semibold text-gold-bright`}>{pts(l.champion)}</td>
                      <td className={`${TD} text-text`}>{pts(l.finalist)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="min-w-0">
            <h3 className={H3}>{t.awardsTitle}</h3>
            <p className="mt-1 text-text">{t.awardsBody}</p>
            <div className="mt-3 overflow-x-auto">
              <table className="w-full border-collapse text-[13px]">
                <thead>
                  <tr>
                    <th className={`${TH} text-left`}>{t.award}</th>
                    <th className={`${TH} text-right`}>{t.points}</th>
                  </tr>
                </thead>
                <tbody>
                  {rs.awards.map((a) => (
                    <tr key={a.key} className="border-t border-border">
                      <td className="px-2 py-1.5 text-left text-text">
                        {localized(a.label, a.i18n, locale)}
                        {a.scaled ? <span className="text-text-muted"> *</span> : null}
                      </td>
                      <td className={`${TD} text-gold-bright`}>{pts(a.points)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div>
          <h3 className={H3}>{t.repeatsTitle}</h3>
          <p className="mt-1 text-text">
            {t.repeatsBody(
              Math.round(rs.repeat_decay * 100),
              localized(rs.example.label, rs.example.i18n, locale),
              steps.map(pts),
              <span className="font-semibold text-gold-bright">{pts(rs.example.total)}</span>,
              pts(steps[0] * steps.length),
            )}
          </p>
        </div>
      </div>
    </section>
  );
}

function entryText(e: GlossaryEntry, locale: Locale) {
  const tr = locale !== "en" ? e.i18n?.[locale] : undefined;
  return { label: tr?.label || e.label || e.term, definition: tr?.definition || e.definition };
}

function Section({ s }: { s: GlossarySection }) {
  const m = useT();
  const locale = useLocale();
  const id = s.id as SectionId;
  const blurb = m.about.sections[id]?.blurb ?? s.blurb;

  return (
    <section id={s.id} className="deco-panel scroll-mt-6">
      <h2 className="deco-title">{sectionTitle(m, s)}</h2>
      <p className="mt-1.5 text-sm text-text-muted">{blurb}</p>

      {s.layout === "cards" ? (
        <dl className="mt-4 grid gap-3 md:grid-cols-2">
          {s.entries.map((e) => {
            const { label, definition } = entryText(e, locale);
            return (
              <div
                key={e.id}
                id={e.id}
                className="group min-w-0 scroll-mt-6 border-l-2 border-gold-deep/70 bg-bg-card/60 px-4 py-3 target:border-teal target:bg-teal-deep/20"
              >
                <dt className="flex items-baseline justify-between gap-3">
                  <span className="min-w-0 font-display text-xl font-bold uppercase tracking-wide text-gold-bright">
                    {label}
                  </span>
                  <a
                    href={`#${e.id}`}
                    className="font-mono text-xs text-text-dim opacity-0 transition-opacity hover:text-teal group-hover:opacity-100"
                    aria-label={m.about.linkTo(label)}
                  >
                    #
                  </a>
                </dt>
                <dd className="mt-1 text-[14px] leading-relaxed text-text [overflow-wrap:anywhere]">{tidy(definition)}</dd>
              </div>
            );
          })}
        </dl>
      ) : (
        <dl className="mt-4 divide-y divide-border">
          {s.entries.map((e) => {
            const { label, definition } = entryText(e, locale);
            return (
              <div
                key={e.id}
                id={e.id}
                className="scroll-mt-6 grid gap-1 py-2.5 sm:grid-cols-[minmax(0,15rem)_1fr] sm:gap-4 target:bg-teal-deep/20"
              >
                <dt className="break-words text-[14px] font-semibold text-gold-bright">{label}</dt>
                <dd className="min-w-0 text-[14px] leading-relaxed text-text [overflow-wrap:anywhere]">{tidy(definition)}</dd>
              </div>
            );
          })}
        </dl>
      )}
    </section>
  );
}

export function AboutBody({
  sections,
  resumeScoring,
  weights,
  years,
  ratedMinGames,
  buildId,
  boardYears = [],
}: {
  sections: GlossarySection[];
  resumeScoring: ResumeScoring | null;
  weights: number[] | null;
  years: [number, number];
  ratedMinGames: number;
  buildId: string;
  boardYears?: number[];   // seasons with a frozen past-year board, newest first (footer links)
}) {
  const m = useT();
  const a = m.about;
  const sep = <span className="text-teal">◆</span>;

  return (
    <>
      <header className="text-center">
        <div className="deco-rule mx-auto max-w-md font-serif text-[11px] font-bold uppercase tracking-[0.45em] text-gold">
          <span>{a.kicker}</span>
        </div>
        <h1 className="mt-3 font-display text-[48px] font-black uppercase leading-[0.9] tracking-[0.02em] sm:text-[72px]">
          <span className="text-metal">{a.titleA}</span>{" "}
          <span className="font-serif text-[0.6em] font-semibold tracking-[0.12em] text-text">{a.titleB}</span>
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-[15px] leading-relaxed text-text-muted">
          {a.intro((s) => (
            <span className="text-gold-bright">{s}</span>
          ))}
        </p>
      </header>

      {/* current settings */}
      <div className="mx-auto mt-6 grid max-w-4xl grid-cols-2 gap-3 sm:grid-cols-4">
        {weights
          ? weights.map((w, i) => (
              <div key={PART_KEYS[i]} className="deco-control px-3 py-2 text-center">
                <div className="font-serif text-[10px] font-bold uppercase tracking-[0.22em] text-text-muted">
                  {a.weight(m.parts[PART_KEYS[i]])}
                </div>
                <div className="font-display text-2xl font-black text-gold-bright">×{w}</div>
              </div>
            ))
          : null}
      </div>
      <p className="mt-3 text-center font-serif text-[10px] font-bold uppercase tracking-[0.25em] text-text-dim">
        {a.settings(years[0], years[1], ratedMinGames, buildId, sep)}
      </p>

      {/* contents */}
      <nav aria-label={a.sectionsAria} className="mt-8 flex flex-wrap justify-center gap-2">
        {sections
          .flatMap((s) =>
            s.id === "resume" && resumeScoring
              ? [{ id: s.id, title: sectionTitle(m, s) }, { id: "resume-points", title: a.resumePointsNav }]
              : [{ id: s.id, title: sectionTitle(m, s) }],
          )
          .map((s) => (
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
          <Fragment key={s.id}>
            <Section s={s} />
            {s.id === "resume" && resumeScoring ? <ResumeTables rs={resumeScoring} /> : null}
          </Fragment>
        ))}
      </div>

      <footer className="mt-10 border-t border-gold-deep/40 py-8 text-center">
        <SiteLinks years={boardYears} />
        <p className="mt-4 text-[11px] text-text-dim">{m.footer.disclaimer}</p>
      </footer>
    </>
  );
}
