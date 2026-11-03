import { useEffect } from 'react';
import type { ReactNode } from 'react';
import { Icon } from './Icon';

interface ModalProps {
  title: ReactNode;
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  size?: 'md' | 'lg';
  /** Prevent closing via overlay/escape (e.g. while showing a one-time secret). */
  locked?: boolean;
}

export function Modal({ title, open, onClose, children, size = 'md', locked = false }: ModalProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !locked) onClose();
    };
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [open, onClose, locked]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex animate-fade-in items-start justify-center overflow-y-auto bg-[rgba(3,7,15,0.62)] px-4 pb-6 pt-[60px] backdrop-blur-[6px] backdrop-saturate-[1.2]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !locked) onClose();
      }}
      role="dialog"
      aria-modal="true"
    >
      <div
        className={`modal relative w-full animate-modal-in rounded-lg border border-solid border-line-strong bg-glass-raised shadow-[shadow:var(--shadow-lg),inset_0_1px_0_var(--glass-edge-top)] backdrop-blur-glass backdrop-saturate-glass before:absolute before:inset-x-0 before:top-0 before:h-px before:bg-[linear-gradient(90deg,transparent,var(--primary),transparent)] before:opacity-60 before:content-[''] ${
          size === 'lg' ? 'max-w-[780px]' : 'max-w-[560px]'
        }`}
      >
        <div className="flex items-center justify-between gap-3 border-0 border-b border-solid border-line px-5 py-4">
          <h2 className="text-lg tracking-[-0.015em]">{title}</h2>
          {!locked && (
            <button type="button" className="flex cursor-pointer rounded border-none bg-transparent p-1.5 leading-none text-muted transition-[background,color] duration-ui ease-ui hover:bg-danger-soft hover:text-danger" onClick={onClose} aria-label="Close">
              <Icon name="close" size={17} />
            </button>
          )}
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}
