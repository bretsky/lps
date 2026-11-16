import { notFound } from "next/navigation";
import { BoardRoute, boardMetadata } from "@/components/routes/BoardRoute";
import { loadMeta } from "@/lib/data";
import type { Locale } from "@/lib/i18n/config";

export const dynamicParams = false;

export async function generateStaticParams() {
  const meta = await loadMeta();
  return (meta.asof_years ?? []).map((y) => ({ year: String(y) }));
}

type Params = { params: Promise<{ lang: string; year: string }> };

export async function generateMetadata({ params }: Params) {
  const { lang, year } = await params;
  return boardMetadata(lang as Locale, Number(year), "all");
}

export default async function AsOfPage({ params }: Params) {
  const { lang, year } = await params;
  const meta = await loadMeta();
  if (!meta.asof_years?.includes(Number(year))) notFound();
  return <BoardRoute locale={lang as Locale} asOf={Number(year)} view="all" />;
}
