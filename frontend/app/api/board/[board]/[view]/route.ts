// Full row list for one view of a board ("today" or a frozen past season), fetched by the
// client board once the reader scrolls past the server-rendered first page or filters.
// Prerendered for every board × view at build time.
import { BOARD_VIEWS, type BoardView } from "@/lib/board";
import { loadBoardView, loadMeta } from "@/lib/data";

export const dynamic = "force-static";
export const dynamicParams = false;

export async function generateStaticParams() {
  const meta = await loadMeta();
  const boards = ["today", ...(meta.asof_years ?? []).map(String)];
  return boards.flatMap((board) => BOARD_VIEWS.map((view) => ({ board, view })));
}

export async function GET(_req: Request, { params }: { params: Promise<{ board: string; view: string }> }) {
  const { board, view } = await params;
  if (!BOARD_VIEWS.includes(view as BoardView)) return new Response("Not found", { status: 404 });
  let asOf: number | null = null;
  if (board !== "today") {
    asOf = Number(board);
    const meta = await loadMeta();
    if (!meta.asof_years?.includes(asOf)) return new Response("Not found", { status: 404 });
  }
  return Response.json(await loadBoardView(asOf, view as BoardView));
}
