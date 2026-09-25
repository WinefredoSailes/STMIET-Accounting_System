const v = (name) =>
  Object.fromEntries(
    [50, 100, 200, 300, 400, 500, 600, 700, 800, 900].map((n) => [
      String(n),
      `rgb(var(--${name}-${n}) / <alpha-value>)`,
    ]),
  );

module.exports = {
  content: [
    "./../apps/**/templates/**/*.html",
    "./../static/js/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        // ADR-048: brand + accent are CSS variables so per-user themes
        // ([data-theme] blocks in src/input.css) retheme the UI with no
        // rebuild. Values ship as "R G B" triplets so /opacity modifiers
        // keep working via <alpha-value>.
        brand: v("brand"),
        accent: v("accent"),
        // Surface stays fixed - neutral document chrome, never themed.
        surface: {
          50: "#fafaf9",
          100: "#f5f5f4",
          200: "#e7e5e4",
          300: "#d6d3d1",
          400: "#a8a29e",
          500: "#78716c",
          600: "#57534e",
          700: "#44403c",
          800: "#292524",
          900: "#1c1917",
        },
      },
    },
  },
  plugins: [],
}
