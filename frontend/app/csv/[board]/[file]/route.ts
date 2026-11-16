// /csv/<board>/<role>.csv: every player on one view of a board ("today" or a frozen past season;
// role = all, top, jungle, mid, adc, support) as a spreadsheet, for writers and analysts to use
// and cite. Each row links back to the player's profile. Prerendered for every board x view;
// the ".csv" in the URL makes Pages serve it as text/csv.
import { BOARD_VIEWS, CSV_SLUGS, type BoardView } from "@/lib/board";
import { loadBoardPage, loadBoardView, loadIndex, loadMeta } from "@/lib/data";
import { ROLE_SLUGS, SITE_URL } from "@/lib/site";
import type { IndexRow } from "@/lib/types";

export const dynamic = "force-static";
export const dynamicParams = false;

const VIEW_BY_FILE = Object.fromEntries(BOARD_VIEWS.map((v) => [`${CSV_SLUGS[v]}.csv`, v])) as Record<
  string,
  BoardView
>;

export async function generateStaticParams() {
  const meta = await loadMeta();
  const boards = ["today", ...(meta.asof_years ?? []).map(String)];
  return boards.flatMap((board) => Object.keys(VIEW_BY_FILE).map((file) => ({ board, file })));
}

/** One CSV field: quoted when it holds a comma, quote or line break. */
function field(v: string | number | boolean | null | undefined): string {
  if (v === null || v === undefined) return "";
  const s = String(v);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

const round = (v: number | null | undefined, d: number) => (v === null || v === undefined ? null : Number(v.toFixed(d)));

export async function GET(_req: Request, { params }: { params: Promise<{ board: string; file: string }> }) {
  const { board, file } = await params;
  const view = VIEW_BY_FILE[file];
  if (!view) return new Response("Not found", { status: 404 });
  let asOf: number | null = null;
  if (board !== "today") {
    asOf = Number(board);
    if (!(await loadMeta()).asof_years?.includes(asOf)) return new Response("Not found", { status: 404 });
  }

  const [rows, page, index] = await Promise.all([loadBoardView(asOf, view), loadBoardPage(asOf, view), loadIndex()]);
  const tierLabel = new Map(page.tiers.map((t) => [t.key, t.label]));
  const hasProfile = new Set(index.map((r) => r.slug));
  const prev = page.prevYear;

  const header = [
    "rank", "player", "real_name", "name_ko", "name_zh", "role", "team", "league",
    "first_season", "last_season", "seasons", "games", "win_rate",
    "clr", "tier", "career_lps", "peak_lps", "resume",
    "worlds_titles", "msi_titles", "league_titles", "hall_of_legends", "status",
    ...(prev ? [`rank_end_${prev}`, `clr_end_${prev}`] : []),
    "profile_url",
  ];
  const line = (r: IndexRow, i: number) => {
    const lane = view === "all" ? r.position : view;
    return [
      i + 1,
      r.playername,
      r.real_name,
      r.name_ko,
      r.name_zh,
      lane ? ROLE_SLUGS[lane] : null,
      r.current_team,
      r.current_league,
      r.first_year,
      r.last_year,
      r.n_years,
      r.games,
      round(r.win_rate, 3),
      round(r.clr, 2),
      tierLabel.get(r.tier) ?? r.tier,
      round(r.total_score, 2),
      round(r.peak_lps, 2),
      round(r.resume_bonus, 2),
      r.titles?.worlds ?? 0,
      r.titles?.msi ?? 0,
      r.titles?.domestic ?? 0,
      r.hall_of_legends ? "yes" : "no",
      r.is_retired ? "retired" : r.is_active ? "active" : "inactive",
      ...(prev ? [r.rank_prev, round(r.clr_prev, 2)] : []),
      hasProfile.has(r.slug) ? `${SITE_URL}/player/${r.slug}` : null,
    ]
      .map(field)
      .join(",");
  };

  // Byte-order mark first, so Excel reads the Korean / Chinese names as UTF-8.
  const body = String.fromCharCode(0xfeff) + [header.join(","), ...rows.map(line)].join("\r\n") + "\r\n";
  return new Response(body, { headers: { "content-type": "text/csv; charset=utf-8" } });
}
