"use client";

import { useMemo, useState } from "react";
import type { IndexRow, Lane, TierMeta } from "@/lib/types";
import { PlayerRow, ROW_GRID } from "./PlayerRow";
import { LANE_LABELS } from "@/lib/format";

type SortKey = "clr" | "total_score" | "peak_lps" | "resume_bonus" | "n_years";

const SORT_LABELS: Record<SortKey, string> = {
  clr: "CLR",
  total_score: "CareerLPS",
  peak_lps: "PeakLPS",
  resume_bonus: "Résumé",
  n_years: "Longevity",
};

const LANE_FILTERS: (Lane | "all")[] = ["all", "top", "jng", "mid", "bot", "sup"];

interface Props {
  rows: IndexRow[];
  laneRows: Record<Lane, IndexRow[]>;
  tiers: TierMeta[];
}

export default function Board({ rows, laneRows, tiers }: Props) {
  const [q, setQ] = useState("");
  const [lane, setLane] = useState<Lane | "all">("all");
  const [league, setLeague] = useState<string>("all");
  const [sortKey, setSortKey] = useState<SortKey>("clr");

  // When a lane is picked, we render the per-lane file instead of filtering
  // the global index. That way each row's `clr` (and rank/tier) reflects the
  // player's career *as if only their seasons in that lane existed* -- e.g.
  // Xiaohu appears in both Mid and Top with different CLR values.
  const source = lane === "all" ? rows : laneRows[lane] ?? [];

  const maxClr = useMemo(
    () => source.reduce((m, r) => (r.clr > m ? r.clr : m), 0),
    [source],
  );

  const leagues = useMemo(() => {
    const seen = new Set<string>();
    for (const r of source) if (r.current_league) seen.add(r.current_league);
    return ["all", ...Array.from(seen).sort()];
  }, [source]);

  const filtered = useMemo(() => {
    const qn = q.trim().toLowerCase();
    let out = source;
    if (qn)
      out = out.filter(
        (r) => r.playername.toLowerCase().includes(qn) || (r.real_name ?? "").toLowerCase().includes(qn),
      );
    if (league !== "all") out = out.filter((r) => r.current_league === league);
    out = [...out].sort((a, b) => (b[sortKey] ?? -Infinity) - (a[sortKey] ?? -Infinity));
    // Re-rank within the filtered view so ranks read 1..N.
    return out.map((r, i) => ({ ...r, filteredRank: i + 1 }));
  }, [source, q, league, sortKey]);

  // Group filtered rows by tier only when sorting by CLR (native ordering);
  // otherwise show a flat list.
  const grouped = useMemo(() => {
    if (sortKey !== "clr" || q.trim()) return null;
    const groups = new Map<string, typeof filtered>();
    for (const t of tiers) groups.set(t.key, []);
    for (const r of filtered) {
      const arr = groups.get(r.tier) ?? [];
      arr.push(r);
      groups.set(r.tier, arr);
    }
    return groups;
  }, [filtered, tiers, sortKey, q]);

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
              {l === "all" ? "All Roles" : LANE_LABELS[l]}
              <span
                className={`absolute inset-x-0 bottom-0 h-[2px] transition-opacity ${active ? "opacity-100" : "opacity-0"}`}
                style={{ background: "linear-gradient(90deg, transparent, #f1d58f, transparent)", boxShadow: "0 0 8px #c9a45c" }}
              />
            </button>
          );
        })}
        <div className="ml-auto flex flex-wrap items-center gap-2 pb-2">
          <input
            type="text"
            placeholder="Search player or name…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            className="deco-control w-52 px-3 py-1.5 text-sm placeholder:text-text-dim focus:border-teal focus:outline-none"
          />
          <select
            value={league}
            onChange={(e) => setLeague(e.target.value)}
            className="deco-control px-2 py-1.5 text-xs uppercase tracking-wider"
          >
            {leagues.map((l) => (
              <option key={l} value={l}>
                {l === "all" ? "All leagues" : l}
              </option>
            ))}
          </select>
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="deco-control px-2 py-1.5 text-xs uppercase tracking-wider"
          >
            {(Object.keys(SORT_LABELS) as SortKey[]).map((k) => (
              <option key={k} value={k}>
                Sort · {SORT_LABELS[k]}
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
        <div>Player</div>
        <div className="hidden md:block">Role</div>
        <div className="hidden lg:block">Career</div>
        <div className="hidden sm:block">Titles</div>
        <div className="text-right">CLR</div>
        <div className="hidden lg:block text-right">Peak</div>
      </div>

      <div className="deco-panel !p-0">
        <div>
          {grouped
            ? tiers.map((t) => {
                const players = grouped.get(t.key) ?? [];
                if (!players.length) return null;
                return (
                  <section key={t.key}>
                    <TierBanner tier={t} count={players.length} />
                    {players.map((r) => (
                      <PlayerRow key={r.slug} row={r} maxClr={maxClr} />
                    ))}
                  </section>
                );
              })
            : filtered.map((r) => <PlayerRow key={r.slug} row={r} maxClr={maxClr} />)}
        </div>
      </div>
      <div className="mt-3 text-right font-mono text-[11px] text-text-dim">
        {filtered.length} player{filtered.length === 1 ? "" : "s"}
      </div>
    </div>
  );
}

/** Tier divider: a lozenge, engraved tier name, and a rule in the tier's colour. */
function TierBanner({ tier, count }: { tier: TierMeta; count: number }) {
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
        {tier.label}
      </span>
      <span className="h-px flex-1" style={{ background: `linear-gradient(90deg, ${c}88, transparent)` }} />
      <span className="font-mono text-[11px] text-text-muted">
        {count} · CLR ≥ {tier.clr_floor?.toFixed(1) ?? "—"}
      </span>
    </div>
  );
}
