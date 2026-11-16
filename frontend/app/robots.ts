// /robots.txt: crawl every page (not the data files behind them), and point at the sitemap.
import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

export const dynamic = "force-static";

export default function robots(): MetadataRoute.Robots {
  return {
    // /api/ = the board's row lists; *.txt = the RSC payloads behind client-side navigation.
    rules: [{ userAgent: "*", allow: "/", disallow: ["/api/", "/*.txt"] }],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
