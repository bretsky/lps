// /sitemaps/<name>.xml: one file of the sitemap index (see lib/sitemap.ts).
import { SITEMAP_FILES, sitemapXml, xmlResponse } from "@/lib/sitemap";

export const dynamic = "force-static";
export const dynamicParams = false;

export function generateStaticParams() {
  return SITEMAP_FILES.map((f) => ({ file: `${f}.xml` }));
}

export async function GET(_req: Request, { params }: { params: Promise<{ file: string }> }) {
  const body = await sitemapXml((await params).file.replace(/\.xml$/, ""));
  return body === null ? new Response("Not found", { status: 404 }) : xmlResponse(body);
}
