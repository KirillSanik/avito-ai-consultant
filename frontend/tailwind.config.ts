import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#15201b",
        canvas: "#f5f4ef",
        brand: "#1f6b4f",
        line: "#deddd6",
        warning: "#b56a25",
      },
    },
  },
  plugins: [],
};

export default config;
