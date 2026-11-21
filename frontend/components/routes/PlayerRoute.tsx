// A player's profile: /player/<slug>, and /ko/player/<slug>, /zh/player/<slug>. The Korean and
// Chinese copies don't fit in the production Pages deployment (20k-file cap): scripts/deploy.mjs
// uploads them to a branch deployment of their own, and functions/{ko,zh}/player proxies them
// onto the site's domain.
import Link from "next/link";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { ProfileHeader } from "@/components/profile/ProfileHeader";
import { ClrWaterfall } from "@/components/profile/ClrWaterfall";
import { ResumeGrid } from "@/components/profile/ResumeGrid";
import { CareerLpsAnatomy } from "@/components/profile/CareerLpsAnatomy";
import { TrajectoryChart } from "@/components/profile/TrajectoryChart";
import { SplitsPanel } from "@/components/profile/SplitsPanel";
import { ChampionPool } from "@/components/profile/ChampionPool";
import { LanguageSwitcher } from "@/components/i18n/LanguageSwitcher";
import { LocalizedLink } from "@/components/i18n/LocalizedLink";
import { T } from "@/components/i18n/T";
import { JsonLd } from "@/components/JsonLd";
import { PlayerLink } from "@/components/PlayerLink";
import { SiteLinks } from "@/components/SiteLinks";
import { loadIndex, loadLane, loadMeta, loadPlayer } from "@/lib/data";
import { displayName } from "@/lib/format";
import type { Locale } from "@/lib/i18n/config";
import { SEO, type PlayerFacts } from "@/lib/i18n/seo";
import { absUrl, pageMeta } from "@/lib/seo";
import { boardPath, localePath, ogPlayerImage } from "@/lib/site";
import type { IndexRow, Lane, PlayerDetail } from "@/lib/types";

export async function playerSlugs(): Promise<string[]> {
  return (await loadIndex()).filter((r) => r.slug).map((r) => r.slug);
}

async function laneRankOf(lane: Lane, slug: string): Promise<number | null> {
  const rows = await loadLane(lane).catch(() => []);
  const i = rows.findIndex((r) => r.slug === slug);
  return i >= 0 ? i + 1 : null;
}

function facts(p: PlayerDetail, row: IndexRow | null, laneRank: number | null, locale: Locale): PlayerFacts {
  return {
    name: displayName(p.playername),
    native: (locale === "ko" ? p.name_ko : locale === "zh" ? p.name_zh : null) || null,
    realName: p.real_name ?? null,
    lane: p.position,
    team: p.current_team,
    league: p.current_league,
    active: !!p.is_active,
    span: p.first_year === p.last_year ? `${p.first_year}` : `${p.first_year}–${p.last_year}`,
    rank: p.rank,
    laneRank,
    clr: p.clr.toFixed(1),
    titles: row?.titles ?? {},
    games: p.games,
    winPct: p.win_rate != null ? Math.round(p.win_rate * 100) : null,
    champs: (p.champions ?? []).slice(0, 3).map((c) => c.champion),
  };
}

export async function playerMetadata(locale: Locale, slug: string): Promise<Metadata> {
  try {
    const [p, index] = await Promise.all([loadPlayer(slug), loadIndex()]);
    const row = index.find((r) => r.slug === slug) ?? null;
    const f = facts(p, row, p.position ? await laneRankOf(p.position, slug) : null, locale);
    return pageMeta({
      title: SEO[locale].player(f),
      description: SEO[locale].playerDesc(f),
      path: `/player/${slug}`,
      locale,
      localized: true,
      image: ogPlayerImage(slug),
      imageAlt: `${f.name}: #${p.rank} all-time, CLR ${f.clr}`,
      type: "profile",
    });
  } catch {
    return { title: "Player · CLR" };
  }
}

