// The site's fonts (next/font), shared by both root layouts: app/(en) and app/(intl)/[lang].
import { Barlow, Big_Shoulders_Display, Cinzel, JetBrains_Mono } from "next/font/google";

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

export const FONT_VARS = `${sans.variable} ${display.variable} ${serif.variable} ${mono.variable}`;
