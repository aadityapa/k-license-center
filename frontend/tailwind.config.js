/**
 * Tailwind for the Karnex License Center portal.
 *
 * The design system lives in CSS variables (src/styles/tokens.css): two themes
 * (dark default, light via <html data-theme="light">) and per-role accents
 * (<html data-role="maker|checker|viewer">). The Tailwind theme points at those
 * variables, so a utility such as `bg-surface text-muted border-line` follows
 * the theme and the signed-in role automatically.
 *
 *   colours   bg-surface, bg-surface-raised/-sunken/-hover/-active, text-ink,
 *             text-ink-2 (secondary), text-muted, border-line, border-line-strong,
 *             primary(-hover/-soft/-border), success/warning/danger/info(-soft/-border),
 *             violet, sidebar-*, code, key
 *   spacing   Tailwind's default 4px scale already equals the --sp-* tokens (1 = 4px)
 *   text      text-xs 11 · sm 12 · base 13 · md 14 · lg 16 · xl 20 · 2xl 25 · 3xl 30
 *   radius    rounded-sm 5 · rounded 8 · rounded-md 10 · rounded-lg 14 · rounded-full
 *   shadow    shadow-xs/sm/md/lg, shadow-glow, shadow-focus
 *   variants  light:… (light theme), dark:… (dark theme), role-admin:/role-maker:/role-checker:/role-viewer:…,
 *             upto-[960px]:… = @media (max-width: 960px) — the old stylesheet's breakpoints
 *             exactly (Tailwind's max-[960px]: is `< 960px`, one pixel off)
 *   motion    animate-fade-in, animate-modal-in, animate-shimmer, animate-notif-pulse
 */
import plugin from 'tailwindcss/plugin';

const v = (name) => `var(--${name})`;

/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  // Preflight (Tailwind's CSS reset) stays off: the portal's own base layer
  // (src/styles/parts/base.css) already normalises what it needs, and the
  // reset would change spacing/typography the design was built on.
  corePlugins: { preflight: false },
  darkMode: ['variant', [':root:not([data-theme="light"]) &']],
  theme: {
    extend: {
      // Page background colours are background-only on purpose: as general colours their
      // names would make `text-base` (13px) also emit `color: var(--bg-base)`.
      backgroundColor: {
        base: v('bg-base'),
        deep: v('bg-deep'),
      },
      colors: {
        glass: { DEFAULT: v('glass'), solid: v('glass-solid'), raised: v('glass-raised'), sunken: v('glass-sunken'), edge: v('glass-edge') },
        surface: {
          DEFAULT: v('surface'), raised: v('surface-raised'), sunken: v('surface-sunken'),
          hover: v('surface-hover'), active: v('surface-active'),
        },
        line: { DEFAULT: v('border'), strong: v('border-strong'), input: v('border-input') },
        ink: { DEFAULT: v('text'), 2: v('text-secondary'), inverse: v('text-inverse') },
        muted: v('text-muted'),
        primary: {
          DEFAULT: v('primary'), hover: v('primary-hover'), active: v('primary-active'),
          soft: v('primary-soft'), border: v('primary-border'), glow: v('primary-glow'), on: v('on-primary'),
        },
        violet: { DEFAULT: v('violet'), soft: v('violet-soft') },
        purple: { DEFAULT: v('accent-purple'), soft: v('accent-purple-soft') },
        success: { DEFAULT: v('success'), soft: v('success-soft'), border: v('success-border') },
        warning: { DEFAULT: v('warning'), soft: v('warning-soft'), border: v('warning-border') },
        danger: { DEFAULT: v('danger'), hover: v('danger-hover'), soft: v('danger-soft'), border: v('danger-border') },
        info: { DEFAULT: v('info'), soft: v('info-soft'), border: v('info-border') },
        code: { DEFAULT: v('code-bg'), text: v('code-text') },
        key: v('key-text'),
        sidebar: {
          DEFAULT: v('sidebar-bg'), hover: v('sidebar-bg-hover'), text: v('sidebar-text'),
          strong: v('sidebar-text-strong'), section: v('sidebar-section'), line: v('sidebar-border'), active: v('sidebar-active-bg'),
        },
      },
      fontFamily: {
        sans: v('font'),
        mono: v('mono'),
      },
      fontSize: {
        '2xs': '10px',
        xs: '11px',
        sm: '12px',
        base: '13px',
        md: '14px',
        lg: '16px',
        xl: '20px',
        '2xl': '25px',
        '3xl': '30px',
      },
      borderRadius: {
        sm: v('radius-sm'),
        DEFAULT: v('radius'),
        md: v('radius-md'),
        lg: v('radius-lg'),
        full: v('radius-full'),
      },
      boxShadow: {
        xs: v('shadow-xs'),
        sm: v('shadow-sm'),
        md: v('shadow-md'),
        lg: v('shadow-lg'),
        glow: v('glow-primary'),
        focus: v('focus-ring'),
        'focus-danger': v('focus-ring-danger'),
      },
      backdropBlur: { glass: '16px' },
      backdropSaturate: { glass: '1.45' }, // with backdrop-blur-glass = the old --glass-blur
      spacing: {
        sidebar: v('sidebar-width'),
        topbar: v('topbar-height'),
      },
      transitionTimingFunction: { ui: 'cubic-bezier(0.4, 0, 0.2, 1)' },
      transitionDuration: { ui: '140ms' },
      keyframes: {
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'modal-in': {
          from: { opacity: '0', transform: 'translateY(-10px) scale(0.98)' },
          to: { opacity: '1', transform: 'none' },
        },
        shimmer: { '0%': { backgroundPosition: '200% 0' }, '100%': { backgroundPosition: '-200% 0' } },
        'notif-pulse': {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(239, 68, 68, .6)' },
          '50%': { boxShadow: '0 0 0 6px rgba(239, 68, 68, 0)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 160ms ease-out',
        'modal-in': 'modal-in 200ms cubic-bezier(0.16, 1, 0.3, 1)',
        shimmer: 'shimmer 1.5s ease-in-out infinite',
        'notif-pulse': 'notif-pulse 1.4s ease-in-out infinite',
      },
    },
  },
  plugins: [
    plugin(({ addVariant, matchVariant }) => {
      addVariant('light', ':root[data-theme="light"] &');
      // upto-[960px]:hidden -> @media (max-width: 960px) { ... }, larger widths first so narrower wins.
      matchVariant('upto', (value) => `@media (max-width: ${value})`, {
        sort: (a, b) => parseFloat(b.value) - parseFloat(a.value),
      });
      for (const role of ['admin', 'maker', 'checker', 'viewer']) {
        addVariant(`role-${role}`, `:root[data-role="${role}"] &`);
      }
    }),
  ],
};
