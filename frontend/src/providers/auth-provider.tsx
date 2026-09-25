import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { createAuthProvider, type AuthProvider, type AuthUser } from '@/api/auth';
import { api } from '@/api/client';
import { setTokenResolver, setUnauthorizedHandler } from '@/api/http';
import { toApiError } from '@/api/errors';

interface AuthContextValue {
  user: AuthUser | null;
  /** True until the initial session lookup resolves. */
  initialising: boolean;
  signingIn: boolean;
  error: string | null;
  isDemo: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  clearError: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  // One provider instance for the app's lifetime; it is stateless with respect to React.
  const providerRef = useRef<AuthProvider | null>(null);
  if (!providerRef.current) providerRef.current = createAuthProvider();
  const provider = providerRef.current;

  const queryClient = useQueryClient();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [initialising, setInitialising] = useState(true);
  const [signingIn, setSigningIn] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Wire the transport layer to this provider once, before any request can fire.
  useEffect(() => {
    setTokenResolver(() => provider.getAccessToken());
    setUnauthorizedHandler(() => {
      // A rejected token means the session is dead; drop it and let the guard redirect.
      setUser(null);
      queryClient.clear();
    });
  }, [provider, queryClient]);

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      try {
        const resolved = await provider.getUser();
        if (!cancelled) setUser(resolved);
      } catch {
        if (!cancelled) setUser(null);
      } finally {
        if (!cancelled) setInitialising(false);
      }
    })();

    const unsubscribe = provider.subscribe((next) => {
      if (!cancelled) setUser(next);
    });

    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [provider]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      setSigningIn(true);
      setError(null);
      try {
        const next = await provider.signIn(email, password);
        setUser(next);
        // Drop anything cached under the previous identity.
        queryClient.clear();
        // Confirm the token actually works against the API before declaring success.
        await api.users.me();
      } catch (caught) {
        const apiError = toApiError(caught);
        setError(apiError.message);
        throw apiError;
      } finally {
        setSigningIn(false);
      }
    },
    [provider, queryClient],
  );

  const signUp = useCallback(
    async (email: string, password: string) => {
      setSigningIn(true);
      setError(null);
      try {
        const next = await provider.signUp(email, password);
        setUser(next);
        queryClient.clear();
      } catch (caught) {
        const apiError = toApiError(caught);
        setError(apiError.message);
        throw apiError;
      } finally {
        setSigningIn(false);
      }
    },
    [provider, queryClient],
  );

  const signOut = useCallback(async () => {
    await provider.signOut();
    setUser(null);
    queryClient.clear();
  }, [provider, queryClient]);

  const clearError = useCallback(() => setError(null), []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      initialising,
      signingIn,
      error,
      isDemo: provider.kind === 'demo',
      signIn,
      signUp,
      signOut,
      clearError,
    }),
    [user, initialising, signingIn, error, provider.kind, signIn, signUp, signOut, clearError],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside an AuthProvider');
  return context;
}
