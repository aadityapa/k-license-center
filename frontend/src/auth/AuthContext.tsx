import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { AuthUser } from '../types';
import { tokenStore, userStore } from '../services/api/http';
import { authApi } from '../services/api/endpoints';

interface AuthContextValue {
  user: AuthUser | null;
  initializing: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  hasPermission: (...perms: string[]) => boolean;
}

/** Exported so a component can be rendered against a stub context in a check. */
export const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => userStore.get<AuthUser>());
  const [initializing, setInitializing] = useState<boolean>(true);

  // Re-validate the session on load: refresh user + permissions from the server.
  // Always attempt /auth/me even without a stored token — when the backend runs
  // with AUTH_DISABLED (demo mode) it succeeds and we skip the login screen.
  useEffect(() => {
    let cancelled = false;
    authApi
      .me()
      .then((me) => {
        if (!cancelled) {
          setUser(me);
          userStore.set(me);
        }
      })
      .catch(() => {
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setInitializing(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await authApi.login(username, password);
    tokenStore.set(res.token);
    userStore.set(res.user);
    setUser(res.user);
  }, []);

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      /* best effort */
    }
    tokenStore.clear();
    setUser(null);
  }, []);

  const hasPermission = useCallback(
    (...perms: string[]) => {
      if (!user) return false;
      if (perms.length === 0) return true;
      const owned = user.permissions ?? [];
      return perms.some((p) => owned.includes(p));
    },
    [user],
  );

  const value = useMemo(
    () => ({ user, initializing, login, logout, hasPermission }),
    [user, initializing, login, logout, hasPermission],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
