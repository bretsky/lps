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

/** The CSV of one view, for readers to download and cite; served by `app/csv/[board]/[file]/route.ts`.
 *  Files are named by the role's URL slug (jungle, adc, support), as on the role boards. */
export const CSV_SLUGS: Record<BoardView, string> = {
  all: "all", top: "top", jng: "jungle", mid: "mid", bot: "adc", sup: "support",
};
export const boardCsvUrl = (asOf: number | null, view: BoardView) => `/csv/${asOf ?? "today"}/${CSV_SLUGS[view]}.csv`;
/** The file name a download saves as: clr-mid.csv, clr-mid-end-2016.csv. */
export const boardCsvName = (asOf: number | null, view: BoardView) =>
  `clr-${CSV_SLUGS[view]}${asOf === null ? "" : `-end-${asOf}`}.csv`;
