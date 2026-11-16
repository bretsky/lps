// /og/asof/<year>.png: a past season's board link-preview image (see lib/og-board.tsx).
import { boardOgImage } from "@/lib/og-board";
import { loadMeta } from "@/lib/data";

export const dynamic = "force-static";
export const dynamicParams = false;

export async function generateStaticParams() {
  return ((await loadMeta()).asof_years ?? []).map((y) => ({ file: `${y}.png` }));
}

export async function GET(_req: Request, { params }: { params: Promise<{ file: string }> }) {
  const year = Number((await params).file.replace(/\.png$/, ""));
  if (!((await loadMeta()).asof_years ?? []).includes(year)) return new Response("Not found", { status: 404 });
  return boardOgImage(year, "all");
}
