import Link from "next/link";
import { notFound } from "next/navigation";
import { ProfileHeader } from "@/components/profile/ProfileHeader";
import { ClrWaterfall } from "@/components/profile/ClrWaterfall";
import { ResumeGrid } from "@/components/profile/ResumeGrid";
import { CareerLpsAnatomy } from "@/components/profile/CareerLpsAnatomy";
import { TrajectoryChart } from "@/components/profile/TrajectoryChart";
import { SplitsPanel } from "@/components/profile/SplitsPanel";
import { loadIndex, loadLane, loadPlayer } from "@/lib/data";
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
      title: `${p.playername} · LPS`,
      description: `${p.playername} — CLR ${p.clr.toFixed(1)}, rank #${p.rank}.`,
    };
  } catch {
    return { title: "Player · LPS" };
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
      <div className="mb-4 flex items-center justify-between">
        <Link
          href="/"
          className="text-xs uppercase tracking-wide text-text-muted hover:text-text"
        >
          ← Back to board
        </Link>
        <Link
          href={`/card/${slug}`}
          className="text-xs uppercase tracking-wide text-text-dim hover:text-text-muted"
        >
          View Card →
        </Link>
      </div>
      <ProfileHeader player={player} laneRank={laneRank} />
      <div className="mt-6 space-y-6">
        <ClrWaterfall player={player} />
        <ResumeGrid player={player} />
        <CareerLpsAnatomy player={player} />
        <TrajectoryChart player={player} />
        <SplitsPanel player={player} />
      </div>
    </main>
  );
}
