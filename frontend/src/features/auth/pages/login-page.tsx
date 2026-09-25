import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowRight, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Field, Input } from '@/components/ui/input';
import { useAuth } from '@/providers/auth-provider';
import { USE_MOCKS, HAS_SUPABASE } from '@/api/config';
import { routes } from '@/lib/query-keys';

/**
 * Sign-in.
 *
 * In demo mode the form accepts anything and says so, rather than pretending to validate.
 * A login screen that lies about what it checks is worse than one that admits it checks
 * nothing.
 */
export function LoginPage() {
  const { signIn, signUp, user, initialising, signingIn, error, clearError } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [mode, setMode] = useState<'signin' | 'signup'>('signin');
  const [email, setEmail] = useState('demo@interviewready.app');
  const [password, setPassword] = useState('demo-password');

  /** `RequireAuth` stashes the blocked route so the user lands where they meant to go. */
  const redirectTo =
    (location.state as { from?: { pathname?: string } } | null)?.from?.pathname ?? routes.today;

  useEffect(() => {
    if (user && !initialising) navigate(redirectTo, { replace: true });
  }, [user, initialising, navigate, redirectTo]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    clearError();
    try {
      if (mode === 'signin') await signIn(email, password);
      else await signUp(email, password);
      navigate(redirectTo, { replace: true });
    } catch {
      // The provider already surfaced a message through `error`.
    }
  };

  return (
    <div className="flex min-h-dvh items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 text-center">
          <Link to={routes.today} className="inline-flex items-center gap-2">
            <span className="flex size-7 items-center justify-center rounded-[var(--radius-control)] bg-primary text-[13px] font-bold text-primary-foreground">
              IR
            </span>
            <span className="text-sm font-semibold tracking-tight">InterviewReady</span>
          </Link>
          <h1 className="mt-4 text-lg font-semibold tracking-tight">
            {mode === 'signin' ? 'Sign in' : 'Create an account'}
          </h1>
          <p className="mt-1 text-[13px] text-muted-foreground">
            {mode === 'signin'
              ? 'Pick up where you left off.'
              : 'Start tracking DSA, design and revision in one place.'}
          </p>
        </div>

        <Card padding="md" className="space-y-4">
          <form onSubmit={submit} className="space-y-3.5">
            <Field label="Email" htmlFor="email">
              <Input
                id="email"
                type="email"
                autoComplete="email"
                required
                value={email}
                disabled={signingIn}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
              />
            </Field>

            <Field
              label="Password"
              htmlFor="password"
              hint={mode === 'signup' ? 'At least 8 characters.' : undefined}
            >
              <Input
                id="password"
                type="password"
                autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
                required
                value={password}
                disabled={signingIn}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="••••••••"
              />
            </Field>

            {error ? (
              <p role="alert" className="text-[12px] text-danger">
                {error}
              </p>
            ) : null}

            <Button type="submit" variant="primary" className="w-full" loading={signingIn}>
              {mode === 'signin' ? 'Sign in' : 'Create account'}
              <ArrowRight />
            </Button>
          </form>

          <button
            type="button"
            onClick={() => {
              clearError();
              setMode((value) => (value === 'signin' ? 'signup' : 'signin'));
            }}
            className="w-full text-center text-[12px] text-muted-foreground hover:text-foreground"
          >
            {mode === 'signin'
              ? 'No account yet? Create one'
              : 'Already have an account? Sign in'}
          </button>
        </Card>

        {/* Be explicit about what this form actually does. */}
        <div className="mt-4 rounded-[var(--radius-card)] border border-border bg-muted px-3.5 py-3 text-[12px] text-muted-foreground">
          {USE_MOCKS || !HAS_SUPABASE ? (
            <>
              <p className="font-medium text-foreground">Demo mode</p>
              <p className="mt-1 leading-relaxed">
                Any email and password will sign you in. Data is stored in this browser only —
                there is no server behind this build. Set{' '}
                <code className="font-mono">VITE_SUPABASE_URL</code> and{' '}
                <code className="font-mono">VITE_SUPABASE_ANON_KEY</code> to use real
                authentication.
              </p>
            </>
          ) : (
            <p className="leading-relaxed">
              Credentials are verified against Supabase. Your study data stays scoped to your
              account.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

/** Full-page loading state shown while the session is being restored. */
export function AuthLoadingScreen() {
  return (
    <div className="flex min-h-dvh items-center justify-center">
      <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" />
        Restoring session…
      </div>
    </div>
  );
}
