import type { Config } from 'tailwindcss';

/** A semantic color backed by a CSS variable in src/index.css. */
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'Roboto', 'Helvetica', 'Arial', 'sans-serif'],
      },
      colors: {
        canvas: token('canvas'),
        surface: {
          DEFAULT: token('surface'),
          sunken: token('surface-sunken'),
          hover: token('surface-hover'),
        },
        border: {
          DEFAULT: token('border'),
          strong: token('border-strong'),
        },
        fg: {
          DEFAULT: token('fg'),
          secondary: token('fg-secondary'),
          muted: token('fg-muted'),
        },
        accent: {
          DEFAULT: token('accent'),
          hover: token('accent-hover'),
          text: token('accent-text'),
        },
        'on-accent': token('on-accent'),
        success: token('success'),
        warning: token('warning'),
        danger: {
          DEFAULT: token('danger'),
          solid: token('danger-solid'),
        },
        ai: token('ai'),
        highlight: token('highlight'),
        ring: token('ring'),
        shadow: token('shadow'),
      },
    },
  },
  plugins: [],
} satisfies Config;
