// The rankings boards in every language: today (`/`), a role (`/role/<x>`) or a frozen past
// season (`/asof/<year>`), each also under /ko and /zh. The app/ routes are thin wrappers.
import type { Metadata } from "next";
import { RankingsPage } from "@/components/board/RankingsPage";
import { JsonLd } from "@/components/JsonLd";
import type { BoardView } from "@/lib/board";
import { loadBoardPage, loadMeta } from "@/lib/data";
import type { Locale } from "@/lib/i18n/config";
import { SEO } from "@/lib/i18n/seo";
import { absUrl, boardItemList, pageMeta, topFive } from "@/lib/seo";
import { ROLE_SLUGS, SITE_NAME, localePath } from "@/lib/site";

const boardUrlPath = (asOf: number | null, view: BoardView) =>
  asOf !== null ? `/asof/${asOf}` : view === "all" ? "/" : `/role/${ROLE_SLUGS[view]}`;

const fmt = (n: number, locale: Locale) => n.toLocaleString(locale === "en" ? "en-US" : locale === "ko" ? "ko-KR" : "zh-CN");

function boardTitle(locale: Locale, asOf: number | null, view: BoardView): string {
  const s = SEO[locale];
  return asOf !== null ? s.asof(asOf) : view === "all" ? s.home : s.role(view);
}

export async function boardMetadata(locale: Locale, asOf: number | null, view: BoardView): Promise<Metadata> {
  const [data, meta] = await Promise.all([loadBoardPage(asOf, view), loadMeta()]);
  const s = SEO[locale];
  const top = topFive(data.rows, locale);
  const [y0, y1] = meta.years;
  const description =
    asOf !== null
      ? s.asofDesc(asOf, top)
      : view === "all"
        ? s.homeDesc(fmt(data.ratedCount, locale), y0, y1, top)
        : s.roleDesc(view, fmt(data.summaries[view].total, locale), y0, y1, top);
  return pageMeta({
    title: boardTitle(locale, asOf, view),
    description,
    path: boardUrlPath(asOf, view),
    locale,
    localized: true,
  });
}

export async function BoardRoute({ locale, asOf, view }: { locale: Locale; asOf: number | null; view: BoardView }) {
  const [data, meta] = await Promise.all([loadBoardPage(asOf, view), loadMeta()]);
  const path = localePath(locale, boardUrlPath(asOf, view));
  return (
    <>
      {asOf === null && view === "all" && (
        <JsonLd
          data={{
            "@context": "https://schema.org",
            "@type": "WebSite",
            name: SITE_NAME,
            alternateName: "CLR",
            url: absUrl(path),
            inLanguage: locale === "zh" ? "zh-CN" : locale,
          }}
        />
      )}
      <JsonLd data={boardItemList(boardTitle(locale, asOf, view), path, data.rows)} />
      <RankingsPage data={data} meta={meta} asOf={asOf} view={view} />
    </>
  );
}
