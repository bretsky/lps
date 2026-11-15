// The rankings frozen at the end of a past season: every career number (CLR, résumé,
// games, years) rebuilt from that season and earlier only. See export_web._write_asof.
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { RankingsPage } from "@/components/board/RankingsPage";
import { loadBoardPage, loadMeta } from "@/lib/data";

export const dynamicParams = false;

export async function generateStaticParams() {
  const meta = await loadMeta();
  return (meta.asof_years ?? []).map((y) => ({ year: String(y) }));
}

export async function generateMetadata({ params }: { params: Promise<{ year: string }> }): Promise<Metadata> {
  const { year } = await params;
  return { title: `CLR · All-Time Rankings as of ${year}` };
}

export default async function AsOfPage({ params }: { params: Promise<{ year: string }> }) {
  const { year: ys } = await params;
  const year = Number(ys);
  const meta = await loadMeta();
  if (!meta.asof_years?.includes(year)) notFound();
  const data = await loadBoardPage(year);
  return <RankingsPage data={data} meta={meta} asOf={year} />;
}
