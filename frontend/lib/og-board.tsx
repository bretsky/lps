// The link-preview image of a board (see lib/og.tsx): today's all-roles board
// (/og/site.png, also About's), a role board (/og/role/<slug>.png) or a past season
// (/og/asof/<year>.png). Its top five are the same rows the page's description lists.
import type { BoardView } from "./board";
import { loadBoardPage, loadMeta } from "./data";
import { displayName } from "./format";
import { glyphSafe, ogImage, OG } from "./og";
import { ROLE_PLURAL, rolePluralLower } from "./site";
import { TIER_COLORS } from "./theme";

export async function boardOgImage(asOf: number | null, view: BoardView) {
  const [data, meta] = await Promise.all([loadBoardPage(asOf, view), loadMeta()]);
  const [y0, y1] = meta.years;
  const count = (n: number) => n.toLocaleString("en-US");
  const kicker = asOf !== null ? "ALL-TIME LEAGUE OF LEGENDS ESPORTS" : "LEAGUE OF LEGENDS ESPORTS";
  const heading =
    asOf !== null ? `RANKINGS AS OF ${asOf}` : view === "all" ? "ALL-TIME RANKINGS" : `GREATEST ${ROLE_PLURAL[view].toUpperCase()}`;
  const sub =
    view === "all"
      ? `${count(data.ratedCount)} pros, ${y0}–${asOf ?? y1}, rated by Career Legend Rating`
      : `${count(data.summaries[view].total)} ${rolePluralLower(view)}, ${y0}–${y1}, rated by Career Legend Rating`;
  const top = data.rows.slice(0, 5);
  return ogImage(
    <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center" }}>
      <div style={{ display: "flex", fontFamily: "Serif", fontSize: 28, letterSpacing: 10, color: OG.gold }}>{kicker}</div>
      <div style={{ display: "flex", fontFamily: "Display", fontWeight: 900, fontSize: heading.length > 18 ? 112 : 128, lineHeight: 1, marginTop: 8 }}>
        {heading}
      </div>
      <div style={{ display: "flex", fontSize: 30, fontWeight: 500, color: OG.muted, marginTop: 12 }}>{sub}</div>
      <div style={{ display: "flex", gap: 34, marginTop: 40 }}>
        {top.map((r, i) => (
          <div key={r.slug} style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <span style={{ fontFamily: "Display", fontWeight: 900, fontSize: 44, color: TIER_COLORS[r.tier] }}>{i + 1}</span>
            <span style={{ fontFamily: "Display", fontWeight: 800, fontSize: 44, textTransform: "uppercase" }}>
              {glyphSafe(displayName(r.playername))}
            </span>
          </div>
        ))}
      </div>
    </div>,
  );
}
