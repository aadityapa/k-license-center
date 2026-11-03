/**
 * A dashboard made of widgets the user can rearrange.
 *
 *  - drag a widget by its header to move it (native HTML drag & drop, no library)
 *  - the size button cycles the width: 1/3 → 1/2 → 2/3 → full
 *  - the eye hides a widget; "Customise" lists hidden ones to bring back
 *  - "Reset layout" restores the default
 *
 * The layout is saved per user in this browser (localStorage); it never
 * changes what the server returns, only how it is laid out here.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent, ReactNode } from 'react';
import { Icon } from '../../components/Icon';

export type WidgetSize = 1 | 2 | 3 | 4; // thirds of the row: 1=⅓ 2=½ 3=⅔ 4=full

export interface WidgetDef {
  id: string;
  title: string;
  defaultSize: WidgetSize;
  /** Sizes this widget looks right at (default: all). */
  sizes?: WidgetSize[];
  render: (size: WidgetSize) => ReactNode;
  /** Right-hand header slot (period picker, "View all", …). */
  actions?: ReactNode;
  subtitle?: string;
  /** No title bar (KPI tiles): the whole tile is the drag handle. */
  bare?: boolean;
}

export interface LayoutItem { id: string; size: WidgetSize; hidden?: boolean }

const LAYOUT_VERSION = 3;

function loadLayout(key: string): LayoutItem[] | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { v?: number; items?: LayoutItem[] };
    return parsed.v === LAYOUT_VERSION && Array.isArray(parsed.items) ? parsed.items : null;
  } catch {
    return null;
  }
}
function saveLayout(key: string, items: LayoutItem[]): void {
  try {
    localStorage.setItem(key, JSON.stringify({ v: LAYOUT_VERSION, items }));
  } catch {
    /* private mode etc. — the layout just won't persist */
  }
}

/** Merge a saved layout with the current widget list: new widgets appear, removed ones vanish. */
function reconcile(saved: LayoutItem[] | null, defs: WidgetDef[]): LayoutItem[] {
  const byId = new Map(defs.map((d) => [d.id, d]));
  const out: LayoutItem[] = [];
  for (const it of saved ?? []) if (byId.has(it.id)) out.push({ id: it.id, size: it.size, hidden: it.hidden });
  for (const d of defs) if (!out.some((o) => o.id === d.id)) out.push({ id: d.id, size: d.defaultSize });
  return out;
}

const SIZE_LABEL: Record<WidgetSize, string> = { 1: '⅓ width', 2: '½ width', 3: '⅔ width', 4: 'Full width' };

/**
 * Columns a widget spans on the 12-column grid, per size. The four KPI tiles
 * (marked `data-kpi`) at ⅓ would leave a hole, so at the default they sit 4 in
 * a row. ≤1200px: ⅓ becomes ½ and ⅔ becomes full; ≤760px everything is full.
 */
const SIZE_SPAN: Record<WidgetSize, string> = {
  1: 'col-span-4 has-[[data-kpi]]:col-span-3 max-[1200px]:col-span-6 max-[1200px]:has-[[data-kpi]]:col-span-6',
  2: 'col-span-6',
  3: 'col-span-8 max-[1200px]:col-span-12',
  4: 'col-span-12',
};
const SPAN_PHONE = 'max-[760px]:col-[1/-1] max-[760px]:has-[[data-kpi]]:col-[1/-1]';

/** Small square button in a widget's header while customising. */
const WG_BTN =
  'inline-flex h-7 min-w-[28px] cursor-pointer items-center gap-1 rounded border border-solid border-line bg-transparent px-1.5 text-xs text-ink-2 hover:border-primary hover:text-ink';

interface WidgetGridProps {
  storageKey: string;
  widgets: WidgetDef[];
  /** Extra toolbar content, left of the Customise button. */
  toolbar?: ReactNode;
}

