import { notFound } from "next/navigation";
import { BoardRoute, boardMetadata } from "@/components/routes/BoardRoute";
import type { Locale } from "@/lib/i18n/config";
import { LANES, ROLE_SLUGS, laneFromSlug } from "@/lib/site";

export const dynamicParams = false;

export function generateStaticParams() {
  return LANES.map((l) => ({ role: ROLE_SLUGS[l] }));
}

type Params = { params: Promise<{ lang: string; role: string }> };

export async function generateMetadata({ params }: Params) {
  const { lang, role } = await params;
  const lane = laneFromSlug(role);
  return lane ? boardMetadata(lang as Locale, null, lane) : {};
}

export default async function RolePage({ params }: Params) {
  const { lang, role } = await params;
  const lane = laneFromSlug(role);
  if (!lane) notFound();
  return <BoardRoute locale={lang as Locale} asOf={null} view={lane} />;
}
