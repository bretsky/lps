// The rankings frozen at the end of a past season: every career number (CLR, résumé,
// games, years) rebuilt from that season and earlier only. See export_web._write_asof.
import { notFound } from "next/navigation";
import { BoardRoute, boardMetadata } from "@/components/routes/BoardRoute";
import { loadMeta } from "@/lib/data";

export const dynamicParams = false;

export async function generateStaticParams() {
  const meta = await loadMeta();
  return (meta.asof_years ?? []).map((y) => ({ year: String(y) }));
}

export async function generateMetadata({ params }: { params: Promise<{ year: string }> }) {
  return boardMetadata("en", Number((await params).year), "all");
}

export default async function AsOfPage({ params }: { params: Promise<{ year: string }> }) {
  const year = Number((await params).year);
  const meta = await loadMeta();
  if (!meta.asof_years?.includes(year)) notFound();
  return <BoardRoute locale="en" asOf={year} view="all" />;
}
