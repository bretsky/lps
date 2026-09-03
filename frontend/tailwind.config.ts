import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // League-flavored dark cinematic base with hextech-gold accents
        bg: {
          DEFAULT: "#0a0e14",
          card: "#111821",
          rail: "#0f151d",
        },
        border: {
          DEFAULT: "#1e2a38",
          strong: "#2c3e52",
        },
        text: {
          DEFAULT: "#e6ecf3",
          muted: "#8a94a3",
          dim: "#5c6675",
        },
        accent: {
          gold: "#c8a95a",
          hex: "#4bd8d8",
        },
        tier: {
          goats: "#f5c15b",
          legends: "#d97757",
          greats: "#a685e2",
          elite: "#6aa7e6",
          stars: "#5fbf94",
          contenders: "#8a94a3",
        },
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
