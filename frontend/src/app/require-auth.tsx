import { Navigate, useLocation } from 'react-router-dom';
import { Loader2 } from 'lucide-react';

import { useAuth } from '@/providers/auth-provider';

/**
 * Route guard.
 *
 * Waits for the initial session lookup before deciding, so a signed-in user reloading the
 * page is never bounced to the login screen for a frame.
 */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user, initialising } = useAuth();
  const location = useLocation();

  if (initialising) {
    return (
      <div className="flex h-dvh items-center justify-center bg-background">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
        <span className="sr-only">Loading your session</span>
      </div>
    );
  }

  if (!user) {
    // Preserve where the user was heading so login can send them back.
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }

  return <>{children}</>;
}
