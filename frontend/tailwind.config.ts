import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // "Console" palette — warm-tinted charcoal, liner-note cream, analog accents.
        ink: "#16141B", // page background
        panel: "#1E1B25", // card surface
        raise: "#262230", // inputs / raised chrome
        line: "#332E3D", // hairlines / borders
        fog: "#A79FB2", // muted text
        cream: "#F4EFE6", // primary text / display
        amber: { DEFAULT: "#F6A93B", deep: "#E8801F" }, // VU-meter primary
        signal: "#5BD1E6", // cyan — data / secondary
        // kept for anything still referencing the old token
        brand: { DEFAULT: "#F6A93B", light: "#FFC46B" },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "Georgia", "serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      keyframes: {
        eq: {
          "0%, 100%": { transform: "scaleY(0.35)" },
          "50%": { transform: "scaleY(1)" },
        },
        "fade-up": {
          from: { opacity: "0", transform: "translateY(10px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.45s cubic-bezier(0.22, 1, 0.36, 1) both",
      },
    },
  },
  plugins: [],
};
export default config;
