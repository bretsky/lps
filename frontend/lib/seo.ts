// Page metadata for search engines and link previews (Discord, X, Reddit, iMessage...).
// Next merges metadata shallowly, so a page's `openGraph` replaces the layout's wholesale:
// every page builds its whole set here.

import type { Metadata } from "next";
import { displayName } from "./format";
import type { Locale } from "./i18n/config";
import { SEO } from "./i18n/seo";
import { OG_SITE_IMAGE, OG_SIZE, SITE_NAME, SITE_URL, URL_LOCALES, localePath } from "./site";

/** hreflang codes, matching <html lang>. */
const HREFLANG: Record<Locale, string> = { en: "en", ko: "ko", zh: "zh-CN" };

/** hreflang alternates of a page that exists in every language (`path` unprefixed). */
export function languageAlternates(path: string): Record<string, string> {
  return {
    [HREFLANG.en]: path,
    ...Object.fromEntries(URL_LOCALES.map((l) => [HREFLANG[l], localePath(l, path)])),
    "x-default": path,
  };
}

export function pageMeta({
  title,
  description,
  path,
  locale = "en",
  localized = false,
  image = OG_SITE_IMAGE,
  imageAlt,
  type = "website",
}: {
  title: string;
  description: string;
  path: string;             // canonical path, unprefixed ("/player/faker", "/role/mid")
  locale?: Locale;          // the page's URL language (its canonical is under /ko or /zh)
  localized?: boolean;      // the page exists in every language: link the others (hreflang)
  image?: string;
  imageAlt?: string;
  type?: "website" | "profile";
}): Metadata {
  const url = localePath(locale, path);
  const images = [{ url: image, ...OG_SIZE, alt: imageAlt ?? title }];
  return {
    title,
    description,
    alternates: { canonical: url, ...(localized ? { languages: languageAlternates(path) } : {}) },
    openGraph: {
      title,
      description,
      url,
      siteName: SITE_NAME,
      type,
      locale: SEO[locale].ogLocale,
      ...(localized ? { alternateLocale: (["en", ...URL_LOCALES] as Locale[]).filter((l) => l !== locale).map((l) => SEO[l].ogLocale) } : {}),
      images,
    },
    twitter: { card: "summary_large_image", title, description, images },
  };
}

/** A JSON-LD <script> payload; `<` is escaped so a name can't close the tag. */
export const jsonLd = (data: object) => JSON.stringify(data).replace(/</g, "\\u003c");

export const absUrl = (path: string) => `${SITE_URL}${path}`;

/** schema.org ItemList of a board's first rows, in rank order (`path` already in the page's language). */
export function boardItemList(name: string, path: string, rows: { slug: string; playername: string }[]) {
  return {
    "@context": "https://schema.org",
    "@type": "ItemList",
    name,
    url: absUrl(path),
    itemListOrder: "https://schema.org/ItemListOrderDescending",
    numberOfItems: rows.length,
    itemListElement: rows.map((r, i) => ({
      "@type": "ListItem",
      position: i + 1,
      url: absUrl(`/player/${r.slug}`),
      name: displayName(r.playername),
    })),
  };
}

/** A board's top five for a description: handles, plus the Hangul / Chinese name on those
 *  sites where there is one ("Faker(이상혁)"), since fans search for both. */
export function topFive(
  rows: { playername: string; name_ko?: string | null; name_zh?: string | null }[],
  locale: Locale,
): string {
  const names = rows.slice(0, 5).map((r) => {
    const h = displayName(r.playername);
    const local = locale === "ko" ? r.name_ko : locale === "zh" ? r.name_zh : null;
    return local ? `${h}(${local})` : h;
  });
  return SEO[locale].list(names);
}
