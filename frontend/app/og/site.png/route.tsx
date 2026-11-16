// /og/site.png: the link-preview image for the boards and About (see lib/og.tsx).
import { glyphSafe, ogImage, OG } from "@/lib/og";
import { loadIndex, loadMeta } from "@/lib/data";
import { displayName } from "@/lib/format";
import { TIER_COLORS } from "@/lib/theme";

export const dynamic = "force-static";

export async function GET() {
  const [rows, meta] = await Promise.all([loadIndex(), loadMeta()]);
  const top = [...rows].sort((a, b) => a.rank - b.rank).slice(0, 5);
  return ogImage(
    <div style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center" }}>
      <div style={{ display: "flex", fontFamily: "Serif", fontSize: 28, letterSpacing: 10, color: OG.gold }}>
        LEAGUE OF LEGENDS ESPORTS
      </div>
      <div style={{ display: "flex", fontFamily: "Display", fontWeight: 900, fontSize: 128, lineHeight: 1, marginTop: 8 }}>
        ALL-TIME RANKINGS
      </div>
      <div style={{ display: "flex", fontSize: 30, fontWeight: 500, color: OG.muted, marginTop: 12 }}>
        {`${rows.length.toLocaleString("en-US")} pros, ${meta.years[0]}–${meta.years[1]}, rated by Career Legend Rating`}
      </div>
      <div style={{ display: "flex", gap: 34, marginTop: 40 }}>
        {top.map((r) => (
          <div key={r.slug} style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <span style={{ fontFamily: "Display", fontWeight: 900, fontSize: 44, color: TIER_COLORS[r.tier] }}>{r.rank}</span>
            <span style={{ fontFamily: "Display", fontWeight: 800, fontSize: 44, textTransform: "uppercase" }}>
              {glyphSafe(displayName(r.playername))}
            </span>
          </div>
        ))}
      </div>
    </div>,
  );
}
