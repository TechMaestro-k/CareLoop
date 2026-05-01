import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: ["./index.html", "./src*.{ts,tsx}"],
  theme: {
    container: { center: true, padding: "1.5rem", screens: { "2xl": "1400px" } },
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        surface: "hsl(var(--surface))",
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        mint: {
          DEFAULT: "#A8E6C9",
          deep: "#5FCBA0",
          ink: "#0F3D2E",
          soft: "#E8F8EF",
        },
        ink: {
          DEFAULT: "#0E1116",
          80: "#1B2027",
          60: "#3A424E",
          40: "#697383",
          20: "#B6BDC8",
        },
        triage: {
          red: "#E04050",
          redSoft: "#FDE7EA",
          amber: "#E8A33C",
          amberSoft: "#FBEEDA",
          green: "#3FA875",
          greenSoft: "#E0F4E9",
        },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
      },
      borderRadius: {
        xl: "1rem",
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ['"Inter"', "system-ui", "sans-serif"],
        display: ['"Manrope"', '"Inter"', "system-ui", "sans-serif"],
        deva: ['"Noto Sans Devanagari"', '"Inter"', "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(14, 17, 22, 0.04), 0 1px 3px rgba(14, 17, 22, 0.06)",
        soft: "0 4px 16px rgba(14, 17, 22, 0.06)",
        focus: "0 0 0 3px rgba(95, 203, 160, 0.35)",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-in": "fade-in 200ms ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
