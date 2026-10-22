/** Tailwind v3 config for the TruthLens UI (compiled to static/app.css by `npm run build`). */
module.exports = {
  darkMode: 'class',
  content: ['./frontend/src/**/*.{js,jsx}', './index.html'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Space Grotesk"', '"Inter"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'monospace'],
      },
      colors: {
        apogee: {
          black: '#030303',
          card: '#0D0D11',
          cardHover: '#14141A',
          border: 'rgba(255, 255, 255, 0.1)',
          borderHover: 'rgba(255, 255, 255, 0.25)',
          text: '#F4F4F5',
          muted: '#A1A1AA',
          dim: '#52525B',
        },
      },
    },
  },
  plugins: [],
};
