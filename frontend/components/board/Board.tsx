"use client";

import { useMemo, useState } from "react";
import type { IndexRow, Lane, TierMeta } from "@/lib/types";
import { PlayerRow } from "./PlayerRow";
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
    if (qn) out = out.filter((r) => r.playername.toLowerCase().includes(qn));
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
    <div className="mx-auto max-w-6xl px-4 pb-16 pt-8">
      <header className="mb-6">
        <h1 className="text-3xl font-bold tracking-tight">LPS All-Time Rankings</h1>
        <p className="mt-1 text-sm text-text-muted">
          Career Legend Rating (CLR) — a holistic all-time score blending career bulk, per-year
          pace, peak, and résumé. Provisional beta weights.
        </p>
      </header>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          type="text"
          placeholder="Search player…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          className="w-56 rounded border border-border bg-bg-card px-3 py-1.5 text-sm placeholder:text-text-dim focus:border-accent-hex/60 focus:outline-none"
        />
        <div className="flex items-center gap-1 rounded border border-border bg-bg-card p-0.5 text-xs">
          {LANE_FILTERS.map((l) => (
            <button
              key={l}
              onClick={() => setLane(l)}
              className={`rounded px-2 py-1 uppercase tracking-wide transition ${
                lane === l ? "bg-accent-hex/20 text-accent-hex" : "text-text-muted hover:text-text"
              }`}
            >
              {l === "all" ? "All" : LANE_LABELS[l]}
            </button>
          ))}
        </div>
        <select
          value={league}
          onChange={(e) => setLeague(e.target.value)}
          className="rounded border border-border bg-bg-card px-2 py-1.5 text-xs"
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
          className="ml-auto rounded border border-border bg-bg-card px-2 py-1.5 text-xs"
        >
          {(Object.keys(SORT_LABELS) as SortKey[]).map((k) => (
            <option key={k} value={k}>
              Sort: {SORT_LABELS[k]}
            </option>
          ))}
        </select>
      </div>

      <div className="mb-2 text-xs text-text-dim">
        {filtered.length} player{filtered.length === 1 ? "" : "s"}
      </div>

      <div className="rounded-lg border border-border bg-bg-card">
        {grouped ? (
          <div>
            {tiers.map((t) => {
              const players = grouped.get(t.key) ?? [];
              if (!players.length) return null;
              return (
                <section key={t.key}>
                  <div
                    className="sticky top-0 z-10 flex items-baseline justify-between border-y border-border/60 px-4 py-2 text-sm font-semibold uppercase tracking-widest backdrop-blur"
                    style={{
                      color: t.color,
                      backgroundColor: "#111821e6",
                      backgroundImage: `linear-gradient(${t.color}22, ${t.color}22)`,
                      boxShadow: `inset 3px 0 0 0 ${t.color}`,
                    }}
                  >
                    <span>{t.label}</span>
                    <span className="font-mono text-xs opacity-70">
                      {players.length} · CLR ≥ {t.clr_floor?.toFixed(1) ?? "—"}
                    </span>
                  </div>
                  <div style={{ backgroundColor: `${t.color}0a` }}>
                    {players.map((r) => (
                      <PlayerRow key={r.slug} row={r} maxClr={maxClr} />
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        ) : (
          <div>
            {filtered.map((r) => (
              <PlayerRow key={r.slug} row={r} maxClr={maxClr} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
