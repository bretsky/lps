import Board from "@/components/board/Board";
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
        <div className="border-b border-accent-gold/30 bg-accent-gold/10 px-4 py-1.5 text-center text-xs text-accent-gold">
          Beta — provisional weights, rankings may change. Data through {meta.years[1]}.
        </div>
      )}
      <Board rows={rows} laneRows={laneRows} tiers={tiers.tiers} />
      <footer className="border-t border-border py-6 text-center text-xs text-text-dim">
        Build {meta.build_id} · {meta.counts.rated} rated players (games ≥ {meta.rated_min_games}) ·
        Not endorsed by Riot Games · Data from Oracle&apos;s Elixir and Leaguepedia
      </footer>
    </main>
  );
}
