import Link from "next/link";
import { notFound } from "next/navigation";
import { ProfileHeader } from "@/components/profile/ProfileHeader";
import { ClrWaterfall } from "@/components/profile/ClrWaterfall";
import { ResumeGrid } from "@/components/profile/ResumeGrid";
import { CareerLpsAnatomy } from "@/components/profile/CareerLpsAnatomy";
import { TrajectoryChart } from "@/components/profile/TrajectoryChart";
import { SplitsPanel } from "@/components/profile/SplitsPanel";
import { ChampionPool } from "@/components/profile/ChampionPool";
import { loadIndex, loadLane, loadPlayer } from "@/lib/data";
import { displayName } from "@/lib/format";
import { LanguageSwitcher } from "@/components/i18n/LanguageSwitcher";
import { T } from "@/components/i18n/T";
import type { Lane } from "@/lib/types";

export async function generateStaticParams() {
  const rows = await loadIndex();
  return rows
    .filter((r) => r.slug)
    .map((r) => ({ slug: r.slug }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  try {
    const p = await loadPlayer(slug);
    return {
      title: `${displayName(p.playername)} · CLR`,
      description: `${displayName(p.playername)} — CLR ${p.clr.toFixed(1)}, rank #${p.rank}.`,
    };
  } catch {
    return { title: "Player · CLR" };
  }
}

export default async function PlayerPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;

  let player;
  try {
    player = await loadPlayer(slug);
  } catch {
    notFound();
  }

  const lane: Lane | null = player.position;
  const laneRows = lane ? await loadLane(lane).catch(() => []) : [];
  const laneRank =
    laneRows.findIndex((r) => r.slug === slug) >= 0
      ? laneRows.findIndex((r) => r.slug === slug) + 1
      : null;

  return (
    <main className="mx-auto max-w-7xl px-4 py-6">
      <nav className="mb-4 flex items-center justify-between font-serif text-[11px] font-bold uppercase tracking-[0.25em]">
        <Link href="/" className="text-text-dim hover:text-gold-bright">
          ◂ <T k="nav.rankings" />
        </Link>
        <div className="flex items-center gap-5">
          <LanguageSwitcher />
          <Link href={`/card/${slug}`} className="text-text-dim hover:text-gold-bright">
            <T k="nav.playerCard" /> ▸
          </Link>
        </div>
      </nav>
      <ProfileHeader player={player} laneRank={laneRank} />
      <div className="mt-6 space-y-6">
        <ClrWaterfall player={player} />
        <ResumeGrid player={player} />
        <CareerLpsAnatomy player={player} />
        <TrajectoryChart player={player} />
        <ChampionPool player={player} />
        <SplitsPanel player={player} />
      </div>
    </main>
  );
}
