import { Fragment } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

interface Crumb {
  label: string;
  to?: string;
}

interface PageHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  breadcrumbs?: Crumb[];
}

export function PageHeader({ title, subtitle, actions, breadcrumbs }: PageHeaderProps) {
  return (
    <div>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-1.5 text-sm text-muted">
          {breadcrumbs.map((c, i) => (
            <Fragment key={i}>
              {i > 0 && <span className="opacity-45">/</span>}
              {c.to ? (
                <Link to={c.to} className="text-muted hover:text-primary">
                  {c.label}
                </Link>
              ) : (
                <span>{c.label}</span>
              )}
            </Fragment>
          ))}
        </div>
      )}
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          {/* gradient ink; `text-ink` stays as the fallback where background-clip: text is unsupported */}
          <h1 className="bg-[linear-gradient(120deg,var(--text)_20%,var(--primary)_130%)] bg-clip-text text-xl tracking-[-0.025em] text-ink [-webkit-text-fill-color:transparent]">
            {title}
          </h1>
          {subtitle && <div className="mt-1 text-base text-ink-2">{subtitle}</div>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
    </div>
  );
}
