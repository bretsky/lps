// The sitemaps: /sitemap.xml is an index of smaller files in /sitemaps/, one for the boards and
// About in every language and one per language for the profiles (~2k URLs each), so each file
// stays small and Search Console reports on each separately. One 3.5 MB file sat at "Sitemap could
// not be read" for days.
//
// Cards are left out (they're a view of the profile, which is their canonical URL). Translations
// aren't listed here: every page names its own in <head> (hreflang, lib/seo.ts), which is enough.
// No changefreq / priority either: Google ignores both.
import { loadIndex, loadMeta } from "./data";
import type { Locale } from "./i18n/config";
import { LANES, ROLE_SLUGS, SITE_URL, URL_LOCALES, localePath } from "./site";

const PROFILE_FILES = { en: "players", ko: "players-ko", zh: "players-zh" } as const;
export const SITEMAP_FILES = ["pages", ...Object.values(PROFILE_FILES)];

const LOCALES: (Locale | null)[] = [null, ...URL_LOCALES];

/** The data build's date, as each page's lastmod. */
async function builtOn(): Promise<string> {
  const d = new Date((await loadMeta()).generated);
  return (Number.isNaN(d.getTime()) ? new Date() : d).toISOString().slice(0, 10);
}

const urlEntry = (path: string, lastmod: string | null) =>
  `<url><loc>${SITE_URL}${path}</loc>${lastmod ? `<lastmod>${lastmod}</lastmod>` : ""}</url>`;

/** One file of the index (a name from SITEMAP_FILES), or null for any other name. */
export async function sitemapXml(file: string): Promise<string | null> {
  const lastmod = await builtOn();
  let urls: string[];
  if (file === "pages") {
    const meta = await loadMeta();
    const years = [...(meta.asof_years ?? [])].sort((a, b) => b - a);
    urls = LOCALES.flatMap((l) => [
      urlEntry(localePath(l, "/"), lastmod),
      ...LANES.map((lane) => urlEntry(localePath(l, `/role/${ROLE_SLUGS[lane]}`), lastmod)),
      urlEntry(localePath(l, "/about"), lastmod),
      // a past season's board only changes when the models do
      ...years.map((y) => urlEntry(localePath(l, `/asof/${y}`), null)),
    ]);
  } else {
    const locale = (Object.keys(PROFILE_FILES) as Locale[]).find((l) => PROFILE_FILES[l as keyof typeof PROFILE_FILES] === file);
    if (!locale) return null;
    const players = [...(await loadIndex())].filter((r) => r.slug).sort((a, b) => a.rank - b.rank);
    urls = players.map((r) => urlEntry(localePath(locale, `/player/${r.slug}`), lastmod));
  }
  return [
    `<?xml version="1.0" encoding="UTF-8"?>`,
    `<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">`,
    ...urls,
    `</urlset>`,
    "",
  ].join("\n");
}

export async function sitemapIndexXml(): Promise<string> {
  const lastmod = await builtOn();
  return [
    `<?xml version="1.0" encoding="UTF-8"?>`,
    `<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">`,
    ...SITEMAP_FILES.map((f) => `<sitemap><loc>${SITE_URL}/sitemaps/${f}.xml</loc><lastmod>${lastmod}</lastmod></sitemap>`),
    `</sitemapindex>`,
    "",
  ].join("\n");
}

export const xmlResponse = (body: string) =>
  new Response(body, { headers: { "content-type": "application/xml; charset=utf-8" } });
