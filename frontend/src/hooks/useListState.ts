import { useCallback, useMemo, useState } from 'react';

export interface ListState {
  page: number;
  pageSize: number;
  sort: string;
  q: string;
  filters: Record<string, string>;
}

interface UseListStateResult {
  state: ListState;
  params: Record<string, string | number | undefined>;
  setPage: (page: number) => void;
  setPageSize: (size: number) => void;
  setSort: (sort: string) => void;
  setQ: (q: string) => void;
  setFilter: (key: string, value: string) => void;
  clearFilters: () => void;
  hasFilters: boolean;
  depsKey: string;
}

/** Shared pagination / sorting / filtering state for server-driven lists. */
export function useListState(initial?: Partial<ListState>): UseListStateResult {
  const [state, setState] = useState<ListState>({
    page: 1,
    pageSize: 20,
    sort: initial?.sort ?? '',
    q: '',
    filters: initial?.filters ?? {},
    ...initial,
  });

  const setPage = useCallback((page: number) => setState((s) => ({ ...s, page })), []);
  const setPageSize = useCallback((pageSize: number) => setState((s) => ({ ...s, pageSize, page: 1 })), []);
  const setSort = useCallback((sort: string) => setState((s) => ({ ...s, sort, page: 1 })), []);
  const setQ = useCallback((q: string) => setState((s) => ({ ...s, q, page: 1 })), []);
  const setFilter = useCallback(
    (key: string, value: string) =>
      setState((s) => ({ ...s, page: 1, filters: { ...s.filters, [key]: value } })),
    [],
  );
  const clearFilters = useCallback(() => setState((s) => ({ ...s, page: 1, q: '', filters: {} })), []);

  const params = useMemo(() => {
    const p: Record<string, string | number | undefined> = {
      page: state.page,
      pageSize: state.pageSize,
      sort: state.sort || undefined,
      q: state.q || undefined,
    };
    for (const [k, v] of Object.entries(state.filters)) {
      if (v !== '') p[k] = v;
    }
    return p;
  }, [state]);

  const hasFilters = state.q !== '' || Object.values(state.filters).some((v) => v !== '');
  const depsKey = JSON.stringify(params);

  return { state, params, setPage, setPageSize, setSort, setQ, setFilter, clearFilters, hasFilters, depsKey };
}
