import type { Honor, PlayerDetail } from "@/lib/types";
import { fmt } from "@/lib/format";
import { MEDAL_COLOR } from "@/lib/theme";
import { leagueIcon } from "@/lib/icons";
import { EventMark, LeagueMark } from "@/components/ui/Marks";
import { CupDomestic, CupIntl, Laurel, Shield, Star } from "./AchievementIcons";

// The 14 résumé categories exported by backend/src/lps/export_web.py, laid out
// as a trophy wall: one row per competition, columns = champion / finalist /
// semifinalist, each tile tinted by its medal.
type Medal = "gold" | "silver" | "bronze";
type Cat = { key: string; label: string; hint: string; medal?: Medal };

type Row = { label: string; icon: React.ReactNode; cats: Cat[] };

const PLACES = (prefix: string, keys: [string, string, string], hint: string): Cat[] => [
  { key: keys[0], label: "Champion", medal: "gold", hint: `${prefix} champion` },
  { key: keys[1], label: "Finalist", medal: "silver", hint: `${prefix} finalist (runner-up)` },
  { key: keys[2], label: "Semis", medal: "bronze", hint: `${prefix} ${hint}` },
];

function primaryLeague(player: PlayerDetail): string | null {
  const counts = new Map<string, number>();
  for (const h of player.honors ?? []) {
    if (h.kind === "domestic" && h.league) counts.set(h.league, (counts.get(h.league) ?? 0) + 1);
  }
  let best: string | null = null;
  for (const [k, v] of counts) if (!best || v > (counts.get(best) ?? 0)) best = k;
  return best ?? player.current_league;
}

export function ResumeGrid({ player }: { player: PlayerDetail }) {
  const rb = player.resume_breakdown ?? {};
  const totalPts = Object.values(rb).reduce((s, v) => s + (v?.pts ?? 0), 0);
  const totalN = Object.values(rb).reduce((s, v) => s + (v?.n ?? 0), 0);
  const league = primaryLeague(player);

  const rows: Row[] = [
    {
      label: "Worlds",
      icon: <EventMark event="worlds" size={26} />,
      cats: PLACES("Worlds", ["wlds_title", "wlds_final", "wlds_semi"], "semifinalist or quarterfinalist"),
    },
    {
      label: "MSI",
      icon: <EventMark event="msi" size={26} />,
      cats: PLACES("MSI", ["msi_title", "msi_final", "msi_semi"], "semifinalist"),
    },
    {
      label: "Other Intl",
      icon: <CupIntl className="h-6 w-6 text-gold" />,
      cats: PLACES("IEM / EWC / MSC / First Stand / Rift Rivals", ["othr_intl_champ", "othr_intl_final", "othr_intl_semi"], "semifinalist"),
    },
    {
      label: "League",
      icon: leagueIcon(league) ? <LeagueMark league={league} size={24} /> : <CupDomestic className="h-6 w-6 text-gold" />,
      cats: [
        { key: "dom_champ", label: "Champion", medal: "gold", hint: "Domestic league title" },
        { key: "dom_final", label: "Finalist", medal: "silver", hint: "Runner-up in a domestic league" },
        { key: "dom_cup", label: "Cup", medal: "bronze", hint: "Domestic cup / secondary domestic title" },
      ],
    },
    {
      label: "Awards",
      icon: <Laurel className="h-6 w-6 text-gold" />,
      cats: [
        { key: "mvp", label: "MVP", hint: "Regular-season or playoff MVP" },
        { key: "allpro", label: "All-Pro", hint: "All-Pro team selection" },
      ],
    },
  ];

  return (
    <section className="deco-panel">
      <div className="mb-4 flex items-baseline justify-between gap-4">
        <h2 className="deco-title flex-1">Résumé</h2>
        <div className="shrink-0 font-mono text-xs text-text-dim">
          {fmt(totalPts, 1)} pts · {totalN} achievements
        </div>
      </div>

      <div className="space-y-2">
        {rows.map((row) => (
          <div key={row.label} className="flex items-stretch gap-3">
            <div className="flex w-24 shrink-0 items-center gap-2">
              <span className="flex w-7 justify-center">{row.icon}</span>
              <span className="font-serif text-[11px] font-bold uppercase tracking-[0.14em] text-text-muted">
                {row.label}
              </span>
            </div>
            <div className="grid flex-1 grid-cols-3 gap-2">
              {row.cats.map((c) => (
                <Tile key={c.key} cat={c} n={rb[c.key]?.n ?? 0} pts={rb[c.key]?.pts ?? 0} />
              ))}
            </div>
          </div>
        ))}
      </div>

      <TrophyCase honors={player.honors ?? []} />
    </section>
  );
}

