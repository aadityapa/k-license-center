/**
 * Tailwind class strings shared by the two public licence-request pages
 * (RequestLicensePage, CompleteRequestPage). Every colour is a theme token,
 * so both themes and the neutral accent apply.
 */
/* The public pages run without the app shell: a centred glass card on the
   ambient page background, widened for grouped form sections. margin:auto
   rather than the parent's align-items, so a tall form scrolls instead of
   being clipped at the top of the viewport. */
export const PAGE = 'relative flex min-h-screen items-center justify-center p-5';
export const CARD =
  "relative m-auto w-full rounded-lg border border-solid border-line-strong bg-glass-raised px-6 py-8 [box-shadow:var(--shadow-lg),inset_0_1px_0_var(--glass-edge-top),0_0_60px_rgba(34,211,238,0.10)] [backdrop-filter:var(--glass-blur)] " +
  "before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-[linear-gradient(90deg,transparent,var(--primary),var(--violet),transparent)] before:content-['']";
export const BRAND = 'mb-6 flex items-center gap-3';
export const LOGO =
  'flex h-[46px] w-[46px] items-center justify-center rounded-lg bg-[linear-gradient(135deg,var(--primary)_0%,var(--violet)_100%)] text-[22px] font-extrabold tracking-[-0.03em] text-[#04121a] shadow-[0_0_30px_var(--primary-glow),inset_0_1px_0_rgba(255,255,255,0.4)]';
export const FOOTER = 'mt-5 text-center text-2xs uppercase tracking-[0.1em] text-muted';
export const SECTION_TITLE = 'mb-2 text-2xs font-bold uppercase tracking-[0.09em] text-muted';
export const LOADING = 'flex items-center gap-2 px-0 py-5 text-md text-ink-2';
export const PICK_LIST = 'grid gap-2';
/** A pickable option row (product, plan). Featured keeps its border colour even when selected. */
export function pickOption(selected: boolean, featured = false): string {
  const border = featured ? 'border-primary-border' : selected ? 'border-primary' : 'border-line-input hover:border-primary-border';
  const fill = selected ? 'bg-primary-soft shadow-glow' : 'bg-surface-sunken hover:bg-surface-hover';
  return `flex w-full cursor-pointer items-start gap-3 rounded border border-solid px-4 py-3 text-left font-sans text-ink [transition:border-color_var(--transition),background_var(--transition),box-shadow_var(--transition)] ${border} ${fill}`;
}
export function pickRadio(selected: boolean): string {
  return `mt-[3px] h-[15px] w-[15px] shrink-0 rounded-full border border-solid ${
    selected ? 'border-primary bg-primary shadow-[0_0_0_3px_var(--primary-soft)]' : 'border-line-strong bg-transparent'
  }`;
}
export const PICK_BODY = 'flex min-w-0 flex-col gap-0.5';
export const PICK_NAME = 'flex items-center gap-2 text-md font-semibold';
export const PICK_META = 'text-sm leading-normal text-ink-2';
export const OUTCOME = 'px-0 pb-2 pt-4 text-center';
export function outcomeIcon(ok = false): string {
  return `mx-auto mb-4 mt-0 flex h-14 w-14 items-center justify-center rounded-full border border-solid ${
    ok ? 'border-success-border bg-success-soft text-success' : 'border-primary-border bg-primary-soft text-primary'
  }`;
}
export const OUTCOME_TITLE = 'text-xl font-semibold tracking-[-0.02em]';
export const OUTCOME_BODY = 'mt-3 text-md leading-[1.65] text-ink-2';
