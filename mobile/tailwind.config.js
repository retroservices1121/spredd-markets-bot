/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,jsx,ts,tsx}",
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  presets: [require("nativewind/preset")],
  theme: {
    extend: {
      colors: {
        spredd: {
          primary: "#00D973",
          bg: "#0F0F1A",
          card: "rgba(255,255,255,0.06)",
          surface: "rgba(255,255,255,0.10)",
          gray: "#9CA3AF",
          green: "#00D973",
          red: "#FF4059",
          border: "rgba(255,255,255,0.08)",
        },
      },
      fontFamily: {
        sans: ["Manrope"],
        brand: ["Bungee"],
      },
    },
  },
  plugins: [],
};
