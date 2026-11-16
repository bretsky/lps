// The reader's language as a tiny external store on <html data-locale> (set before paint by
// LOCALE_INIT_SCRIPT, changed by the switcher). Components read it with `useT()`, which
// returns that language's message table (lib/i18n/en.tsx, ko.tsx, zh.tsx).
//
// Hydration renders in English (the server snapshot, matching the prebuilt HTML) and React
// re-renders in the reader's language straight after; client-side navigation renders in the
// reader's language from the start.

import { useContext, useSyncExternalStore } from "react";
import { PageLocale } from "@/components/i18n/PageLocale";
import { HTML_LANG, STORAGE_KEY, isLocale, type Locale } from "./config";
import { en, type Messages } from "./en";
import { ko } from "./ko";
import { zh } from "./zh";

export { LOCALES, LOCALE_NAMES, LOCALE_SHORT, type Locale } from "./config";
export type { Messages } from "./en";

export const MESSAGES: Record<Locale, Messages> = { en, ko, zh };

const listeners = new Set<() => void>();

function readLocale(): Locale {
  const l = document.documentElement.getAttribute("data-locale");
  return isLocale(l) ? l : "en";
}

function apply(l: Locale) {
  const d = document.documentElement;
  d.setAttribute("data-locale", l);
  d.lang = HTML_LANG[l];
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  // Another tab switched language.
  const onStorage = (e: StorageEvent) => {
    if (e.key === STORAGE_KEY && isLocale(e.newValue) && e.newValue !== readLocale()) {
      apply(e.newValue);
      listeners.forEach((f) => f());
    }
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", onStorage);
  };
}

export function setLocale(l: Locale) {
  apply(l);
  try {
    localStorage.setItem(STORAGE_KEY, l);
  } catch {
    // Private mode / blocked storage: the choice lasts for this page only.
  }
  listeners.forEach((f) => f());
}

/** The page's language: the one its URL fixes (/ko, /zh), else the reader's ("en" while hydrating). */
export function useLocale(): Locale {
  const fixed = useContext(PageLocale);
  const reader = useSyncExternalStore<Locale>(subscribe, readLocale, () => "en");
  return fixed ?? reader;
}

/** The language the page's URL fixes (/ko, /zh), or null on unprefixed pages. */
export function usePageLocale(): Locale | null {
  return useContext(PageLocale);
}

/** The message table for the reader's language. */
export function useT(): Messages {
  return MESSAGES[useLocale()];
}

/** The reader's language, outside React (event handlers, effects). */
export function currentLocale(): Locale {
  return typeof document === "undefined" ? "en" : readLocale();
}

/** A data label with optional translations ({label, i18n: {ko, zh}}) in the reader's language. */
export function localized(en: string, i18n: Partial<Record<Locale, string>> | null | undefined, l: Locale): string {
  return (l !== "en" && i18n?.[l]) || en;
}
