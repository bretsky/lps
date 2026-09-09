import type { PlayerDetail } from "@/lib/types";
import { fmt } from "@/lib/format";

// The 14 résumé categories exported by backend/src/lps/export_web.py.
// International splits into Worlds / MSI / Other, each by placement tier.
// Domestic and Awards are unchanged.
type Cat = {
  key: string;
  label: string;
  short: string;
  hint: string;
};

const WORLDS: Cat[] = [
  { key: "wlds_title", label: "Worlds Title", short: "WC", hint: "Worlds champion" },
  { key: "wlds_final", label: "Worlds Finals", short: "WF", hint: "Worlds finalist (runner-up)" },
  { key: "wlds_semi",  label: "Worlds Semis",  short: "WS", hint: "Worlds semifinalist or quarterfinalist" },
];

const MSI_CATS: Cat[] = [
  { key: "msi_title", label: "MSI Title",  short: "MC", hint: "MSI champion" },
  { key: "msi_final", label: "MSI Finals", short: "MF", hint: "MSI finalist (runner-up)" },
  { key: "msi_semi",  label: "MSI Semis",  short: "MS", hint: "MSI semifinalist" },
];

const OTHER_INTL: Cat[] = [
  { key: "othr_intl_champ", label: "Intl Title",  short: "IC", hint: "IEM / EWC / MSC / Rift Rivals champion" },
  { key: "othr_intl_final", label: "Intl Finals", short: "IF", hint: "IEM / EWC / MSC finalist" },
  { key: "othr_intl_semi",  label: "Intl Semis",  short: "IS", hint: "IEM / EWC / MSC semifinalist" },
];

const TITLES: Cat[] = [
  { key: "dom_champ", label: "Domestic Champ", short: "DC", hint: "Domestic league title" },
  { key: "dom_final", label: "Domestic Final", short: "DF", hint: "Runner-up in a domestic league" },
  { key: "dom_cup",   label: "Domestic Cup",   short: "DK", hint: "Domestic cup / secondary domestic title" },
];

const AWARDS: Cat[] = [
  { key: "mvp",     label: "MVP",     short: "MVP", hint: "Regular-season or playoff MVP" },
  { key: "allpro",  label: "All-Pro", short: "AP",  hint: "All-Pro team selection" },
];

export function ResumeGrid({ player }: { player: PlayerDetail }) {
  const rb = player.resume_breakdown ?? {};
  const totalPts = Object.values(rb).reduce((s, v) => s + (v?.pts ?? 0), 0);

  return (
    <section className="rounded-lg border border-border bg-bg-card p-5">
      <div className="mb-3 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-text-muted">
          Résumé
        </h2>
        <div className="text-xs text-text-dim">
          {fmt(totalPts, 1)} pts across{" "}
          {Object.values(rb).reduce((s, v) => s + (v?.n ?? 0), 0)} achievements
        </div>
      </div>

      <div className="space-y-4">
        <div>
          <div className="mb-1.5 text-[10px] uppercase tracking-widest text-accent-hex">
            International
          </div>
          <div className="space-y-1.5">
            <SubRow label="Worlds" cats={WORLDS} rb={rb} />
            <SubRow label="MSI"    cats={MSI_CATS} rb={rb} />
            <SubRow label="Other"  cats={OTHER_INTL} rb={rb} />
          </div>
        </div>
        <Group title="Domestic" cats={TITLES} rb={rb} tone="text-emerald-400" />
        <Group title="Awards"   cats={AWARDS} rb={rb} tone="text-accent-gold" />
      </div>
    </section>
  );
}

function SubRow({
  label,
  cats,
  rb,
}: {
  label: string;
  cats: Cat[];
  rb: PlayerDetail["resume_breakdown"];
}) {
  return (
    <div className="flex items-stretch gap-2">
      <div className="flex w-10 shrink-0 items-center justify-end text-[9px] uppercase tracking-widest text-text-dim">
        {label}
      </div>
      <div className="grid flex-1 grid-cols-3 gap-2">
        {cats.map((c) => {
          const v = rb[c.key];
          const n = v?.n ?? 0;
          const pts = v?.pts ?? 0;
          const dim = n === 0;
          return (
            <div
              key={c.key}
              title={`${c.label} — ${c.hint}`}
              className={`rounded border px-3 py-2 ${
                dim
                  ? "border-border/50 bg-bg-rail/40 opacity-50"
                  : "border-border bg-bg-rail"
              }`}
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate text-xs text-text-muted">{c.label}</span>
                <span className={`font-mono text-lg font-bold ${dim ? "text-text-dim" : "text-text"}`}>
                  {n}
                </span>
              </div>
              <div className="mt-0.5 text-[10px] text-text-dim">
                {fmt(pts, 1)} pts
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Group({
  title,
  cats,
  rb,
  tone,
}: {
  title: string;
  cats: Cat[];
  rb: PlayerDetail["resume_breakdown"];
  tone: string;
}) {
  return (
    <div>
      <div className={`mb-1.5 text-[10px] uppercase tracking-widest ${tone}`}>
        {title}
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {cats.map((c) => {
          const v = rb[c.key];
          const n = v?.n ?? 0;
          const pts = v?.pts ?? 0;
          const dim = n === 0;
          return (
            <div
              key={c.key}
              title={`${c.label} — ${c.hint}`}
              className={`rounded border px-3 py-2 ${
                dim
                  ? "border-border/50 bg-bg-rail/40 opacity-50"
                  : "border-border bg-bg-rail"
              }`}
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate text-xs text-text-muted">{c.label}</span>
                <span className={`font-mono text-lg font-bold ${dim ? "text-text-dim" : "text-text"}`}>
                  {n}
                </span>
              </div>
              <div className="mt-0.5 text-[10px] text-text-dim">
                {fmt(pts, 1)} pts
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
