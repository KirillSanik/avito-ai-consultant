import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/screens/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/lib/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "#EEF0F6",
        foreground: "#111827",
        primary: "#2A3F8F",
        "primary-dark": "#1E2F6A",
        secondary: "#F3F4F9",
        muted: "#6B7280",
        accent: "#4F6BEF",
        success: "#10B981",
        warning: "#F59E0B",
        danger: "#EF4444",
        border: "#DDE1ED",
      },
      fontFamily: {
        display: ["Instrument Serif", "serif"],
        sans: ["Inter", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
