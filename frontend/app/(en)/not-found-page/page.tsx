// The site's 404 page. With two root layouts (app/(en), app/(intl)/[lang]) Next can only export
// its own unstyled 404.html, so this page is built instead and scripts/deploy.mjs copies it over
// out/404.html (and drops the /not-found-page URL itself).
import type { Metadata } from "next";
import { LanguageSwitcher } from "@/components/i18n/LanguageSwitcher";
import { LocalizedLink } from "@/components/i18n/LocalizedLink";
import { T } from "@/components/i18n/T";

export const metadata: Metadata = {
  title: "Page not found · CLR",
  robots: { index: false, follow: true },
};

export default function NotFoundPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col px-4 py-6">
      <nav className="flex justify-end font-serif text-[11px] font-bold uppercase tracking-[0.25em]">
        <LanguageSwitcher />
      </nav>
      <div className="flex flex-1 flex-col items-center justify-center text-center">
        <div className="font-display text-[120px] font-black leading-none text-metal">404</div>
        <h1 className="mt-4 font-serif text-xl font-extrabold uppercase tracking-[0.3em] text-gold">
          <T k="notFound.title" />
        </h1>
        <p className="mt-3 text-text-muted">
          <T k="notFound.body" />
        </p>
        <LocalizedLink
          path="/"
          className="mt-8 font-serif text-[11px] font-bold uppercase tracking-[0.25em] text-gold hover:text-gold-bright"
        >
          ◂ <T k="nav.rankings" />
        </LocalizedLink>
      </div>
    </main>
  );
}
