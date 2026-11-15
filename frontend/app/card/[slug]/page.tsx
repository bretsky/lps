import Link from "next/link";
import { notFound } from "next/navigation";
import { PlayerCard } from "@/components/card/PlayerCard";
import { loadIndex, loadPlayer } from "@/lib/data";
import { displayName } from "@/lib/format";

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
      title: `${displayName(p.playername)} · LPS Card`,
      description: `${displayName(p.playername)} — CLR ${p.clr.toFixed(1)}, rank #${p.rank}. Click to flip.`,
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
    <main className="relative flex min-h-screen flex-col items-center justify-center gap-6 overflow-hidden px-4 py-12">
      {/* spotlight */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse 40% 55% at 50% 50%, rgba(31,209,193,0.10), transparent 70%), radial-gradient(ellipse 30% 20% at 50% 92%, rgba(201,164,92,0.12), transparent 70%)",
        }}
      />
      <nav className="relative flex gap-5 self-start font-serif text-[11px] font-bold uppercase tracking-[0.25em] text-text-dim">
        <Link href="/" className="hover:text-gold-bright">
          ◂ Rankings
        </Link>
        <Link href={`/player/${slug}`} className="hover:text-gold-bright">
          ◂ Profile
        </Link>
      </nav>

      <div className="relative">
        <PlayerCard player={player} />
      </div>

      <p className="relative font-serif text-[10px] font-bold uppercase tracking-[0.35em] text-text-dim">
        Click the card to flip
      </p>
    </main>
  );
}
