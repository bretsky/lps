// Root layout of the unprefixed (English) pages. Their prebuilt HTML is English; a reader who
// chose Korean or Chinese gets it translated in the browser (lib/i18n). /ko and /zh have their
// own root layout, app/(intl)/[lang]/layout.tsx.
import type { Metadata } from "next";
import { RootDocument } from "@/components/RootDocument";
import { SEO } from "@/lib/i18n/seo";
import { SITE_NAME, SITE_URL } from "@/lib/site";

// Site-wide defaults; every page sets its own title, description, canonical URL and preview.
export const metadata: Metadata = {
  title: SEO.en.home,
  description: "League of Legends esports all-time player rankings by CLR (Career Legend Rating).",
  metadataBase: new URL(SITE_URL),
  applicationName: SITE_NAME,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <RootDocument>{children}</RootDocument>;
}
