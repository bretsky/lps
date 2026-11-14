import Link from "next/link";
import { notFound } from "next/navigation";
import { PlayerCard } from "@/components/card/PlayerCard";
import { loadIndex, loadPlayer } from "@/lib/data";

export async function generateStaticParams() {
  const rows = await loadIndex();
  return rows.filter((r) => r.slug).map((r) => ({ slug: r.slug }));
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
      title: `${p.playername} · LPS Card`,
      description: `${p.playername} — CLR ${p.clr.toFixed(1)}, rank #${p.rank}. Click to flip.`,
    };
  } catch {
    return { title: "Player Card · LPS" };
  }
}

export default async function CardPage({
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

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-4 py-12">
      <nav className="flex gap-4 self-start text-xs text-text-dim">
        <Link href="/" className="hover:text-text">
          ← Board
        </Link>
        <Link href={`/player/${slug}`} className="hover:text-text">
          ← Profile
        </Link>
      </nav>

      <PlayerCard player={player} />

      <p className="text-[10px] uppercase tracking-widest text-text-dim">
        Click card to flip
      </p>
    </main>
  );
}
