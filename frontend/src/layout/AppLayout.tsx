import { useEffect, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useRoleIdentity } from '../auth/useRoleIdentity';
import { useTheme } from '../theme/ThemeContext';
import { Icon } from '../components/Icon';
import { NotificationBell } from '../components/NotificationBell';
import { ServerClock } from '../components/ServerClock';
import { changeRequestsApi } from '../services/api/endpoints';
import type { IconName } from '../components/Icon';

interface NavItem {
  label: string;
  to: string;
  icon: IconName;
  perms?: string[]; // shown if user has ANY of these
  /** Key into the live counters resolved in AppLayout (e.g. pending approvals). */
  badge?: 'pendingApprovals';
}

interface NavSection {
  title: string | null;
  items: NavItem[];
}

const NAV: NavSection[] = [
  {
    title: null,
    items: [{ label: 'Dashboard', to: '/', icon: 'dashboard', perms: ['DASHBOARD_VIEW'] }],
  },
  {
    title: 'Products',
    items: [
      { label: 'Products', to: '/products', icon: 'package', perms: ['PRODUCT_VIEW', 'PRODUCT_MANAGE'] },
      { label: 'Product Plans', to: '/plans', icon: 'layers', perms: ['PLAN_MANAGE'] },
    ],
  },
  {
    title: 'Customers',
    items: [{ label: 'Customers', to: '/customers', icon: 'users', perms: ['CUSTOMER_VIEW', 'CUSTOMER_MANAGE'] }],
  },
  {
    title: 'Licenses',
    items: [
      { label: 'All Licenses', to: '/licenses', icon: 'file-text', perms: ['LICENSE_VIEW'] },
      { label: 'License Keys', to: '/license-keys', icon: 'key', perms: ['LICENSE_VIEW'] },
      { label: 'Activations', to: '/activations', icon: 'activity', perms: ['ACTIVATION_MANAGE', 'LICENSE_VIEW'] },
      { label: 'Renewals', to: '/renewals', icon: 'refresh', perms: ['LICENSE_VIEW'] },
    ],
  },
  {
    title: 'Requests',
    items: [
      { label: 'Licence Requests', to: '/license-requests', icon: 'inbox', perms: ['REQUEST_LICENSE_VIEW'] },
      { label: 'Email Outbox', to: '/email-outbox', icon: 'file-text', perms: ['EMAIL_OUTBOX_VIEW'] },
    ],
  },
  // API Clients (/api-clients) and API Logs (/api-logs) are hidden from the menu on purpose
  // (user's request, 04-Nov-2026): the apps' clients are issued by scripts, staff don't manage
  // them. The pages still work by URL for troubleshooting.
  {
    title: 'Users & Security',
    items: [
      { label: 'Users', to: '/users', icon: 'user', perms: ['USER_MANAGE'] },
      { label: 'Roles', to: '/roles', icon: 'sliders', perms: ['USER_MANAGE'] },
    ],
  },
  {
    title: 'Governance',
    items: [
      { label: 'Approvals', to: '/approvals', icon: 'clipboard', perms: ['REQUEST_VIEW'], badge: 'pendingApprovals' },
    ],
  },
  {
    title: 'Audit',
    items: [{ label: 'Audit Logs', to: '/audit-logs', icon: 'clipboard', perms: ['AUDIT_VIEW'] }],
  },
  {
    title: 'System',
    items: [{ label: 'Settings', to: '/settings', icon: 'settings', perms: ['SETTINGS_MANAGE'] }],
  },
];

/* Sidebar nav item: a filled gradient pill when active (reads instantly at a glance,
   which matters in a sidebar this long). Its ink is dark on the admin cyan and the
   role's own on-primary colour elsewhere. */
const NAV_LINK =
  'group relative mx-2 my-px flex items-center gap-3 rounded border border-solid border-transparent px-2.5 py-2 text-base hover:no-underline transition-[background,color,box-shadow] duration-ui ease-ui';
