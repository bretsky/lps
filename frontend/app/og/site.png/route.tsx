// /og/site.png: the link-preview image for today's all-roles board and About (see lib/og-board.tsx).
import { boardOgImage } from "@/lib/og-board";

export const dynamic = "force-static";

export async function GET() {
  return boardOgImage(null, "all");
}
