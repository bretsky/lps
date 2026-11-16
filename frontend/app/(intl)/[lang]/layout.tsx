// Root layout of the Korean and Chinese pages (/ko/..., /zh/...): the boards and About,
// prerendered in that language with a matching <html lang> so search engines index them as
// such. Profiles and cards stay on their English URLs (translated in the browser), which keeps
// the site under Cloudflare Pages' file cap.
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { RootDocument } from "@/components/RootDocument";
import { isLocale } from "@/lib/i18n/config";
import { SITE_NAME, SITE_URL, URL_LOCALES } from "@/lib/site";

export const dynamicParams = false;

export function generateStaticParams() {
  return URL_LOCALES.map((lang) => ({ lang }));
}

export const metadata: Metadata = { metadataBase: new URL(SITE_URL), applicationName: SITE_NAME };

export default async function IntlLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ lang: string }>;
}) {
  const { lang } = await params;
  if (!isLocale(lang) || lang === "en") notFound();
  return <RootDocument fixed={lang}>{children}</RootDocument>;
}
