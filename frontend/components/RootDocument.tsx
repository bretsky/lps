// The <html> document both root layouts render. English pages (app/(en)) follow the reader's
// saved language in the browser; /ko and /zh pages (app/(intl)/[lang]) are fixed to theirs, so
// their prerendered HTML is already in that language for search engines.
import "@/app/globals.css";
import { LocaleReady } from "@/components/i18n/LocaleReady";
import { PageLocaleProvider } from "@/components/i18n/PageLocale";
import { FONT_VARS } from "@/lib/fonts";
import { HTML_LANG, LOCALE_INIT_SCRIPT, type Locale } from "@/lib/i18n/config";

export function RootDocument({ fixed = null, children }: { fixed?: Locale | null; children: React.ReactNode }) {
  return (
    // Unprefixed pages: lang / data-locale are set before paint by LOCALE_INIT_SCRIPT (the
    // reader's language), hence suppressHydrationWarning: the prebuilt HTML always says "en".
    <html
      lang={HTML_LANG[fixed ?? "en"]}
      data-locale={fixed ?? undefined}
      data-locale-fixed={fixed ?? undefined}
      className={FONT_VARS}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: LOCALE_INIT_SCRIPT }} />
      </head>
      <body className="min-h-screen bg-bg font-sans text-text antialiased">
        <PageLocaleProvider value={fixed}>
          <LocaleReady />
          {children}
        </PageLocaleProvider>
      </body>
    </html>
  );
}
