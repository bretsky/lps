"use client";

import type { BoxLine, ChampionLine, PlayerDetail } from "@/lib/types";
import { fmt, fmtPct } from "@/lib/format";
import { ChampionIcon } from "@/components/ui/ChampionIcon";
import { useT } from "@/lib/i18n";

// Champion pool + career box score. Champions are ranked by the LPS earned on them: every
// scored game's exact share of its season's LPS (season.build_player_ratings game credit), so
// the full champion list sums to CareerLPS. Box-score stats cover the same LPS-scored games.

const num = (n: number | null | undefined) =>
  n == null ? "—" : Math.round(n).toLocaleString("en-US");

function kdaLine(b: BoxLine): string {
  if (b.kda_games == null || b.kills == null) return "—";
  const g = b.kda_games || 1;
  return `${fmt(b.kills / g, 1)} / ${fmt((b.deaths ?? 0) / g, 1)} / ${fmt((b.assists ?? 0) / g, 1)}`;
}

export function ChampionPool({ player }: { player: PlayerDetail }) {
  const m = useT();
  const t = m.champs;
  const champs = player.champions ?? [];
  const cs = player.career_stats;
  if (!champs.length && !cs) return null;

  const total = player.career_lps.total_score ?? cs?.lps ?? null;
  const max = Math.max(...champs.map((c) => Math.max(0, c.lps)), 1e-9);

  return (
    <section className="deco-panel">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="deco-title">{t.title}</h2>
        {cs && <span className="text-[10px] uppercase tracking-widest text-text-dim">{t.summary(cs.n_champions)}</span>}
      </div>

      {cs && (
        // phones: totals on their own row, then per game + KDA, then CS + CS/min (3 columns);
        // lg: all five in one row of 7
        <div className="mb-4 grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          <Stat
            label={t.careerKda}
            value={cs.kills != null ? `${num(cs.kills)} / ${num(cs.deaths)} / ${num(cs.assists)}` : "—"}
            hint={cs.kda_games != null ? t.careerKdaHint(num(cs.kda_games)) : undefined}
            className="col-span-3 sm:col-span-2"
          />
          <Stat label={t.perGame} value={kdaLine(cs)} hint={t.perGameHint} className="col-span-2" />
          <Stat label="KDA" value={fmt(cs.kda, 2)} hint={t.kdaHint} />
          <Stat label={t.careerCs} value={num(cs.cs)} hint={t.careerCsHint} className="col-span-2 sm:col-span-1" />
          <Stat label={t.cspm} value={fmt(cs.cspm, 1)} />
        </div>
      )}

      {champs.length > 0 && (
        <ol className="space-y-1 sm:hidden">
          {champs.map((c, i) => (
            <ChampionItem key={c.champion} c={c} i={i} max={max} total={total} />
          ))}
        </ol>
      )}

      {champs.length > 0 && (
        <div className="hidden overflow-x-auto sm:block">
          <table className="w-full min-w-[520px] border-separate border-spacing-y-1 whitespace-nowrap text-xs">
            <thead>
              <tr className="text-left text-[10px] uppercase tracking-widest text-text-dim">
                <th className="w-6 pb-1 font-normal">#</th>
                <th className="pb-1 font-normal">{t.col.champion}</th>
                <th className="pb-1 text-right font-normal">{t.col.games}</th>
                <th className="pb-1 text-right font-normal">{t.col.winPct}</th>
                <th className="pb-1 text-right font-normal">{t.col.kda}</th>
                <th className="pb-1 text-right font-normal">KDA</th>
                <th className="pb-1 pl-4 font-normal">{t.col.lps}</th>
              </tr>
            </thead>
            <tbody>
              {champs.map((c, i) => (
                <ChampionRow key={c.champion} c={c} i={i} max={max} total={total} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function ChampionRow({
  c,
  i,
  max,
  total,
}: {
  c: ChampionLine;
  i: number;
  max: number;
  total: number | null;
}) {
  const w = (Math.max(0, c.lps) / max) * 100;
  const share = total && total > 0 ? c.lps / total : null;
  return (
    <tr className="bg-bg-rail/60">
      <td className="rounded-l py-1 pl-2 font-mono text-text-dim">{i + 1}</td>
      <td className="py-1">
        <div className="flex items-center gap-2">
          <ChampionIcon name={c.champion} size={28} ring="rgba(201,164,92,0.55)" />
          <span className="font-semibold text-text">{c.champion}</span>
        </div>
      </td>
      <td className="py-1 pl-3 text-right font-mono text-text-muted">{c.games}</td>
      <td className="py-1 pl-3 text-right font-mono text-text-muted">{fmtPct(c.games ? c.wins / c.games : null)}</td>
      <td className="py-1 pl-3 text-right font-mono text-text-muted">{kdaLine(c)}</td>
      <td className="py-1 pl-3 text-right font-mono text-text">{fmt(c.kda, 2)}</td>
      <td className="w-[34%] rounded-r py-1 pl-4 pr-2">
        <div className="flex items-center gap-2">
          <div className="h-1.5 flex-1 overflow-hidden rounded-sm bg-black/40">
            <div className="h-full bg-accent-hex/70" style={{ width: `${w}%` }} />
          </div>
          <span className="w-10 text-right font-mono text-text">{fmt(c.lps, 1)}</span>
          <span className="w-10 text-right font-mono text-[10px] text-text-dim">
            {share != null ? `${(share * 100).toFixed(0)}%` : ""}
          </span>
        </div>
      </td>
    </tr>
  );
}

/** One champion on a phone, where the table's seven columns don't fit: name and LPS earned on
 *  top, the bar, then games / win rate / K/D/A / KDA as a wrapping line. */
function ChampionItem({
  c,
  i,
  max,
  total,
}: {
  c: ChampionLine;
  i: number;
  max: number;
  total: number | null;
}) {
  const m = useT();
  const w = (Math.max(0, c.lps) / max) * 100;
  const share = total && total > 0 ? c.lps / total : null;
  return (
    <li className="flex items-center gap-2.5 rounded bg-bg-rail/60 px-2 py-1.5">
      <span className="w-4 shrink-0 text-right font-mono text-[10px] text-text-dim">{i + 1}</span>
      <ChampionIcon name={c.champion} size={32} ring="rgba(201,164,92,0.55)" />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="min-w-0 flex-1 truncate text-sm font-semibold text-text">{c.champion}</span>
          <span className="font-mono text-xs text-text">{fmt(c.lps, 1)}</span>
          {share != null && (
            <span className="w-7 text-right font-mono text-[10px] text-text-dim">{`${(share * 100).toFixed(0)}%`}</span>
          )}
        </div>
        <div className="mt-1 h-1 overflow-hidden rounded-sm bg-black/40">
          <div className="h-full bg-accent-hex/70" style={{ width: `${w}%` }} />
        </div>
        <div className="mt-1 flex flex-wrap gap-x-2 font-mono text-[10px] text-text-muted">
          <span className="whitespace-nowrap">{m.common.games(String(c.games))}</span>
          <span className="whitespace-nowrap">{m.common.winRate(fmtPct(c.games ? c.wins / c.games : null))}</span>
          <span className="whitespace-nowrap">{kdaLine(c)}</span>
          <span className="whitespace-nowrap text-text">{m.common.kda(fmt(c.kda, 2))}</span>
        </div>
      </div>
    </li>
  );
}

function Stat({
  label,
  value,
  hint,
  className = "",
}: {
  label: string;
  value: string;
  hint?: string;
  className?: string;
}) {
  return (
    <div
      className={`rounded border border-border/70 bg-bg-rail px-3 py-2 ${className}`}
      title={hint}
    >
      <div className="text-[10px] uppercase tracking-widest text-text-dim">{label}</div>
      <div className="mt-0.5 font-mono text-base font-semibold text-text">{value}</div>
    </div>
  );
}
