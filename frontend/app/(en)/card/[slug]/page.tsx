import { PlayerLink } from "@/components/PlayerLink";
import { LocalizedLink } from "@/components/i18n/LocalizedLink";
import { notFound } from "next/navigation";
import { PlayerCard } from "@/components/card/PlayerCard";
import { loadIndex, loadPlayer } from "@/lib/data";
import { displayName } from "@/lib/format";
import { LanguageSwitcher } from "@/components/i18n/LanguageSwitcher";
import { DocTitle, T } from "@/components/i18n/T";
import { pageMeta } from "@/lib/seo";
import { ogPlayerImage } from "@/lib/site";

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
    const name = displayName(p.playername);
    // The card is a view of the profile: search engines index the profile (canonical) instead.
    return pageMeta({
      title: `${name} · CLR Card`,
      description: `${name}'s CLR player card: #${p.rank} all-time in League of Legends esports, CLR ${p.clr.toFixed(1)}.`,
      path: `/player/${slug}`,
      image: ogPlayerImage(slug),
      imageAlt: `${name}: #${p.rank} all-time, CLR ${p.clr.toFixed(1)}`,
      type: "profile",
    });
  } catch {
    return { title: "Player Card · CLR" };
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
      <DocTitle k="card" args={[displayName(player.playername)]} />
      <nav className="relative flex w-full items-center gap-4 whitespace-nowrap font-serif text-[11px] font-bold uppercase tracking-[0.15em] text-text-dim sm:gap-5 sm:tracking-[0.25em]">
        <LocalizedLink path="/" className="hover:text-gold-bright">
          ◂ <T k="nav.rankingsShort" />
        </LocalizedLink>
        <PlayerLink slug={slug} className="hover:text-gold-bright">
          ◂ <T k="nav.profile" />
        </PlayerLink>
        <LanguageSwitcher className="ml-auto" />
      </nav>

      <div className="relative">
        <PlayerCard player={player} />
      </div>

      <p className="relative font-serif text-[10px] font-bold uppercase tracking-[0.35em] text-text-dim">
        <T k="card.clickToFlip" />
      </p>
    </main>
  );
}
