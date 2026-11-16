"use client";

// Footer links to every board: today's role boards and each frozen past season. Readers
// mostly use the tabs and the season picker above the board, but those are scripted, so
// this plain list is also how search engines find those pages. Ends with a link to the
// author's homepage (brettselby.xyz), which links back here and to the pickems site.

import Link from "next/link";
import { useLocale, useT } from "@/lib/i18n";
import { LANES, boardPath } from "@/lib/site";

const linkCls = "text-text-dim hover:text-gold-bright";

export function SiteLinks({ years }: { years: number[] }) {
  const m = useT();
  const locale = useLocale(); // links go to the reader's language (prerendered: the page's)
  return (
    <nav className="mx-auto mt-6 max-w-3xl space-y-2 px-4 font-serif text-[10px] font-bold uppercase tracking-[0.22em]">
      <p className="flex flex-wrap justify-center gap-x-4 gap-y-1">
        <span className="text-gold">{m.footer.byRole}</span>
        {LANES.map((l) => (
          <Link key={l} href={boardPath(null, l, locale)} prefetch={false} className={linkCls}>
            {m.lanes[l]}
          </Link>
        ))}
      </p>
      {years.length > 0 && (
        <p className="flex flex-wrap justify-center gap-x-3 gap-y-1">
          <span className="text-gold">{m.footer.pastSeasons}</span>
          {years.map((y) => (
            <Link key={y} href={boardPath(y, "all", locale)} prefetch={false} className={`font-mono ${linkCls}`}>
              {y}
            </Link>
          ))}
        </p>
      )}
      <p className="flex justify-center pt-1">
        <a href="https://brettselby.xyz" className={`font-mono normal-case tracking-normal ${linkCls}`}>
          brettselby.xyz
        </a>
      </p>
    </nav>
  );
}
