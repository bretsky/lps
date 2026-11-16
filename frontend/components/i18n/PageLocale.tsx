"use client";

// The language a page's URL fixes (/ko/..., /zh/...), or null on unprefixed pages, which
// follow the reader's saved choice instead. Read by useLocale() and the board links.
import { createContext } from "react";
import type { Locale } from "@/lib/i18n/config";

export const PageLocale = createContext<Locale | null>(null);

export function PageLocaleProvider({ value, children }: { value: Locale | null; children: React.ReactNode }) {
  return <PageLocale.Provider value={value}>{children}</PageLocale.Provider>;
}
