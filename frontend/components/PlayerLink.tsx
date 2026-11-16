"use client";

import Link from "next/link";
import type { ComponentProps } from "react";
import { useLocale } from "@/lib/i18n";
import { localePath } from "@/lib/site";

/** A link to a player's profile in the reader's language (/player/faker, /ko/player/faker).
 *  Prerendered (and hydrated) in the page's language, so a /ko board's HTML links /ko profiles.
 *  The Korean / Chinese profiles are served through a Pages Function, where every request
 *  counts against a daily quota, so those links are never prefetched. */
export function PlayerLink({
  slug,
  prefetch,
  ...props
}: { slug: string } & Omit<ComponentProps<typeof Link>, "href">) {
  const locale = useLocale();
  return <Link href={localePath(locale, `/player/${slug}`)} prefetch={locale === "en" ? prefetch : false} {...props} />;
}
