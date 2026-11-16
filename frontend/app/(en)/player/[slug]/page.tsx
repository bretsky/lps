import { PlayerRoute, playerMetadata, playerSlugs } from "@/components/routes/PlayerRoute";

export const dynamicParams = false;

export async function generateStaticParams() {
  return (await playerSlugs()).map((slug) => ({ slug }));
}

type Params = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Params) {
  return playerMetadata("en", (await params).slug);
}

export default async function PlayerPage({ params }: Params) {
  return <PlayerRoute locale="en" slug={(await params).slug} />;
}