export async function PlayerRoute({ locale, slug }: { locale: Locale; slug: string }) {
  let player;
  try {
    player = await loadPlayer(slug);
  } catch {
    notFound();
  }

  const lane: Lane | null = player.position;
  const [laneRank, index, meta] = await Promise.all([
    lane ? laneRankOf(lane, slug) : null,
    loadIndex(),
    loadMeta(),
  ]);
  const nearby = neighbours(index, player.rank, 4);
  const name = displayName(player.playername);
  const alt = [player.real_name, player.name_ko, player.name_zh, player.playername !== name ? player.playername : null]
    .filter((x): x is string => !!x);
  const url = absUrl(localePath(locale, `/player/${slug}`));
  const s = SEO[locale];

  return (
    <main className="mx-auto max-w-7xl px-4 py-6">
      <nav className="mb-4 flex items-center justify-between gap-3 whitespace-nowrap font-serif text-[11px] font-bold uppercase tracking-[0.18em] sm:tracking-[0.25em]">
        <LocalizedLink path="/" className="text-text-dim hover:text-gold-bright">
          ◂{" "}
          <span className="sm:hidden">
            <T k="nav.rankingsShort" />
          </span>
          <span className="hidden sm:inline">
            <T k="nav.rankings" />
          </span>
        </LocalizedLink>
        <div className="flex items-center gap-5">
          <LanguageSwitcher />
          {/* on phones the header's "View card" plaque is the way to the card */}
          <Link href={`/card/${slug}`} prefetch={false} className="hidden text-text-dim hover:text-gold-bright sm:inline">
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
        <Nearby rows={nearby} current={slug} />
      </div>
      <footer className="mt-10 border-t border-gold-deep/40 pb-4 text-center">
        <SiteLinks years={[...(meta.asof_years ?? [])].sort((a, b) => b - a)} />
      </footer>
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "ProfilePage",
          url,
          inLanguage: locale === "zh" ? "zh-CN" : locale,
          mainEntity: {
            "@type": "Person",
            name,
            ...(alt.length ? { alternateName: alt } : {}),
            ...(player.photo ? { image: player.photo } : {}),
            ...(player.country ? { nationality: { "@type": "Country", name: player.country } } : {}),
            jobTitle: "Professional League of Legends player",
            ...(player.current_team && player.is_active
              ? { memberOf: { "@type": "SportsTeam", name: player.current_team, sport: "League of Legends" } }
              : {}),
            url,
          },
        }}
      />
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "BreadcrumbList",
          itemListElement: [
            { "@type": "ListItem", position: 1, name: s.home, item: absUrl(localePath(locale, "/")) },
            ...(lane
              ? [{ "@type": "ListItem", position: 2, name: s.role(lane), item: absUrl(boardPath(null, lane, locale)) }]
              : []),
            { "@type": "ListItem", position: lane ? 3 : 2, name, item: url },
          ],
        }}
      />
    </main>
  );
}

/** The players ranked just above and below on the all-time board (`span` each side). */
function neighbours(index: IndexRow[], rank: number, span: number): IndexRow[] {
  const byRank = [...index].sort((a, b) => a.rank - b.rank);
  const i = byRank.findIndex((r) => r.rank === rank);
  if (i < 0) return [];
  const lo = Math.max(0, Math.min(i - span, byRank.length - 2 * span - 1));
  return byRank.slice(lo, lo + 2 * span + 1);
}

/** "Ranked nearby": the neighbouring players on the all-time board, so every profile links on. */
function Nearby({ rows, current }: { rows: IndexRow[]; current: string }) {
  if (rows.length < 2) return null;
  return (
    <section className="deco-panel">
      <h2 className="mb-3 font-serif text-sm font-extrabold uppercase tracking-[0.3em] text-gold">
        <T k="profile.nearby" />
      </h2>
      <ol className="grid gap-x-6 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map((r) => {
          const here = r.slug === current;
          return (
            <li key={r.slug}>
              <PlayerLink
                slug={r.slug}
                prefetch={false}
                aria-current={here ? "page" : undefined}
                className={`flex items-baseline gap-3 border-b border-border/60 py-1.5 ${
                  here ? "text-gold-bright" : "text-text hover:text-gold-bright"
                }`}
              >
                <span className="w-12 text-right font-mono text-xs text-text-dim">#{r.rank}</span>
                <span className="flex-1 truncate font-display text-lg font-bold uppercase tracking-wide">
                  {displayName(r.playername)}
                </span>
                <span className="font-serif text-[10px] font-bold uppercase tracking-[0.2em] text-text-dim">
                  {r.position ? <T k={`lanes.${r.position}`} /> : null}
                </span>
                <span className="w-12 text-right font-mono text-xs text-text-muted">{r.clr.toFixed(1)}</span>
              </PlayerLink>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
