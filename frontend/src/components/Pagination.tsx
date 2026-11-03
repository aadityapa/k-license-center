import { Icon } from './Icon';

interface PaginationProps {
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  onPageSizeChange?: (size: number) => void;
}

export function Pagination({ page, pageSize, total, onPageChange, onPageSizeChange }: PaginationProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);

  return (
    <div className="pagination">
      <span>
        {total === 0 ? 'No records' : `Showing ${from}–${to} of ${total}`}
      </span>
      <div className="pages">
        {onPageSizeChange && (
          <select
            className="input"
            style={{ width: 'auto', padding: '3px 6px', marginRight: 8 }}
            value={pageSize}
            onChange={(e) => onPageSizeChange(Number(e.target.value))}
            aria-label="Rows per page"
          >
            {[10, 20, 50, 100].map((n) => (
              <option key={n} value={n}>
                {n} / page
              </option>
            ))}
          </select>
        )}
        <button
          type="button"
          className="btn btn-sm"
          disabled={page <= 1}
          onClick={() => onPageChange(1)}
          aria-label="First page"
        >
          First
        </button>
        <button
          type="button"
          className="btn btn-sm"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          aria-label="Previous page"
        >
          <Icon name="chevron-left" size={14} />
        </button>
        <span className="px-2">
          Page {page} of {totalPages}
        </span>
        <button
          type="button"
          className="btn btn-sm"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          aria-label="Next page"
        >
          <Icon name="chevron-right" size={14} />
        </button>
        <button
          type="button"
          className="btn btn-sm"
          disabled={page >= totalPages}
          onClick={() => onPageChange(totalPages)}
          aria-label="Last page"
        >
          Last
        </button>
      </div>
    </div>
  );
}
