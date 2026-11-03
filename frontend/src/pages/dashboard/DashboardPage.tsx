/**
 * Dashboard selector.
 *
 * The landing view is chosen from the permissions the session actually carries —
 * never from a role name. `useRoleIdentity()` owns that derivation (and the
 * workspace title / purpose line each variant prints), so this file only maps
 * the resulting key onto a component:
 *
 *   admin   → Command Centre, the ops console
 *   checker → Review Desk, the approval inbox
 *   maker   → My Workspace, the submission board
 *   viewer  → Insights, the read-only report
 */
import { useRoleIdentity } from '../../auth/useRoleIdentity';
import { AdminDashboard } from './AdminDashboard';
import { CheckerDashboard } from './CheckerDashboard';
import { MakerDashboard } from './MakerDashboard';
import { ViewerDashboard } from './ViewerDashboard';

export function DashboardPage() {
  const role = useRoleIdentity();

  switch (role.key) {
    case 'admin':
      return <AdminDashboard />;
    case 'checker':
      return <CheckerDashboard />;
    case 'maker':
      return <MakerDashboard />;
    default:
      return <ViewerDashboard />;
  }
}
