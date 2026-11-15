import Board from "@/components/board/Board";
import { Hero } from "@/components/board/Hero";
import { loadIndex, loadLane, loadMeta, loadTiers } from "@/lib/data";
import type { IndexRow, Lane } from "@/lib/types";

const LANES: Lane[] = ["top", "jng", "mid", "bot", "sup"];

export default async function Page() {
  const [rows, tiers, meta, ...laneArrays] = await Promise.all([
    loadIndex(),
    loadTiers(),
    loadMeta(),
    ...LANES.map((l) => loadLane(l).catch(() => [] as IndexRow[])),
  ]);
  const laneRows = Object.fromEntries(LANES.map((l, i) => [l, laneArrays[i]])) as Record<Lane, IndexRow[]>;
  return (
    <main>
      {meta.beta && (
        <div className="border-b border-gold-deep/50 bg-black/60 px-4 py-1.5 text-center font-serif text-[10px] font-bold uppercase tracking-[0.3em] text-gold">
          Beta <span className="text-teal">◆</span> provisional weights, rankings may change{" "}
          <span className="text-teal">◆</span> data through {meta.years[1]}
        </div>
      )}
      <Hero rows={rows} meta={meta} />
      <Board rows={rows} laneRows={laneRows} tiers={tiers.tiers} />
      <footer className="border-t border-gold-deep/40 py-8 text-center">
        <div className="deco-rule mx-auto mb-3 max-w-xs">
          <span className="h-2 w-2 rotate-45 bg-gold" />
        </div>
        <p className="font-serif text-[10px] font-bold uppercase tracking-[0.3em] text-text-dim">
          Build {meta.build_id} · {meta.counts.rated} rated players (games ≥ {meta.rated_min_games})
        </p>
        <p className="mt-1 text-[11px] text-text-dim">
          Not endorsed by Riot Games · Data and photos from Oracle&apos;s Elixir and Leaguepedia · League marks © their
          owners
        </p>
      </footer>
    </main>
  );
}
