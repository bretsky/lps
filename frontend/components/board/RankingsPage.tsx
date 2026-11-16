"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { useLocale, useT } from "@/lib/i18n";
import { DocTitle } from "@/components/i18n/T";
import Board from "@/components/board/Board";
import { Hero } from "@/components/board/Hero";
import { SiteLinks } from "@/components/SiteLinks";
import { localePath } from "@/lib/site";
import type { BoardData } from "@/lib/data";
import type { BoardView } from "@/lib/board";
import type { IndexRow, Meta } from "@/lib/types";

/** The rankings page body, shared by today's board (`/`), its role boards (`/role/<x>`) and
 *  the frozen past-year boards (`/asof/<year>`). `asOf` = the season the board is frozen at,
 *  null for today; `view` = the role tab the page was built for. */
export function RankingsPage({
  data, meta, asOf, view = "all",
}: { data: BoardData; meta: Meta; asOf: number | null; view?: BoardView }) {
  const m = useT();
  const locale = useLocale(); // links go to the reader's language (prerendered: the page's)
  const years = [...(meta.asof_years ?? [])].sort((a, b) => b - a);
  // The role tab, shared by the board and the hero (whose top five follow it once that
  // role's list has loaded; until then it keeps the last top five it had).
  const [lane, setLane] = useState<BoardView>(view);
  const [tops, setTops] = useState<Partial<Record<BoardView, IndexRow[]>>>({ [view]: data.rows.slice(0, 5) });
  const onViewRows = useCallback(
    (v: BoardView, rows: IndexRow[]) => setTops((t) => (t[v] ? t : { ...t, [v]: rows.slice(0, 5) })),
    [],
  );
  const [heroLane, setHeroLane] = useState<BoardView>(view);
  if (tops[lane] && heroLane !== lane) setHeroLane(lane);
  return (
    <main>
      {asOf !== null ? (
        <DocTitle k="asof" args={[asOf]} />
      ) : lane === "all" ? (
        <DocTitle k="home" />
      ) : (
        <DocTitle k="role" args={[lane]} />
      )}
      {asOf !== null && (
        <div className="border-b border-teal/40 bg-black/70 px-4 py-1.5 text-center font-serif text-[10px] font-bold uppercase tracking-[0.3em] text-teal">
          {m.frozen(
            asOf,
            <span className="text-gold">◆</span>,
            <Link href={localePath(locale, "/")} className="text-gold underline-offset-4 hover:text-gold-bright hover:underline">
              {m.backToToday}
            </Link>,
          )}
        </div>
      )}
      <Hero rows={tops[heroLane] ?? data.rows} asOf={asOf} lane={heroLane} />
      <Board
        key={asOf ?? "today"}
        initialRows={data.rows}
        initialView={view}
        lane={lane}
        onLane={setLane}
        onViewRows={onViewRows}
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
            href={localePath(locale, "/about")}
            className="font-serif text-[10px] font-bold uppercase tracking-[0.3em] text-gold hover:text-gold-bright"
          >
            {m.footer.aboutLink}
          </Link>
        </p>
        <SiteLinks years={years} />
        <p className="mt-4 text-[11px] text-text-dim">{m.footer.disclaimer}</p>
      </footer>
    </main>
  );
}
