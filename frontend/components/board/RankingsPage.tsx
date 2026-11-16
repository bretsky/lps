"use client";

import Link from "next/link";
import { useT } from "@/lib/i18n";
import { DocTitle } from "@/components/i18n/T";
import Board from "@/components/board/Board";
import { Hero } from "@/components/board/Hero";
import type { BoardData } from "@/lib/data";
import type { Meta } from "@/lib/types";

/** The rankings page body, shared by today's board (`/`) and the frozen past-year
 *  boards (`/asof/<year>`). `asOf` = the season the board is frozen at, null for today. */
export function RankingsPage({ data, meta, asOf }: { data: BoardData; meta: Meta; asOf: number | null }) {
  const m = useT();
  const years = [...(meta.asof_years ?? [])].sort((a, b) => b - a);
  return (
    <main>
      {asOf === null ? <DocTitle k="home" /> : <DocTitle k="asof" args={[asOf]} />}
      {asOf !== null && (
        <div className="border-b border-teal/40 bg-black/70 px-4 py-1.5 text-center font-serif text-[10px] font-bold uppercase tracking-[0.3em] text-teal">
          {m.frozen(
            asOf,
            <span className="text-gold">◆</span>,
            <Link href="/" className="text-gold underline-offset-4 hover:text-gold-bright hover:underline">
              {m.backToToday}
            </Link>,
          )}
        </div>
      )}
      <Hero rows={data.rows} asOf={asOf} />
      <Board
        key={asOf ?? "today"}
        initialRows={data.rows}
        summaries={data.summaries}
        tiers={data.tiers}
        asOf={asOf}
        years={years}
        latestYear={meta.years[1]}
        prevYear={data.prevYear}
      />
      <footer className="border-t border-gold-deep/40 py-8 text-center">
        <div className="deco-rule mx-auto mb-3 max-w-xs">
          <span className="h-2 w-2 rotate-45 bg-gold" />
        </div>
        <p className="font-serif text-[10px] font-bold uppercase tracking-[0.3em] text-text-dim">
          {m.footer.build(meta.build_id, data.ratedCount, asOf, data.ratedMinGames)}
        </p>
        <p className="mt-2">
          <Link
            href="/about"
            className="font-serif text-[10px] font-bold uppercase tracking-[0.3em] text-gold hover:text-gold-bright"
          >
            {m.footer.aboutLink}
          </Link>
        </p>
        <p className="mt-1 text-[11px] text-text-dim">{m.footer.disclaimer}</p>
      </footer>
    </main>
  );
}
