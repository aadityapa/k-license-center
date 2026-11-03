import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from './AuthContext';
import { Spinner } from '../components/Spinner';

export function RequireAuth() {
  const { user, initializing } = useAuth();
  const location = useLocation();

  if (initializing) {
    return (
      <div className="fullpage-center">
        <Spinner size={32} />
      </div>
    );
  }

  // `user` is only set once /auth/me succeeded, so it is the authoritative signal.
  // Checking for a stored token as well would break AUTH_DISABLED demo mode, where the
  // server authenticates every request and no token is ever issued.
  if (!user) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }

  return <Outlet />;
}
