import type { Config } from 'tailwindcss';
export default {
  content: ['./src/**/*.{ts,tsx}'],
  theme: { extend: { colors: { bg: '#0b0e10', panel: '#12161a', raised: '#1a2026', line: '#262e35', ink: '#e8ecef', sub: '#9aa6af', mute: '#6f7b84', accent: '#7cc4ff', bad: '#ff7a66', good: '#5fd39a', warn: '#e8b84b' },
    fontFamily: { mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'] } } },
  plugins: [],
} satisfies Config;
