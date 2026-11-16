// /sitemap.xml: every page a search engine should index. The boards, About and profiles are
// listed in each language (/, /ko, /zh), each entry naming its translations (hreflang). Cards are left
// out (they're a view of the profile, which is their canonical URL).
import type { MetadataRoute } from "next";
import { loadIndex, loadMeta } from "@/lib/data";
import { languageAlternates } from "@/lib/seo";
import { LANES, ROLE_SLUGS, SITE_URL, URL_LOCALES, localePath } from "@/lib/site";

export const dynamic = "force-static";

type Entry = MetadataRoute.Sitemap[number];

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const [index, meta] = await Promise.all([loadIndex(), loadMeta()]);
  const built = new Date(meta.generated);
  const lastModified = Number.isNaN(built.getTime()) ? new Date() : built;
  const url = (path: string) => `${SITE_URL}${path}`;

  // A page that exists in every language: one entry per language, each listing all of them.
  const everyLanguage = (path: string, rest: Omit<Entry, "url" | "alternates">): Entry[] => {
    const languages = Object.fromEntries(Object.entries(languageAlternates(path)).map(([k, p]) => [k, url(p)]));
    return [null, ...URL_LOCALES].map((l) => ({ url: url(localePath(l, path)), ...rest, alternates: { languages } }));
  };

  return [
    ...everyLanguage("/", { lastModified, changeFrequency: "daily", priority: 1 }),
    ...LANES.flatMap((l) => everyLanguage(`/role/${ROLE_SLUGS[l]}`, { lastModified, changeFrequency: "daily", priority: 0.9 })),
    ...everyLanguage("/about", { lastModified, changeFrequency: "monthly", priority: 0.6 }),
    ...[...(meta.asof_years ?? [])]
      .sort((a, b) => b - a)
      .flatMap((y) => everyLanguage(`/asof/${y}`, { changeFrequency: "yearly", priority: 0.5 })),
    ...[...index]
      .filter((r) => r.slug)
      .sort((a, b) => a.rank - b.rank)
      .flatMap((r) =>
        everyLanguage(`/player/${r.slug}`, {
          lastModified,
          changeFrequency: "weekly",
          // the best-known players first: 0.8 for the top 100, tapering to 0.3
          priority: Math.round(Math.max(0.3, 0.8 - Math.floor((r.rank - 1) / 100) * 0.05) * 100) / 100,
        }),
      ),
  ];
}
