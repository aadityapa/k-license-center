import { useAuth } from './AuthContext';

/**
 * Which workspace the signed-in person gets.
 *
 * Derived from PERMISSIONS, never from role names — a custom role with the same
 * capabilities gets the same workspace, and renaming a role cannot break it.
 * Order matters: a checker is defined as "can approve but cannot submit", so it
 * is tested before maker.
 */
export type RoleKey = 'admin' | 'maker' | 'checker' | 'viewer';

export interface RoleIdentity {
  key: RoleKey;
  /** Name of the workspace, used as the dashboard title. */
  workspace: string;
  /** One line explaining what this person is here to do. */
  purpose: string;
  /** Short label for the sidebar badge. */
  badge: string;
}

const IDENTITIES: Record<RoleKey, Omit<RoleIdentity, 'key'>> = {
  admin: {
    workspace: 'Command Centre',
    purpose: 'Full control — your changes apply immediately',
    badge: 'Admin',
  },
  maker: {
    workspace: 'My Workspace',
    purpose: 'Prepare changes and send them for approval',
    badge: 'Maker',
  },
  checker: {
    workspace: 'Review Desk',
    purpose: 'Review what others submitted and decide',
    badge: 'Checker',
  },
  viewer: {
    workspace: 'Insights',
    purpose: 'Read-only view of the licence estate',
    badge: 'Viewer',
  },
};

export function useRoleIdentity(): RoleIdentity {
  const { hasPermission } = useAuth();

  const key: RoleKey = hasPermission('APPROVAL_BYPASS')
    ? 'admin'
    : hasPermission('REQUEST_APPROVE') && !hasPermission('REQUEST_SUBMIT')
      ? 'checker'
      : hasPermission('REQUEST_SUBMIT')
        ? 'maker'
        : 'viewer';

  return { key, ...IDENTITIES[key] };
}
