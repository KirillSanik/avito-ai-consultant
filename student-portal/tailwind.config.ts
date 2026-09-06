import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        background: "#F4F6FB",
        foreground: "#111827",
        primary: "#2446A8",
        "primary-dark": "#18357F",
        secondary: "#F3F4F9",
        muted: "#6B7280",
        accent: "#4F6BEF",
        success: "#10B981",
        warning: "#F59E0B",
        danger: "#EF4444",
        border: "#DDE1ED"
      },
      fontFamily: {
        display: ["Instrument Serif", "serif"],
        sans: ["Inter", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"]
      }
    }
  },
  plugins: []
};

export default config;
