"use client";

import { useEffect } from "react";
import { useLocale, useT, type Messages } from "@/lib/i18n";
import { SEO } from "@/lib/i18n/seo";

// Dotted paths to the plain-string messages ("nav.rankings"), so server components can drop a
// translated string in with <T k="nav.rankings" /> without becoming client components.
type StringPaths<T, P extends string = ""> = {
  [K in keyof T & string]: T[K] extends string ? `${P}${K}` : T[K] extends object ? StringPaths<T[K], `${P}${K}.`> : never;
}[keyof T & string];
export type MessageKey = StringPaths<Messages>;

function lookup(m: Messages, k: MessageKey): string {
  let v: unknown = m;
  for (const part of k.split(".")) v = (v as Record<string, unknown>)[part];
  return typeof v === "string" ? v : k;
}

/** A plain-string message in the reader's language. */
export function T({ k }: { k: MessageKey }) {
  return <>{lookup(useT(), k)}</>;
}

/** Sets document.title in the page's / reader's language (lib/i18n/seo.ts, the same titles the
 *  pages' metadata prerenders), so a reader's tab title follows a language switch. */
export function DocTitle({ k, args = [] }: { k: "home" | "asof" | "about" | "card" | "role"; args?: (string | number)[] }) {
  const locale = useLocale();
  useEffect(() => {
    const v = SEO[locale][k] as string | ((...a: (string | number)[]) => string);
    document.title = typeof v === "function" ? v(...args) : v;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale, k, args.join("|")]); // joined: the board's role tab can add or drop an arg
  return null;
}
