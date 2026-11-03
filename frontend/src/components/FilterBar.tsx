import type { ReactNode } from 'react';

interface FilterBarProps {
  children: ReactNode;
  onClear?: () => void;
  showClear?: boolean;
}

export function FilterBar({ children, onClear, showClear }: FilterBarProps) {
  return (
    <div className="flex flex-wrap items-end gap-3 border-0 border-b border-solid border-line bg-glass-sunken px-4 py-3">
      {children}
      {showClear && onClear && (
        <button type="button" className="btn btn-sm mb-px" onClick={onClear}>
          Clear filters
        </button>
      )}
    </div>
  );
}

interface FilterItemProps {
  label: string;
  children: ReactNode;
}

export function FilterItem({ label, children }: FilterItemProps) {
  return (
    <div className="filter-item">
      <label>{label}</label>
      {children}
    </div>
  );
}
