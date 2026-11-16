import type { Config } from "tailwindcss";

// "Art Deco meets Tron", coloured like the Rift: abyssal blue-black, burnished
// hextech-style gold for prestige, and a neon arcane teal for the data layer.
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: {
          DEFAULT: "#03070d",
          card: "#08121d",
          rail: "#050c15",
          raised: "#0d1b29",
        },
        border: {
          DEFAULT: "#1d2b38",
          strong: "#3a4a55",
        },
        text: {
          DEFAULT: "#eee4cf",
          muted: "#a79f8b",
          dim: "#6c6a62",
        },
        gold: {
          DEFAULT: "#c9a45c",
          bright: "#f1d58f",
          deep: "#7d5b28",
        },
        teal: {
          DEFAULT: "#1fd1c1",
          deep: "#0c6f74",
          ice: "#a6f2ff",
        },
        accent: {
          gold: "#c9a45c",
          hex: "#1fd1c1", // neon teal (name kept so older classes re-theme)
        },
        tier: {
          goats: "#f1cf7c",
          legends: "#e8874f",
          greats: "#b28bff",
          elite: "#3fbfe8",
          stars: "#3fd29e",
          contenders: "#8b8e95",
        },
      },
      fontFamily: {
        // --font-cjk (globals.css) covers Korean / Chinese text, which the Latin web fonts lack.
        sans: ["var(--font-sans)", "var(--font-cjk)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-sans)", "var(--font-cjk)", "sans-serif"],
        serif: ["var(--font-serif)", "Georgia", "var(--font-cjk)", "serif"],
        mono: ["var(--font-mono)", "ui-monospace", "Consolas", "var(--font-cjk)", "monospace"],
      },
      keyframes: {
        sheen: {
          "0%": { backgroundPosition: "200% 0" },
          "100%": { backgroundPosition: "-200% 0" },
        },
        pulseline: {
          "0%, 100%": { opacity: "0.55" },
          "50%": { opacity: "1" },
        },
      },
      animation: {
        sheen: "sheen 7s linear infinite",
        pulseline: "pulseline 3.5s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
