"use client";

import { useEffect } from "react";
import { currentLocale, useLocale } from "@/lib/i18n";

/** Shows the page once React has re-rendered in the reader's language (LOCALE_INIT_SCRIPT
 *  hides it until then, so the English build doesn't flash). Mounted once, in the root layout. */
export function LocaleReady() {
  const locale = useLocale();
  useEffect(() => {
    if (locale === currentLocale()) document.documentElement.removeAttribute("data-i18n-pending");
  }, [locale]);
  return null;
}
