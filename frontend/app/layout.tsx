import type { Metadata } from "next";
import { Barlow, Big_Shoulders_Display, Cinzel, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { LocaleReady } from "@/components/i18n/LocaleReady";
import { LOCALE_INIT_SCRIPT } from "@/lib/i18n/config";

// Body copy.
const sans = Barlow({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-sans",
  display: "swap",
});

// Tall, condensed deco numerals + headline names (Chicago deco signage lineage).
const display = Big_Shoulders_Display({
  subsets: ["latin"],
  weight: ["500", "700", "800", "900"],
  variable: "--font-display",
  display: "swap",
});

// Engraved, hall-of-fame capitals for titles, tiers and plaques.
const serif = Cinzel({
  subsets: ["latin"],
  weight: ["500", "600", "700", "800"],
  variable: "--font-serif",
  display: "swap",
});

// Readouts.
const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "CLR · All-Time Rankings",
  description:
    "League of Legends esports all-time player rankings by CLR (Career Legend Rating).",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // lang / data-locale are set before paint by LOCALE_INIT_SCRIPT (the reader's language),
    // hence suppressHydrationWarning: the prebuilt HTML always says "en".
    <html
      lang="en"
      className={`${sans.variable} ${display.variable} ${serif.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: LOCALE_INIT_SCRIPT }} />
      </head>
      <body className="min-h-screen bg-bg font-sans text-text antialiased">
        <LocaleReady />
        {children}
      </body>
    </html>
  );
}
