"use client";

import { useEffect } from "react";
import { MESSAGES, useLocale, useT, type Messages } from "@/lib/i18n";

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

/** Sets document.title from a message (the prerendered <title> is English). */
export function DocTitle({ k, args = [] }: { k: "home" | "asof" | "about" | "card"; args?: (string | number)[] }) {
  const locale = useLocale();
  useEffect(() => {
    const v = MESSAGES[locale].meta[k] as string | ((...a: (string | number)[]) => string);
    document.title = typeof v === "function" ? v(...args) : v;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [locale, k, ...args]);
  return null;
}