function Tile({ cat, n, pts }: { cat: Cat; n: number; pts: number }) {
  const dim = n === 0;
  const color = cat.medal ? MEDAL_COLOR[cat.medal] : cat.key === "mvp" ? "#f1d58f" : "#1fd1c1";
  const Icon = cat.key === "mvp" ? Star : cat.key === "allpro" ? Shield : null;
  return (
    <div
      title={`${cat.hint}`}
      className={`relative flex items-center justify-between gap-2 px-3 py-1.5 ${dim ? "opacity-35" : ""}`}
      style={{
        clipPath: "polygon(6px 0, 100% 0, 100% calc(100% - 6px), calc(100% - 6px) 100%, 0 100%, 0 6px)",
        background: dim ? "rgba(255,255,255,0.02)" : `linear-gradient(90deg, ${color}1f, rgba(5,11,20,0.4))`,
        boxShadow: `inset 2px 0 0 ${dim ? "#3a4a55" : color}`,
      }}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-1 truncate text-[10px] font-bold uppercase tracking-[0.16em]" style={{ color: dim ? undefined : color }}>
          {Icon && <Icon className="h-3 w-3" />}
          {cat.label}
        </div>
        <div className="font-mono text-[10px] text-text-dim">{fmt(pts, 1)} pts</div>
      </div>
      <span className={`font-display text-2xl font-extrabold leading-none ${dim ? "text-text-dim" : "text-text"}`}>{n}</span>
    </div>
  );
}

const KIND_ORDER: Honor["kind"][] = ["worlds", "msi", "first_stand", "intl", "domestic", "cup"];
const KIND_NAME: Record<Honor["kind"], string> = {
  worlds: "Worlds",
  msi: "MSI",
  first_stand: "First Stand",
  intl: "Intl",
  domestic: "League",
  cup: "Cup",
};

/** Every podium finish, year by year, with the event's / league's own mark. */
function TrophyCase({ honors }: { honors: Honor[] }) {
  if (!honors.length) return null;
  const byYear = new Map<number, Honor[]>();
  for (const h of honors) byYear.set(h.year, [...(byYear.get(h.year) ?? []), h]);
  const years = [...byYear.keys()].sort((a, b) => b - a);
  return (
    <div className="mt-5">
      <div className="deco-rule mb-3 font-serif text-[10px] font-bold uppercase tracking-[0.3em] text-gold">
        <span>Trophy case · {honors.filter((h) => h.medal === "gold").length} titles</span>
      </div>
      <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2">
        {years.map((y) => (
          <div key={y} className="flex items-start gap-3">
            <span className="w-10 shrink-0 pt-1 font-display text-lg font-extrabold leading-none text-gold">{y}</span>
            <div className="flex flex-wrap gap-1.5">
              {byYear
                .get(y)!
                .sort((a, b) => KIND_ORDER.indexOf(a.kind) - KIND_ORDER.indexOf(b.kind))
                .map((h, i) => (
                  <HonorChip key={i} h={h} />
                ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function HonorChip({ h }: { h: Honor }) {
  const color = MEDAL_COLOR[h.medal];
  const place = h.medal === "gold" ? "Champion" : h.medal === "silver" ? "Finalist" : "Semis";
  const name = h.kind === "domestic" ? h.league ?? "League" : h.kind === "intl" || h.kind === "cup" ? h.event ?? KIND_NAME[h.kind] : KIND_NAME[h.kind];
  const mark =
    h.kind === "worlds" || h.kind === "msi" || h.kind === "first_stand" ? (
      <EventMark event={h.kind} medal={h.medal} size={16} />
    ) : h.kind === "domestic" && leagueIcon(h.league) ? (
      <LeagueMark league={h.league} size={14} />
    ) : h.kind === "intl" ? (
      <CupIntl className="h-4 w-4" style={{ color }} />
    ) : (
      <CupDomestic className="h-4 w-4" style={{ color }} />
    );
  return (
    <span
      title={h.page ?? undefined}
      className="inline-flex items-center gap-1.5 rounded-full py-0.5 pl-1 pr-2 text-[10px]"
      style={{ boxShadow: `inset 0 0 0 1px ${color}66`, background: `${color}10` }}
    >
      {mark}
      <span className="font-semibold uppercase tracking-wide text-text-muted">{name}</span>
      <span className="font-bold" style={{ color }}>{place}</span>
    </span>
  );
}
