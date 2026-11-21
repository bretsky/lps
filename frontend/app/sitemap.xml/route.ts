// /sitemap.xml: the sitemap index (see lib/sitemap.ts); robots.txt points here.
import { sitemapIndexXml, xmlResponse } from "@/lib/sitemap";

export const dynamic = "force-static";

export async function GET() {
  return xmlResponse(await sitemapIndexXml());
}
