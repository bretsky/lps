// /og/role/<slug>.png: a role board's link-preview image (see lib/og-board.tsx).
import { boardOgImage } from "@/lib/og-board";
import { LANES, ROLE_SLUGS, laneFromSlug } from "@/lib/site";

export const dynamic = "force-static";
export const dynamicParams = false;

export function generateStaticParams() {
  return LANES.map((l) => ({ file: `${ROLE_SLUGS[l]}.png` }));
}

export async function GET(_req: Request, { params }: { params: Promise<{ file: string }> }) {
  const lane = laneFromSlug((await params).file.replace(/\.png$/, ""));
  if (!lane) return new Response("Not found", { status: 404 });
  return boardOgImage(null, lane);
}
