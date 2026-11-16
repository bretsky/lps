// /og/player/<slug>.png: a player's link-preview image (see lib/og.tsx). Prerendered for
// every rated player; the ".png" in the URL makes Pages serve it as an image.
import { glyphSafe, ogImage, OG } from "@/lib/og";
import { loadIndex, loadLane } from "@/lib/data";
import { displayName } from "@/lib/format";
import { en } from "@/lib/i18n/en";
import { LANES, ROLE_SINGULAR } from "@/lib/site";
import { TIER_COLORS } from "@/lib/theme";
import type { IndexRow, Lane } from "@/lib/types";

export const dynamic = "force-static";
export const dynamicParams = false;

export async function generateStaticParams() {
  return (await loadIndex()).filter((r) => r.slug).map((r) => ({ file: `${r.slug}.png` }));
}

// Built once per build worker, not once per image.
let laneRanks: Promise<Map<string, number>> | null = null;
function laneRankMap() {
  laneRanks ??= Promise.all(LANES.map((l) => loadLane(l).catch(() => [] as IndexRow[]))).then((lists) => {
    const m = new Map<string, number>();
    lists.forEach((rows, i) =>
      [...rows].sort((a, b) => b.clr - a.clr).forEach((r, j) => m.set(`${LANES[i]}:${r.slug}`, j + 1)),
    );
    return m;
  });
  return laneRanks;
}
let index: Promise<Map<string, IndexRow>> | null = null;
const indexMap = () => (index ??= loadIndex().then((rows) => new Map(rows.map((r) => [r.slug, r]))));

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export async function GET(_req: Request, { params }: { params: Promise<{ file: string }> }) {
  const slug = (await params).file.replace(/\.png$/, "");
  const r = (await indexMap()).get(slug);
  if (!r) return new Response("Not found", { status: 404 });
  const lane: Lane | null = r.position;
  const laneRank = lane ? (await laneRankMap()).get(`${lane}:${slug}`) ?? null : null;

  const name = glyphSafe(displayName(r.playername)) || r.slug;
  const realName = r.real_name ? glyphSafe(r.real_name) : "";
  const nameSize = name.length <= 7 ? 168 : name.length <= 10 ? 132 : name.length <= 14 ? 100 : 76;
  const color = TIER_COLORS[r.tier];
  const span = r.first_year === r.last_year ? `${r.first_year}` : `${r.first_year}–${r.last_year}`;
  const team = r.current_team ? `${glyphSafe(r.current_team)}${r.current_league ? ` (${r.current_league})` : ""}` : null;
  const facts = [lane ? cap(ROLE_SINGULAR[lane]) : null, team, span].filter(Boolean).join("  ·  ");
  const t = r.titles ?? {};
  const pills = [
    t.worlds ? `${t.worlds}× Worlds` : null,
    t.msi ? `${t.msi}× MSI` : null,
    t.first_stand ? `${t.first_stand}× First Stand` : null,
    t.ewc ? `${t.ewc}× EWC` : null,
    t.domestic ? `${t.domestic}× ${t.league ?? "League"}` : null,
  ].filter((x): x is string => !!x);

  return ogImage(
    <div style={{ flex: 1, display: "flex" }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", minWidth: 0 }}>
        <div style={{ display: "flex", fontFamily: "Serif", fontSize: 30, letterSpacing: 8, color: OG.gold }}>
          {`#${r.rank} ALL-TIME`}
        </div>
        <div
          style={{
            display: "flex",
            fontFamily: "Display",
            fontWeight: 900,
            fontSize: nameSize,
            lineHeight: 0.95,
            textTransform: "uppercase",
            color: OG.text,
            marginTop: 6,
          }}
        >
          {name}
        </div>
        {realName && (
          <div style={{ display: "flex", fontSize: 32, fontWeight: 500, color: OG.muted, marginTop: 8 }}>
            {realName}
          </div>
        )}
        <div style={{ display: "flex", fontFamily: "Serif", fontSize: 24, letterSpacing: 3, color: OG.text, marginTop: 18, textTransform: "uppercase" }}>
          {facts}
        </div>
        {pills.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 26 }}>
            {pills.map((p) => (
              <div
                key={p}
                style={{
                  display: "flex",
                  border: `1.5px solid ${OG.gold}`,
                  color: OG.goldBright,
                  padding: "6px 16px",
                  fontSize: 26,
                  fontWeight: 600,
                }}
              >
                {p}
              </div>
            ))}
          </div>
        )}
      </div>
      <div
        style={{
          // Runs out over the frame's right padding to the gold border, so the score centres
          // between the divider and the border rather than hugging the divider.
          width: 386,
          marginRight: -56,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          borderLeft: `1px solid ${OG.gold}55`,
          marginLeft: 36,
        }}
      >
        <div style={{ display: "flex", fontFamily: "Serif", fontSize: 26, letterSpacing: 8, color: OG.muted }}>CLR</div>
        <div style={{ display: "flex", fontFamily: "Display", fontWeight: 900, fontSize: 176, lineHeight: 1, color }}>
          {r.clr.toFixed(1)}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 8 }}>
          <div style={{ width: 16, height: 16, background: color, transform: "rotate(45deg)" }} />
          <div style={{ display: "flex", fontFamily: "Serif", fontSize: 30, letterSpacing: 6, color, textTransform: "uppercase" }}>
            {en.tiers[r.tier].one}
          </div>
        </div>
        {laneRank && lane && (
          <div style={{ display: "flex", fontSize: 26, fontWeight: 500, color: OG.muted, marginTop: 22 }}>
            {`#${laneRank} ${ROLE_SINGULAR[lane]}`}
          </div>
        )}
        {r.hall_of_legends && (
          <div style={{ display: "flex", fontSize: 22, fontWeight: 600, color: OG.teal, marginTop: 10, letterSpacing: 2 }}>
            {`HALL OF LEGENDS${r.hol_year ? ` ${r.hol_year}` : ""}`}
          </div>
        )}
      </div>
    </div>,
  );
}