export function WidgetGrid({ storageKey, widgets, toolbar }: WidgetGridProps) {
  const [layout, setLayout] = useState<LayoutItem[]>(() => reconcile(loadLayout(storageKey), widgets));
  const [customising, setCustomising] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);
  const [overId, setOverId] = useState<string | null>(null);
  const defs = useMemo(() => new Map(widgets.map((w) => [w.id, w])), [widgets]);

  // New widgets added in a later release show up without a reset.
  useEffect(() => {
    setLayout((cur) => reconcile(cur, widgets));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [widgets.map((w) => w.id).join('|')]);

  const update = useCallback(
    (fn: (items: LayoutItem[]) => LayoutItem[]) => {
      setLayout((cur) => {
        const next = fn(cur);
        saveLayout(storageKey, next);
        return next;
      });
    },
    [storageKey],
  );

  const cycleSize = (id: string) =>
    update((items) =>
      items.map((it) => {
        if (it.id !== id) return it;
        const allowed = defs.get(id)?.sizes ?? [1, 2, 3, 4];
        const i = allowed.indexOf(it.size);
        return { ...it, size: allowed[(i + 1) % allowed.length] ?? it.size };
      }),
    );
  const setHidden = (id: string, hidden: boolean) =>
    update((items) => items.map((it) => (it.id === id ? { ...it, hidden } : it)));
  const reset = () => update(() => reconcile(null, widgets));
  const move = (from: string, to: string) =>
    update((items) => {
      const a = items.findIndex((i) => i.id === from);
      const b = items.findIndex((i) => i.id === to);
      if (a < 0 || b < 0 || a === b) return items;
      const next = [...items];
      const [moved] = next.splice(a, 1);
      next.splice(b, 0, moved!);
      return next;
    });

  // Keyboard alternative to dragging: move a widget one step back/forward.
  const nudge = (id: string, dir: -1 | 1) =>
    update((items) => {
      const visible = items.filter((i) => !i.hidden);
      const vi = visible.findIndex((i) => i.id === id);
      const target = visible[vi + dir];
      if (!target) return items;
      const a = items.findIndex((i) => i.id === id);
      const b = items.findIndex((i) => i.id === target.id);
      const next = [...items];
      const [moved] = next.splice(a, 1);
      next.splice(b, 0, moved!);
      return next;
    });

  // Pointer-based dragging. Native HTML5 drag & drop does not work on touch
  // screens, so the header listens for pointer events instead: press, move a
  // few pixels to start, hover the target widget, release to drop.
  const drag = useRef<{ id: string; x: number; y: number; active: boolean } | null>(null);
  const overRef = useRef<string | null>(null);
  const targetAt = (x: number, y: number): string | null => {
    const el = document.elementFromPoint(x, y)?.closest('[data-widget-id]') as HTMLElement | null;
    return el?.dataset.widgetId ?? null;
  };
  const onPointerDown = (e: ReactPointerEvent<HTMLElement>, id: string) => {
    if (e.button !== 0) return;
    if ((e.target as HTMLElement).closest('button, a, select, input')) return;
    drag.current = { id, x: e.clientX, y: e.clientY, active: false };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLElement>) => {
    const d = drag.current;
    if (!d) return;
    if (!d.active) {
      if (Math.abs(e.clientX - d.x) + Math.abs(e.clientY - d.y) < 6) return;
      d.active = true;
      setDragId(d.id);
      document.body.classList.add('wg-dragging');
    }
    e.preventDefault();
    const t = targetAt(e.clientX, e.clientY);
    const next = t && t !== d.id ? t : null;
    if (next !== overRef.current) {
      overRef.current = next;
      setOverId(next);
    }
    // Keep the page scrolling while dragging near the top/bottom edge.
    if (e.clientY < 60) window.scrollBy(0, -12);
    else if (e.clientY > window.innerHeight - 60) window.scrollBy(0, 12);
  };
  const endDrag = (e: ReactPointerEvent<HTMLElement>, drop: boolean) => {
    const d = drag.current;
    drag.current = null;
    try { (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId); } catch { /* not captured */ }
    document.body.classList.remove('wg-dragging');
    if (d?.active && drop && overRef.current) move(d.id, overRef.current);
    overRef.current = null;
    setDragId(null);
    setOverId(null);
  };

  const hidden = layout.filter((i) => i.hidden && defs.has(i.id));

  return (
    <div className="wg">
      <div className="mb-2.5 flex items-center justify-end gap-2.5">
        {toolbar}
        <div className="flex items-center gap-2">
          {hidden.length > 0 && !customising && (
            <span className="text-xs text-muted">{hidden.length} hidden</span>
          )}
          <button type="button" className={`btn btn-sm ${customising ? 'btn-primary' : ''}`} onClick={() => setCustomising((v) => !v)}>
            <Icon name="sliders" size={14} />
            {customising ? 'Done' : 'Customise'}
          </button>
          {customising && (
            <button type="button" className="btn btn-sm" onClick={reset} title="Back to the default arrangement">
              <Icon name="refresh" size={14} />
              Reset layout
            </button>
          )}
        </div>
      </div>

      {customising && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-[12px] border border-dashed border-primary bg-[color-mix(in_srgb,var(--primary)_6%,transparent)] px-3.5 py-2.5 text-sm text-ink-2">
          Drag a widget by its title bar to move it. Use <Icon name="layers" size={13} /> to change its width and{' '}
          <Icon name="close" size={13} /> to hide it.
          {hidden.length > 0 && (
            <span className="ml-2 inline-flex flex-wrap items-center gap-1">
              Hidden:
              {hidden.map((h) => (
                <button key={h.id} type="button" className="btn btn-sm btn-ghost" onClick={() => setHidden(h.id, false)}>
                  <Icon name="plus" size={12} /> {defs.get(h.id)!.title}
                </button>
              ))}
            </span>
          )}
        </div>
      )}

      <div className="grid grid-cols-12 items-stretch gap-4 max-[760px]:grid-cols-[1fr]">
        {layout
          .filter((it) => !it.hidden && defs.has(it.id))
          .map((it) => {
            const def = defs.get(it.id)!;
            const isOver = overId === it.id;
            return (
              <section
                key={it.id}
                className={[
                  'wg-item group/wg flex min-w-0 flex-col rounded-[16px] border border-solid border-line bg-surface outline-offset-2',
                  'transition-[box-shadow,transform,opacity,outline-color] duration-150 ease-[ease]',
                  SIZE_SPAN[it.size],
                  SPAN_PHONE,
                  // customising: a dashed outline on every widget (it also wins over the drop-target colour)
                  customising ? 'outline-1 outline-dashed outline-line-strong' : `outline outline-2 ${isOver ? 'outline-primary' : 'outline-transparent'}`,
                  isOver ? 'shadow-[0_0_0_6px_color-mix(in_srgb,var(--primary)_15%,transparent)]' : 'shadow-sm',
                  dragId === it.id ? 'scale-[.985] opacity-45' : '',
                ].join(' ')}
                aria-label={def.title}
                data-widget-id={it.id}
              >
                <header
                  className={`flex cursor-grab touch-none select-none items-center gap-2 active:cursor-grabbing ${
                    def.bare ? 'min-h-[10px] px-2.5 pb-0 pt-1.5' : 'px-4 pb-2 pt-3.5'
                  }`}
                  onPointerDown={(e) => onPointerDown(e, it.id)}
                  onPointerMove={onPointerMove}
                  onPointerUp={(e) => endDrag(e, true)}
                  onPointerCancel={(e) => endDrag(e, false)}
                  title="Drag to move"
                >
                  <span
                    className={`flex rotate-90 text-muted transition-opacity duration-150 ease-[ease] ${
                      customising ? 'opacity-80' : 'opacity-0 group-hover/wg:opacity-80'
                    }`}
                    aria-hidden="true"
                  >
                    <Icon name="more" size={14} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <h2 className={`m-0 truncate text-[15px] tracking-[-0.01em] ${def.bare ? 'empty:hidden' : ''}`}>
                      {def.bare && !customising ? '' : def.title}
                    </h2>
                    {def.subtitle && <div className="mt-px text-sm text-muted">{def.subtitle}</div>}
                  </div>
                  <div className="flex cursor-default items-center gap-1">
                    {!customising && def.actions}
                    {customising && (
                      <>
                        <button type="button" className={WG_BTN} onClick={() => nudge(it.id, -1)} title="Move earlier" aria-label="Move earlier">
                          <Icon name="chevron-left" size={14} />
                        </button>
                        <button type="button" className={WG_BTN} onClick={() => nudge(it.id, 1)} title="Move later" aria-label="Move later">
                          <Icon name="chevron-right" size={14} />
                        </button>
                        <button type="button" className={WG_BTN} onClick={() => cycleSize(it.id)} title={`Width: ${SIZE_LABEL[it.size]} — click to change`} aria-label="Change width">
                          <Icon name="layers" size={14} />
                          <span className="whitespace-nowrap">{SIZE_LABEL[it.size]}</span>
                        </button>
                        <button type="button" className={WG_BTN} onClick={() => setHidden(it.id, true)} title="Hide this widget" aria-label="Hide">
                          <Icon name="close" size={14} />
                        </button>
                      </>
                    )}
                  </div>
                </header>
                <div className="min-w-0 flex-1 px-4 pb-4">{def.render(it.size)}</div>
              </section>
            );
          })}
      </div>
    </div>
  );
}
