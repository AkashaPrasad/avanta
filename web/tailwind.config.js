/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        abyss:   '#050709',
        panel:   '#0A0E11',
        raised:  '#11171B',
        hairline:'#263037',
        ink:     '#F3F5F0',
        muted:   '#A9B2B4',
        dim:     '#839095',
        sodium:  '#FFB000',
        radar:   '#67F7D4',
        coral:   '#FF5C35',
        sage:    '#91D89E',
      },
      fontFamily: {
        display: ['"Barlow Condensed"', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
        sans: ['"IBM Plex Sans"', 'sans-serif'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
    },
  },
  plugins: [],
}
