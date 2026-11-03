import type { ReactNode } from 'react';
import { Icon } from './Icon';

export interface Column<T> {
  key: string;
  header: ReactNode;
  render?: (row: T) => ReactNode;
  sortable?: boolean;
  align?: 'left' | 'right';
  width?: string | number;
}

/**
 * Optional banded header above the column row, e.g. a "COUNTS" label spanning
 * three numeric columns. Groups are laid out left to right; `span: 0` (or any
 * gap you leave) is filled with an empty spacer cell automatically.
 */
export interface ColumnGroup {
  label: ReactNode;
  /** How many consecutive columns this band covers. */
  span: number;
}

interface DataTableProps<T> {
  columns: Array<Column<T>>;
  /** Bands over the header row. Total span may be less than columns.length. */
  groups?: ColumnGroup[];
  rows: T[];
  rowKey: (row: T) => string | number;
  loading?: boolean;
  /** current sort, e.g. "expiryDate:desc" */
  sort?: string;
  onSortChange?: (sort: string) => void;
  emptyTitle?: string;
  emptyMessage?: string;
  onRowClick?: (row: T) => void;
  skeletonRows?: number;
}

export function DataTable<T>({
  columns,
  groups,
  rows,
  rowKey,
  loading = false,
  sort,
  onSortChange,
  emptyTitle = 'No records found',
  emptyMessage = 'Try adjusting your filters or search.',
  onRowClick,
  skeletonRows = 6,
}: DataTableProps<T>) {
  const [sortKey, sortDir] = (sort ?? '').split(':');

  const toggleSort = (col: Column<T>) => {
    if (!col.sortable || !onSortChange) return;
    if (sortKey === col.key) {
      onSortChange(`${col.key}:${sortDir === 'asc' ? 'desc' : 'asc'}`);
    } else {
      onSortChange(`${col.key}:asc`);
    }
  };

  const cellValue = (row: T, col: Column<T>): ReactNode => {
    if (col.render) return col.render(row);
    const v = (row as Record<string, unknown>)[col.key];
    if (v === null || v === undefined || v === '') return <span className="muted">—</span>;
    return String(v);
  };

  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          {groups && groups.length > 0 && (
            <tr className="group-row">
              {(() => {
                const cells: ReactNode[] = [];
                let covered = 0;
                groups.forEach((g, i) => {
                  if (g.span <= 0) return;
                  cells.push(
                    <th key={`g-${i}`} colSpan={g.span} className={g.label ? 'group-label' : undefined}>
                      {g.label}
                    </th>,
                  );
                  covered += g.span;
                });
                if (covered < columns.length) {
                  cells.push(<th key="g-rest" colSpan={columns.length - covered} />);
                }
                return cells;
              })()}
            </tr>
          )}
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={`${col.sortable && onSortChange ? 'sortable' : ''} ${col.align === 'right' ? 'num' : ''}`}
                style={col.width ? { width: col.width } : undefined}
                onClick={() => toggleSort(col)}
              >
                {col.header}
                {col.sortable && sortKey === col.key && (
                  <span className="ml-1 text-primary">
                    <Icon
                      name={sortDir === 'desc' ? 'chevron-down' : 'chevron-up'}
                      size={11}
                      strokeWidth={2.5}
                      className="align-middle"
                    />
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading &&
            Array.from({ length: skeletonRows }).map((_, i) => (
              <tr key={`sk-${i}`} className="skeleton-row">
                {columns.map((col) => (
                  <td key={col.key}>
                    <div className="skeleton-bar" style={{ width: `${45 + ((i * 17 + col.key.length * 7) % 45)}%` }} />
                  </td>
                ))}
              </tr>
            ))}
          {!loading && rows.length === 0 && (
            <tr>
              <td colSpan={columns.length}>
                <div className="table-empty">
                  <div className="empty-icon">
                    <Icon name="inbox" size={32} />
                  </div>
                  <div className="empty-title">{emptyTitle}</div>
                  <div className="empty-hint">{emptyMessage}</div>
                </div>
              </td>
            </tr>
          )}
          {!loading &&
            rows.map((row) => (
              <tr
                key={rowKey(row)}
                className={onRowClick ? 'clickable' : undefined}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
              >
                {columns.map((col) => (
                  <td key={col.key} className={col.align === 'right' ? 'num' : undefined}>
                    {cellValue(row, col)}
                  </td>
                ))}
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}
