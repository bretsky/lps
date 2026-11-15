// Board paging shared by the server loaders (lib/data.ts) and the client board. No `fs`
// here, so client components can import it.

import type { Lane } from "./types";

/** Rows the server renders up front, and how many more each scroll step reveals. */
export const BOARD_PAGE = 100;

export type BoardView = Lane | "all";
export const BOARD_VIEWS: BoardView[] = ["all", "top", "jng", "mid", "bot", "sup"];

/** What the board needs to know about a view before its full row list is fetched. */
export interface ViewSummary {
  total: number;
  maxClr: number;
  leagues: string[];
  tierCounts: Record<string, number>;
}

/** URL of the full row list for one view; served by `app/api/board/[board]/[view]/route.ts`. */
export const boardViewUrl = (asOf: number | null, view: BoardView) => `/api/board/${asOf ?? "today"}/${view}`;
