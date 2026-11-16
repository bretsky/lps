// Site languages. The site is a static export with ~15k prerendered files and Cloudflare
// Pages caps a site at 20k, so languages are NOT separate routes (/ko/...): every page is
// built once in English and the reader's choice is applied in the browser (lib/i18n/index.ts).
// The choice is kept in localStorage; a first visit follows the browser's language.

export const LOCALES = ["en", "ko", "zh"] as const;
export type Locale = (typeof LOCALES)[number];

/** Each language's name in itself, for the switcher. */
export const LOCALE_NAMES: Record<Locale, string> = { en: "English", ko: "한국어", zh: "中文" };
/** Short switcher labels. */
export const LOCALE_SHORT: Record<Locale, string> = { en: "EN", ko: "한국어", zh: "中文" };
/** BCP 47 tag for <html lang>: picks the right CJK glyph forms and fonts (zh = Simplified). */
export const HTML_LANG: Record<Locale, string> = { en: "en", ko: "ko", zh: "zh-CN" };

export const STORAGE_KEY = "clr-locale";

export const isLocale = (x: unknown): x is Locale => typeof x === "string" && (LOCALES as readonly string[]).includes(x);

/** Runs in <head> before first paint: applies the saved (or browser) language to <html> so
 *  CSS and the first client render see it, and hides the page until React has re-rendered
 *  in that language (LocaleReady removes the flag; the timeout is a fallback if JS stalls),
 *  so Korean and Chinese readers don't see the English build flash first. */
export const LOCALE_INIT_SCRIPT = `(function(){try{
var d=document.documentElement,l=null;
try{l=localStorage.getItem(${JSON.stringify(STORAGE_KEY)})}catch(e){}
if(l!=="en"&&l!=="ko"&&l!=="zh"){var n=((navigator.languages&&navigator.languages[0])||navigator.language||"").toLowerCase();l=n.indexOf("ko")===0?"ko":n.indexOf("zh")===0?"zh":"en"}
d.setAttribute("data-locale",l);d.lang=l==="zh"?"zh-CN":l;
if(l!=="en"){d.setAttribute("data-i18n-pending","");setTimeout(function(){d.removeAttribute("data-i18n-pending")},1500)}
}catch(e){}})();`;