const NAV_LINK_IDLE = 'font-medium text-sidebar-text hover:bg-sidebar-hover hover:text-sidebar-strong';
const NAV_LINK_ACTIVE =
  'bg-[linear-gradient(100deg,var(--primary)_0%,#2dd4bf_100%)] font-semibold text-[#06131c] shadow-[0_2px_16px_var(--primary-glow)] hover:text-[#06131c] role-maker:text-primary-on role-checker:text-primary-on role-viewer:text-primary-on';

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
}

export function AppLayout() {
  const { user, logout, hasPermission } = useAuth();
  const role = useRoleIdentity();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [pendingApprovals, setPendingApprovals] = useState<number | null>(null);
  const [search, setSearch] = useState('');
  const displayName = user?.fullName || user?.username || '';
  const roleLabel = (user?.roles ?? []).filter((r) => r && r.trim() !== '').join(', ');

  // One cheap call on mount for the Approvals badge; pageSize 1 because only
  // the aggregate matters. Silently ignored if the user cannot see requests.
  const canViewRequests = hasPermission('REQUEST_VIEW');
  useEffect(() => {
    if (!canViewRequests) {
      setPendingApprovals(null);
      return;
    }
    let cancelled = false;
    changeRequestsApi
      .list({ status: 'PENDING', pageSize: 1 })
      .then((res) => {
        if (!cancelled) setPendingApprovals(res.pendingTotal);
      })
      .catch(() => {
        if (!cancelled) setPendingApprovals(null);
      });
    return () => {
      cancelled = true;
    };
  }, [canViewRequests]);

  const handleLogout = async () => {
    await logout();
    navigate('/login', { replace: true });
  };

  const visibleSections = NAV.map((section) => ({
    ...section,
    items: section.items.filter((item) => !item.perms || hasPermission(...item.perms)),
  })).filter((section) => section.items.length > 0);

  // Stamp the role on <html> so the CSS accent tokens swap for the whole app.
  // Cleared on unmount so the login screen returns to the neutral palette.
  useEffect(() => {
    document.documentElement.setAttribute('data-role', role.key);
    return () => document.documentElement.removeAttribute('data-role');
  }, [role.key]);

  return (
    <div className="flex min-h-screen">
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-[35] hidden bg-[rgba(3,7,15,0.6)] backdrop-blur-[4px] upto-[960px]:block"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-sidebar flex-col overflow-y-auto overscroll-contain border-0 border-r border-solid border-sidebar-line bg-sidebar text-sidebar-text backdrop-blur-glass backdrop-saturate-glass transition-transform duration-[240ms] ease-ui upto-[960px]:shadow-lg ${
          sidebarOpen ? 'upto-[960px]:translate-x-0' : 'upto-[960px]:-translate-x-full'
        }`}
      >
        <div className="flex h-topbar shrink-0 items-center gap-3 border-0 border-b border-solid border-sidebar-line px-4">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-[linear-gradient(135deg,var(--primary)_0%,var(--violet)_100%)] text-lg font-extrabold tracking-[-0.03em] text-[#04121a] shadow-[0_0_20px_var(--primary-glow),inset_0_1px_0_rgba(255,255,255,0.35)]">
            K
          </div>
          <div>
            <div className="text-md font-semibold leading-[1.25] tracking-[-0.01em] text-sidebar-strong">Karnex License Center</div>
            <div className="mt-[3px] inline-flex items-center gap-[5px] rounded-full border border-solid border-primary-border bg-primary-soft px-2 py-px text-[9px] font-bold uppercase tracking-[0.14em] text-primary">
              {role.badge}
            </div>
          </div>
        </div>
        <nav className="flex-1 pb-6 pt-2">
          {visibleSections.map((section, i) => (
            <div key={i}>
              {section.title && (
                <div className="px-4 pb-1 pt-4 text-2xs font-bold uppercase tracking-[0.12em] text-sidebar-section">
                  {section.title}
                </div>
              )}
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  className={({ isActive }) => `${NAV_LINK} ${isActive ? NAV_LINK_ACTIVE : NAV_LINK_IDLE}`}
                  onClick={() => setSidebarOpen(false)}
                >
                  {({ isActive }) => (
                    <>
                      <span
                        className={`flex h-4 w-4 shrink-0 items-center justify-center transition-[opacity,filter] duration-ui ease-ui ${
                          isActive ? 'opacity-100' : 'opacity-85 group-hover:opacity-100'
                        }`}
                      >
                        <Icon name={item.icon} size={16} />
                      </span>
                      {item.label}
                      {item.badge === 'pendingApprovals' && pendingApprovals !== null && pendingApprovals > 0 && (
                        <span
                          className={`ml-auto inline-flex h-[17px] min-w-[18px] items-center justify-center rounded-full border border-solid px-1.5 text-2xs font-bold leading-none tabular-nums ${
                            isActive
                              ? 'border-[rgba(6,19,28,0.24)] bg-[rgba(6,19,28,0.16)] text-[#06131c]'
                              : 'border-danger-border bg-danger-soft text-danger'
                          }`}
                          title={`${pendingApprovals} pending change request(s)`}
                        >
                          {pendingApprovals > 99 ? '99+' : pendingApprovals}
                        </span>
                      )}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>
      <div className="ml-sidebar flex min-w-0 flex-1 flex-col upto-[960px]:ml-0">
        <header className="sticky top-0 z-30 flex h-topbar items-center justify-between gap-4 border-0 border-b border-solid border-line bg-glass px-6 backdrop-blur-glass backdrop-saturate-glass upto-[960px]:px-4">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              className="icon-btn hidden upto-[960px]:inline-flex"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open navigation menu"
            >
              <Icon name="menu" size={18} />
            </button>
            <form
              className="group relative max-w-[420px] flex-1 upto-[860px]:hidden"
              onSubmit={(e) => {
                e.preventDefault();
                const q = search.trim();
                if (q) navigate(`/licenses?q=${encodeURIComponent(q)}`);
              }}
              role="search"
            >
              <span className="pointer-events-none absolute left-3 top-1/2 flex -translate-y-1/2 text-muted group-focus-within:text-primary">
                <Icon name="search" size={15} />
              </span>
              <input
                className="input h-[34px] min-h-[34px] rounded-full pl-[34px]"
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search licence, serial, key or customer…"
                aria-label="Search licenses"
              />
            </form>
          </div>
          <div className="flex items-center gap-2">
            <ServerClock />
            <NotificationBell />
            <button
              type="button"
              className="icon-btn"
              onClick={() => navigate('/licenses?expiring=1')}
              aria-label="Licences expiring soon"
              title="Licences expiring soon"
            >
              <Icon name="alert-triangle" size={17} />
            </button>
            <button
              type="button"
              className="icon-btn"
              onClick={toggleTheme}
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
            >
              <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={17} />
            </button>
            <div className="mx-1 h-6 w-px bg-line" />
            <div className="flex items-center gap-2">
              <div className="text-right leading-[1.25] upto-[960px]:hidden">
                <div className="text-base font-semibold">{displayName}</div>
                {/* Real role names only — an unknown role is shown as nothing
                    rather than a guess that would make everyone an admin. */}
                {roleLabel && (
                  <div className="text-2xs font-semibold uppercase tracking-[0.08em] text-muted">{roleLabel}</div>
                )}
              </div>
              <div
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-solid border-primary-border bg-[linear-gradient(135deg,var(--primary-soft),var(--violet-soft))] text-sm font-bold text-primary shadow-[0_0_14px_var(--primary-glow)]"
                aria-hidden
              >
                {initials(displayName)}
              </div>
            </div>
            <button type="button" className="icon-btn" onClick={handleLogout} aria-label="Sign out" title="Sign out">
              <Icon name="logout" size={17} />
            </button>
          </div>
        </header>
        <main className="w-full max-w-[1520px] px-6 pb-10 pt-6 upto-[960px]:px-4 upto-[960px]:pb-8 upto-[960px]:pt-4">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
