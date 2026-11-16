// /ko/player/<slug>, /zh/player/<slug>. Built with the rest of the site, but deployed separately
// (see components/routes/PlayerRoute.tsx).
import { PlayerRoute, playerMetadata, playerSlugs } from "@/components/routes/PlayerRoute";
import type { Locale } from "@/lib/i18n/config";

export const dynamicParams = false;

export async function generateStaticParams() {
  return (await playerSlugs()).map((slug) => ({ slug }));
}

type Params = { params: Promise<{ lang: string; slug: string }> };

export async function generateMetadata({ params }: Params) {
  const { lang, slug } = await params;
  return playerMetadata(lang as Locale, slug);
}

export default async function PlayerPage({ params }: Params) {
  const { lang, slug } = await params;
  return <PlayerRoute locale={lang as Locale} slug={slug} />;
}
