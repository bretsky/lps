// Link-preview images (og:image / twitter:image, 1200×630), drawn at build time with
// next/og (satori) and written out as plain PNGs by the static export: one per player
// (app/og/player/[file]) and one for the boards and About (app/og/site.png).
//
// No player photos: they're hotlinked from Leaguepedia's CDN, and fetching ~2k of them on
// every build would be slow and rude. Fonts come from the @fontsource packages (WOFF, which
// satori reads; next/font only has WOFF2). Each family lists its latin-ext file too, which
// satori falls back to for accented handles.

import { existsSync, promises as fs } from "fs";
import path from "path";
import { ImageResponse } from "next/og";
import type { ReactNode } from "react";
import { OG_SIZE, SITE_URL } from "./site";

type Weight = 500 | 600 | 700 | 800 | 900;
const FONT_FILES: [name: string, pkg: string, weight: Weight][] = [
  ["Display", "big-shoulders-display", 900],
  ["Display", "big-shoulders-display", 800],
  ["Serif", "cinzel", 700],
  ["Sans", "barlow", 500],
  ["Sans", "barlow", 600],
];

/** node_modules/@fontsource/<pkg>, looked up from the working directory like Node does
 *  (deploy.mjs builds in .build/, which has no node_modules of its own). */
function fontsourceDir(pkg: string): string {
  for (let dir = process.cwd(); ; ) {
    const p = path.join(dir, "node_modules", "@fontsource", pkg, "files");
    if (existsSync(p)) return p;
    const up = path.dirname(dir);
    if (up === dir) throw new Error(`@fontsource/${pkg} not installed (npm install in frontend/)`);
    dir = up;
  }
}

let fonts: Promise<{ name: string; data: Buffer; weight: Weight; style: "normal" }[]> | null = null;
function loadFonts() {
  fonts ??= Promise.all(
    FONT_FILES.flatMap(([name, pkg, weight]) =>
      ["latin", "latin-ext"].map(async (subset) => ({
        name,
        weight,
        style: "normal" as const,
        data: await fs.readFile(path.join(fontsourceDir(pkg), `${pkg}-${subset}-${weight}-normal.woff`)),
      })),
    ),
  );
  return fonts;
}

/** Drops characters the bundled fonts (latin + latin-ext) don't have ("QT DIG∞"): satori would
 *  otherwise draw a box and try to download a font for them mid-build. */
export const glyphSafe = (s: string) =>
  s.replace(/[^\u0020-\u024F\u1E00-\u1EFF\u2010-\u2026]/g, "").replace(/\s{2,}/g, " ").trim();

export const OG = {
  bg: "#050b14",
  gold: "#c9a45c",
  goldBright: "#f1d58f",
  teal: "#1fd1c1",
  text: "#e9e4d8",
  muted: "#9aa3ad",
  dim: "#6b7480",
};

/** The shared frame: deco background, gold border, site mark along the bottom. */
export async function ogImage(children: ReactNode): Promise<ImageResponse> {
  const host = SITE_URL.replace(/^https?:\/\//, "");
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          background: OG.bg,
          backgroundImage: `radial-gradient(ellipse 70% 80% at 85% 100%, rgba(241,213,143,0.20), transparent 70%), radial-gradient(ellipse 90% 70% at 10% 110%, rgba(12,111,116,0.45), transparent 70%), linear-gradient(180deg, #03070d 0%, #071322 70%, #03070d 100%)`,
          fontFamily: "Sans",
          color: OG.text,
          padding: 28,
        }}
      >
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            border: `2px solid ${OG.gold}88`,
            padding: "40px 56px 28px",
          }}
        >
          <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>{children}</div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              borderTop: `1px solid ${OG.gold}55`,
              paddingTop: 18,
              fontFamily: "Serif",
              fontSize: 22,
              letterSpacing: 5,
              textTransform: "uppercase",
              color: OG.gold,
            }}
          >
            <span>CLR · LoL Esports All-Time Rankings</span>
            <span style={{ color: OG.dim, letterSpacing: 2, fontSize: 20 }}>{host}</span>
          </div>
        </div>
      </div>
    ),
    { ...OG_SIZE, fonts: await loadFonts() },
  );
}
