"use client";

import { usePathname } from "next/navigation";
import { LOCALES, LOCALE_NAMES, LOCALE_SHORT, setLocale, useLocale, usePageLocale, useT } from "@/lib/i18n";
import { HTML_LANG } from "@/lib/i18n/config";
import { hasLocalizedPages, localePath, splitLocalePath } from "@/lib/site";

/** EN · 한국어 · 中文, styled like the nav links beside it. On pages that exist in every
 *  language (the boards, About) each is a link to that language's URL (/, /ko, /zh), which is
 *  also how crawlers find them; elsewhere (profiles, cards) it switches the page in place. */
export function LanguageSwitcher({ className = "" }: { className?: string }) {
  const locale = useLocale();
  const pageLocale = usePageLocale();
  const m = useT();
  const { path } = splitLocalePath(usePathname() ?? "/");
  const linked = pageLocale !== null || hasLocalizedPages(path);
  return (
    <div
      role="group"
      aria-label={m.lang.label}
      className={`flex items-center whitespace-nowrap font-serif text-[11px] font-bold uppercase tracking-[0.18em] ${className}`}
    >
      {LOCALES.map((l, i) => {
        const cls = `transition-colors ${
          locale === l ? "text-gold-bright" : "text-text-dim hover:text-gold-bright"
        } ${l === "en" ? "" : "tracking-[0.06em]"}`;
        return (
          <span key={l} className="flex items-center">
            {i > 0 && <span className="mx-1.5 h-2.5 w-px bg-gold-deep" aria-hidden />}
            {linked ? (
              <a
                href={localePath(l, path)}
                hrefLang={HTML_LANG[l]}
                lang={HTML_LANG[l]}
                title={LOCALE_NAMES[l]}
                aria-current={locale === l ? "true" : undefined}
                onClick={(e) => {
                  if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
                  e.preventDefault();
                  setLocale(l); // remembered, so English profiles opened from here follow it
                  // the board's role tab (`?lane=` on past seasons) comes along
                  const target = localePath(l, splitLocalePath(window.location.pathname).path) + window.location.search;
                  if (target !== window.location.pathname + window.location.search) window.location.assign(target);
                }}
                className={cls}
              >
                {LOCALE_SHORT[l]}
              </a>
            ) : (
              <button
                type="button"
                lang={HTML_LANG[l]}
                title={LOCALE_NAMES[l]}
                aria-pressed={locale === l}
                onClick={() => setLocale(l)}
                className={cls}
              >
                {LOCALE_SHORT[l]}
              </button>
            )}
          </span>
        );
      })}
    </div>
  );
}
