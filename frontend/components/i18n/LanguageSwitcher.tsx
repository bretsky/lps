"use client";

import { LOCALES, LOCALE_NAMES, LOCALE_SHORT, setLocale, useLocale, useT } from "@/lib/i18n";
import { HTML_LANG } from "@/lib/i18n/config";

/** EN · 한국어 · 中文, styled like the nav links beside it. */
export function LanguageSwitcher({ className = "" }: { className?: string }) {
  const locale = useLocale();
  const m = useT();
  return (
    <div
      role="group"
      aria-label={m.lang.label}
      className={`flex items-center font-serif text-[11px] font-bold uppercase tracking-[0.18em] ${className}`}
    >
      {LOCALES.map((l, i) => (
        <span key={l} className="flex items-center">
          {i > 0 && <span className="mx-1.5 h-2.5 w-px bg-gold-deep" aria-hidden />}
          <button
            type="button"
            lang={HTML_LANG[l]}
            title={LOCALE_NAMES[l]}
            aria-pressed={locale === l}
            onClick={() => setLocale(l)}
            className={`transition-colors ${
              locale === l ? "text-gold-bright" : "text-text-dim hover:text-gold-bright"
            } ${l === "en" ? "" : "tracking-[0.06em]"}`}
          >
            {LOCALE_SHORT[l]}
          </button>
        </span>
      ))}
    </div>
  );
}
