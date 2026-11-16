"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { IndexRow, Lane, TierMeta } from "@/lib/types";
import { PlayerRow, ROW_GRID } from "./PlayerRow";
import { useT } from "@/lib/i18n";
import { BOARD_PAGE, boardViewUrl, type BoardView, type ViewSummary } from "@/lib/board";

type SortKey = "clr" | "total_score" | "peak_lps" | "resume_bonus" | "n_years";
const SORT_KEYS: SortKey[] = ["clr", "total_score", "peak_lps", "resume_bonus", "n_years"];

const LANE_FILTERS: (Lane | "all")[] = ["all", "top", "jng", "mid", "bot", "sup"];

interface Props {
  initialRows: IndexRow[];   // first BOARD_PAGE rows of the all-roles view (server-rendered)
  summaries: Record<BoardView, ViewSummary>;
  tiers: TierMeta[];
  asOf: number | null;      // season this board is frozen at; null = today
  years: number[];          // seasons with a frozen board, newest first
  latestYear: number;
  prevYear: number | null;  // season the rank-movement arrows compare against
}

export default function Board({ initialRows, summaries, tiers, asOf, years, latestYear, prevYear }: Props) {
  const router = useRouter();
  const m = useT();
  const [q, setQ] = useState("");
  const [lane, setLaneState] = useState<Lane | "all">("all");

  // The role tab rides along in `?lane=` so switching years (and shared links) keep it.
  useEffect(() => {
    const l = new URLSearchParams(window.location.search).get("lane") as Lane | null;
    if (l && LANE_FILTERS.includes(l)) setLaneState(l);
  }, []);
  const laneQuery = (l: Lane | "all") => (l === "all" ? "" : `?lane=${l}`);
  const setLane = (l: Lane | "all") => {
    setLaneState(l);
    window.history.replaceState(null, "", window.location.pathname + laneQuery(l));
  };
  const goToYear = (y: string) => router.push((y === "today" ? "/" : `/asof/${y}`) + laneQuery(lane));
  const [league, setLeague] = useState<string>("all");
  const [sortKey, setSortKey] = useState<SortKey>("clr");

  // Each view's full row list, fetched on demand. Until the all-roles list arrives the
  // board shows the server-rendered first page, which is only complete enough for the
  // default view (all roles, every league, no search, CLR order); anything else waits.
  const [full, setFull] = useState<Partial<Record<BoardView, IndexRow[]>>>({});
  const [failed, setFailed] = useState<BoardView | null>(null);
  const inflight = useRef(new Set<BoardView>());
  const requestView = useCallback(
    (v: BoardView) => {
      if (full[v] || inflight.current.has(v)) return;
      inflight.current.add(v);
      setFailed(null);
      fetch(boardViewUrl(asOf, v))
        .then((r) => {
          if (!r.ok) throw new Error(`${r.status}`);
          return r.json() as Promise<IndexRow[]>;
        })
        .then((data) => setFull((f) => ({ ...f, [v]: data })))
        .catch(() => setFailed(v))
        .finally(() => inflight.current.delete(v));
    },
    [asOf, full],
  );

  const isDefault = lane === "all" && !q.trim() && league === "all" && sortKey === "clr";
  useEffect(() => {
    if (!isDefault) requestView(lane);
  }, [isDefault, lane, requestView]);

  // When a lane is picked, we render the per-lane file instead of filtering
  // the global index. That way each row's `clr` (and rank/tier) reflects the
  // player's career *as if only their seasons in that lane existed* -- e.g.
  // Xiaohu appears in both Mid and Top with different CLR values.
  const loaded = full[lane];
  const source: IndexRow[] | null = loaded ?? (isDefault ? initialRows : null);
  const summary = summaries[lane];
  const maxClr = summary.maxClr;
  const leagues = useMemo(() => ["all", ...summary.leagues], [summary]);

  const filtered = useMemo(() => {
    if (!source) return [];
    const qn = q.trim().toLowerCase();
    let out = source;
    if (qn)
      out = out.filter(
        (r) =>
          r.playername.toLowerCase().includes(qn) ||
          // any language's name finds the player: "faker", "lee sang", "이상혁", "卓定"
          [r.real_name, r.name_ko, r.name_zh].some((n) => (n ?? "").toLowerCase().includes(qn)),
      );
    if (league !== "all") out = out.filter((r) => r.current_league === league);
    out = [...out].sort((a, b) => (b[sortKey] ?? -Infinity) - (a[sortKey] ?? -Infinity));
    // Re-rank within the filtered view so ranks read 1..N.
    return out.map((r, i) => ({ ...r, filteredRank: i + 1 }));
  }, [source, q, league, sortKey]);
  const total = loaded ? filtered.length : summary.total;

  // Render a page at a time; the sentinel below the list reveals the next page (fetching
  // the view's full list first if we only have the server-rendered page).
  const [limit, setLimit] = useState(BOARD_PAGE);
  useEffect(() => setLimit(BOARD_PAGE), [lane, q, league, sortKey]);
  const visible = useMemo(() => filtered.slice(0, limit), [filtered, limit]);
  const hasMore = source !== null && (limit < filtered.length || !loaded);
  const sentinel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !hasMore) return;
    // Re-created whenever the list grows, so it fires again at once while the sentinel is
    // still within reach -- that keeps filling a tall screen without further scrolling.
    const io = new IntersectionObserver(
      ([e]) => {
        if (!e.isIntersecting) return;
        if (limit < filtered.length) setLimit((l) => l + BOARD_PAGE);
        else requestView(lane);
      },
      { rootMargin: "1500px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [hasMore, limit, filtered.length, lane, requestView]);

  // Group rows by tier only when sorting by CLR (native ordering); otherwise show a flat
  // list. Banner counts cover the whole view, not just the rendered page.
  const grouped = useMemo(() => {
    if (sortKey !== "clr" || q.trim()) return null;
    const groups = new Map<string, IndexRow[]>();
    const counts = new Map<string, number>();
    for (const t of tiers) groups.set(t.key, []);
    for (const r of visible) {
      const arr = groups.get(r.tier) ?? [];
      arr.push(r);
      groups.set(r.tier, arr);
    }
    if (loaded) for (const r of filtered) counts.set(r.tier, (counts.get(r.tier) ?? 0) + 1);
    else for (const [k, n] of Object.entries(summary.tierCounts)) counts.set(k, n);
    return { groups, counts };
  }, [visible, filtered, loaded, summary, tiers, sortKey, q]);

  return (
    <div className="mx-auto max-w-6xl px-4 pb-16 pt-6">
      {/* Lane tabs, client-nav style: caps, gold underline on the active tab */}
      <nav className="mb-5 flex flex-wrap items-end gap-x-6 gap-y-2 border-b border-border">
        {LANE_FILTERS.map((l) => {
          const active = lane === l;
          return (
            <button
              key={l}
              onClick={() => setLane(l)}
              className={`relative -mb-px pb-2.5 font-serif text-[13px] font-bold uppercase tracking-[0.18em] transition-colors ${
                active ? "text-gold-bright" : "text-text-dim hover:text-text-muted"
              }`}
            >
              {l === "all" ? m.board.allRoles : m.lanes[l]}
              <span
                className={`absolute inset-x-0 bottom-0 h-[2px] transition-opacity ${active ? "opacity-100" : "opacity-0"}`}
                style={{ background: "linear-gradient(90deg, transparent, #f1d58f, transparent)", boxShadow: "0 0 8px #c9a45c" }}
              />
            </button>
          );
        })}
        <div className="ml-auto flex flex-wrap items-center gap-2 pb-2">
          {years.length > 0 && (
            <select
              value={asOf === null ? "today" : String(asOf)}
              onChange={(e) => goToYear(e.target.value)}
              title={m.board.yearTitle}
              aria-label={m.board.yearAria}
              className={`deco-control px-2 py-1.5 text-xs uppercase tracking-wider ${asOf !== null ? "!border-teal text-teal" : ""}`}
            >
              <option value="today">{m.board.asOfToday(latestYear)}</option>
              {years.map((y) => (
                <option key={y} value={y}>
                  {m.board.asOfEnd(y)}
                </option>
              ))}
            </select>
          )}
          <input
            type="text"
            placeholder={m.board.search}
            aria-label={m.board.search}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="deco-control w-52 px-3 py-1.5 text-sm placeholder:text-text-dim focus:border-teal focus:outline-none"
          />
          <select
            value={league}
            onChange={(e) => setLeague(e.target.value)}
            aria-label={m.board.leagueAria}
            className="deco-control px-2 py-1.5 text-xs uppercase tracking-wider"
          >
            {leagues.map((l) => (
              <option key={l} value={l}>
                {l === "all" ? m.board.allLeagues : l}
              </option>
            ))}
          </select>
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            aria-label={m.board.sortAria}
            className="deco-control px-2 py-1.5 text-xs uppercase tracking-wider"
          >
            {SORT_KEYS.map((k) => (
              <option key={k} value={k}>
                {m.board.sortBy(m.board.sort[k])}
              </option>
            ))}
          </select>
        </div>
      </nav>

      {/* column header */}
      <div
        className={`${ROW_GRID} px-4 pb-2 font-serif text-[10px] font-bold uppercase tracking-[0.2em] text-text-dim`}
      >
        <div className="text-right">#</div>
        <div />
        <div>{m.board.col.player}</div>
        <div className="hidden md:block">{m.board.col.role}</div>
        <div className="hidden lg:block">{m.board.col.career}</div>
        <div className="hidden sm:block">{m.board.col.titles}</div>
        <div className="text-right">{m.board.col.clr}</div>
        <div className="hidden lg:block text-right">{m.board.col.peak}</div>
      </div>

      <div className="deco-panel !p-0">
        <div>
          {source === null ? (
            <BoardStatus failed={failed === lane} onRetry={() => requestView(lane)} />
          ) : grouped ? (
            tiers.map((t) => {
                const players = grouped.groups.get(t.key) ?? [];
                if (!players.length) return null;
                return (
                  <section key={t.key}>
                    <TierBanner tier={t} count={grouped.counts.get(t.key) ?? players.length} />
                    {players.map((r) => (
                      <PlayerRow key={r.slug} row={r} maxClr={maxClr} prevYear={prevYear} />
                    ))}
                  </section>
                );
              })
          ) : (
            visible.map((r) => <PlayerRow key={r.slug} row={r} maxClr={maxClr} prevYear={prevYear} />)
          )}
          {hasMore && (
            <div ref={sentinel}>
              <BoardStatus failed={failed === lane} onRetry={() => requestView(lane)} />
            </div>
          )}
        </div>
      </div>
      <div className="mt-3 text-right font-mono text-[11px] text-text-dim">
        {source === null ? "…" : m.board.players(total)}
      </div>
    </div>
  );
}

/** Placeholder while a view's rows are on their way, or a retry if fetching them failed. */
function BoardStatus({ failed, onRetry }: { failed: boolean; onRetry: () => void }) {
  const m = useT();
  return (
    <div className="px-4 py-6 text-center font-serif text-[11px] font-bold uppercase tracking-[0.25em] text-text-dim">
      {failed ? (
        <>
          {m.board.loadFailed}{" "}
          <button onClick={onRetry} className="ml-2 text-gold underline-offset-4 hover:text-gold-bright hover:underline">
            {m.board.retry}
          </button>
        </>
      ) : (
        m.board.loading
      )}
    </div>
  );
}

/** Tier divider: a lozenge, engraved tier name, and a rule in the tier's colour. */
function TierBanner({ tier, count }: { tier: TierMeta; count: number }) {
  const m = useT();
  const c = tier.color;
  return (
    <div
      className="sticky top-0 z-10 flex items-center gap-3 px-4 py-2.5 backdrop-blur"
      style={{
        background: `linear-gradient(90deg, ${c}26, rgba(5,11,20,0.92) 45%, rgba(5,11,20,0.92))`,
        boxShadow: `inset 0 -1px 0 ${c}55, inset 0 1px 0 ${c}33`,
      }}
    >
      <span className="h-2.5 w-2.5 rotate-45" style={{ background: c, boxShadow: `0 0 10px ${c}` }} />
      <span className="font-serif text-sm font-extrabold uppercase tracking-[0.3em]" style={{ color: c }}>
        {m.tiers[tier.key]?.label ?? tier.label}
      </span>
      <span className="h-px flex-1" style={{ background: `linear-gradient(90deg, ${c}88, transparent)` }} />
      <span className="font-mono text-[11px] text-text-muted">
        {count} · CLR ≥ {tier.clr_floor?.toFixed(1) ?? "—"}
      </span>
    </div>
  );
}
