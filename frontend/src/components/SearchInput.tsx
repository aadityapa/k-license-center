import { useEffect, useRef, useState } from 'react';
import { Icon } from './Icon';

interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  debounceMs?: number;
  /** Set when an external <label htmlFor> should point at the field. */
  id?: string;
}

/** Debounced search input; calls onChange after the user stops typing. */
export function SearchInput({ value, onChange, placeholder = 'Search…', debounceMs = 350, id }: SearchInputProps) {
  const [local, setLocal] = useState(value);
  const timer = useRef<number | undefined>(undefined);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => setLocal(value), [value]);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const handle = (next: string) => {
    setLocal(next);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => onChangeRef.current(next), debounceMs);
  };

  return (
    <span className="search-input-wrap">
      <span className="search-icon">
        <Icon name="search" size={15} />
      </span>
      <input
        id={id}
        type="search"
        className="input"
        value={local}
        placeholder={placeholder}
        onChange={(e) => handle(e.target.value)}
        aria-label={placeholder}
      />
    </span>
  );
}
