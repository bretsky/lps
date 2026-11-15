// Data loaders. The bundle lives under `frontend/public/data/current/`
// (overwritten on each `python -m lps.export_web` run). The build id +
// generated timestamp are in `current/meta.json`. Past snapshots are
// auto-archived to `frontend/public/data/archive/<build_id>/` locally but
// are gitignored -- only `current/` ships in the repo.

import type {
  AsOfJson,
  AsOfRow,
  GlossaryJson,
  TierMeta,
  IndexRow,
  Lane,
  Meta,
  PlayerDetail,
  TiersJson,
} from "./types";
import { BOARD_PAGE, BOARD_VIEWS, type BoardView, type ViewSummary } from "./board";
import { promises as fs } from "fs";
import path from "path";

const CURRENT_DATA = path.join(process.cwd(), "public", "data", "current");

async function readJson<T>(rel: string): Promise<T> {
  const p = path.join(CURRENT_DATA, rel);
  const raw = await fs.readFile(p, "utf-8");
  return JSON.parse(raw) as T;
}

export async function loadIndex(): Promise<IndexRow[]> {
  return readJson<IndexRow[]>("index.json");
}

export async function loadTiers(): Promise<TiersJson> {
  return readJson<TiersJson>("tiers.json");
}

export async function loadMeta(): Promise<Meta> {
  return readJson<Meta>("meta.json");
}

export async function loadLane(lane: Lane): Promise<IndexRow[]> {
  return readJson<IndexRow[]>(`lanes/${lane}.json`);
}

export async function loadPlayer(slug: string): Promise<PlayerDetail> {
  return readJson<PlayerDetail>(`players/${slug}.json`);
}

const LANES: Lane[] = ["top", "jng", "mid", "bot", "sup"];

export interface BoardData {
  rows: IndexRow[];                            // first BOARD_PAGE rows of the all-roles view
  summaries: Record<BoardView, ViewSummary>;
  tiers: TierMeta[];
  ratedCount: number;
  prevYear: number | null;                     // season each row's `rank_prev` refers to
}

interface FullBoard {
  views: Record<BoardView, IndexRow[]>;
  tiers: TierMeta[];
  ratedCount: number;
  prevYear: number | null;
}

const byClr = (rows: IndexRow[]) => [...rows].sort((a, b) => b.clr - a.clr);

/** Today's board: the global index plus every lane file. */
async function loadTodayFull(): Promise<FullBoard> {
  const [rows, tiers, ...laneArrays] = await Promise.all([
    loadIndex(),
    loadTiers(),
    ...LANES.map((l) => loadLane(l).catch(() => [] as IndexRow[])),
  ]);
  const views = { all: byClr(rows) } as Record<BoardView, IndexRow[]>;
  LANES.forEach((l, i) => (views[l] = byClr(laneArrays[i])));
  return { views, tiers: tiers.tiers, ratedCount: tiers.rated_count, prevYear: tiers.prev_year ?? null };
}

/** The board frozen at the end of `year`. Snapshot rows carry the numbers as they stood
 *  then; photos, names and the like come from today's index (anyone rated back then is
 *  still rated today, since games only accumulate). */
async function loadAsOfFull(year: number): Promise<FullBoard> {
  const [snap, base] = await Promise.all([readJson<AsOfJson>(`asof/${year}.json`), loadIndex()]);
  const bySlug = new Map(base.map((r) => [r.slug, r]));
  const join = (rows: AsOfRow[] | undefined): IndexRow[] =>
    byClr(
      (rows ?? []).flatMap((r) => {
        const b = bySlug.get(r.slug);
        // Not on today's board (early-season floors are lower): the row carries its own identity.
        return b ? [{ ...b, ...r } as IndexRow] : r.playername ? [r as IndexRow] : [];
      }),
    );
  const views = { all: join(snap.all) } as Record<BoardView, IndexRow[]>;
  for (const l of LANES) views[l] = join(snap.lanes[l]);
  return { views, tiers: snap.tiers, ratedCount: snap.rated_count, prevYear: snap.prev_year ?? null };
}

const loadFull = (asOf: number | null) => (asOf === null ? loadTodayFull() : loadAsOfFull(asOf));

function summarize(rows: IndexRow[]): ViewSummary {
  const leagues = new Set<string>();
  const tierCounts: Record<string, number> = {};
  let maxClr = 0;
  for (const r of rows) {
    if (r.current_league) leagues.add(r.current_league);
    tierCounts[r.tier] = (tierCounts[r.tier] ?? 0) + 1;
    if (r.clr > maxClr) maxClr = r.clr;
  }
  return { total: rows.length, maxClr, leagues: Array.from(leagues).sort(), tierCounts };
}

/** The first page of a board (today when `asOf` is null) plus a summary of every view.
 *  The full lists are served by `app/api/board/[board]/[view]` and fetched on demand. */
export async function loadBoardPage(asOf: number | null): Promise<BoardData> {
  const full = await loadFull(asOf);
  const summaries = Object.fromEntries(
    BOARD_VIEWS.map((v) => [v, summarize(full.views[v])]),
  ) as Record<BoardView, ViewSummary>;
  return {
    rows: full.views.all.slice(0, BOARD_PAGE),
    summaries,
    tiers: full.tiers,
    ratedCount: full.ratedCount,
    prevYear: full.prevYear,
  };
}

/** Every row of one view of a board, for the client to fetch once it scrolls or filters. */
export async function loadBoardView(asOf: number | null, view: BoardView): Promise<IndexRow[]> {
  return (await loadFull(asOf)).views[view] ?? [];
}

export async function loadGlossary(): Promise<GlossaryJson> {
  return readJson<GlossaryJson>("glossary.json");
}
