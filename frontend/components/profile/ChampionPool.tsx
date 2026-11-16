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
        <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          <Stat
            label={t.careerKda}
            value={cs.kills != null ? `${num(cs.kills)} / ${num(cs.deaths)} / ${num(cs.assists)}` : "—"}
            hint={cs.kda_games != null ? t.careerKdaHint(num(cs.kda_games)) : undefined}
            wide
          />
          <Stat label="KDA" value={fmt(cs.kda, 2)} hint={t.kdaHint} />
          <Stat label={t.perGame} value={kdaLine(cs)} hint={t.perGameHint} wide />
          <Stat label={t.careerCs} value={num(cs.cs)} hint={t.careerCsHint} />
          <Stat label={t.cspm} value={fmt(cs.cspm, 1)} />
        </div>
      )}

      {champs.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] border-separate border-spacing-y-1 text-xs">
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
      <td className="py-1 text-right font-mono text-text-muted">{c.games}</td>
      <td className="py-1 text-right font-mono text-text-muted">{fmtPct(c.games ? c.wins / c.games : null)}</td>
      <td className="py-1 text-right font-mono text-text-muted">{kdaLine(c)}</td>
      <td className="py-1 text-right font-mono text-text">{fmt(c.kda, 2)}</td>
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

function Stat({
  label,
  value,
  hint,
  wide = false,
}: {
  label: string;
  value: string;
  hint?: string;
  wide?: boolean;
}) {
  return (
    <div
      className={`rounded border border-border/70 bg-bg-rail px-3 py-2 ${wide ? "col-span-2" : ""}`}
      title={hint}
    >
      <div className="text-[10px] uppercase tracking-widest text-text-dim">{label}</div>
      <div className="mt-0.5 font-mono text-base font-semibold text-text">{value}</div>
    </div>
  );
}
