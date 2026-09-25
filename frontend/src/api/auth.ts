import { HAS_SUPABASE, STORAGE_KEYS, SUPABASE_ANON_KEY, SUPABASE_URL, USE_MOCKS } from '@/api/config';
import { ApiError } from '@/api/errors';
import type { UserResponse } from '@/types/common';

export interface AuthUser {
  id: string;
  email: string;
  name: string;
}

/**
 * Auth is behind an interface so the app can run three ways with no UI changes:
 * in-memory demo (mock mode), a locally persisted demo session, or real Supabase Auth.
 */
export interface AuthProvider {
  readonly kind: 'demo' | 'supabase';
  getAccessToken(): Promise<string | null>;
  getUser(): Promise<AuthUser | null>;
  subscribe(listener: (user: AuthUser | null) => void): () => void;
  signIn(email: string, password: string): Promise<AuthUser>;
  signUp(email: string, password: string): Promise<AuthUser>;
  signOut(): Promise<void>;
}

// --------------------------------------------------------------------- demo provider

interface DemoSession {
  user: AuthUser;
  token: string;
  createdAt: string;
}

const DEMO_NAME_BY_EMAIL = new Map<string, string>();

function readDemoSession(): DemoSession | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.demoSession);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<DemoSession>;
    if (!parsed.user?.id || !parsed.token) return null;
    return parsed as DemoSession;
  } catch {
    return null;
  }
}

function writeDemoSession(session: DemoSession | null): void {
  try {
    if (session) {
      localStorage.setItem(STORAGE_KEYS.demoSession, JSON.stringify(session));
    } else {
      localStorage.removeItem(STORAGE_KEYS.demoSession);
    }
  } catch {
    /* storage may be unavailable in private browsing — the app still works in memory */
  }
}

function nameFromEmail(email: string): string {
  const cached = DEMO_NAME_BY_EMAIL.get(email);
  if (cached) return cached;
  const local = email.split('@')[0] ?? 'there';
  const name = local
    .split(/[.\-_]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
  DEMO_NAME_BY_EMAIL.set(email, name);
  return name || 'there';
}

/**
 * Demo auth: any email/password is accepted and the session is persisted locally.
 * This is what makes mock mode feel like a real signed-in app.
 */
class DemoAuthProvider implements AuthProvider {
  readonly kind = 'demo' as const;

  private listeners = new Set<(user: AuthUser | null) => void>();

  async getAccessToken(): Promise<string | null> {
    return readDemoSession()?.token ?? null;
  }

  async getUser(): Promise<AuthUser | null> {
    return readDemoSession()?.user ?? null;
  }

  subscribe(listener: (user: AuthUser | null) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(user: AuthUser | null): void {
    this.listeners.forEach((listener) => listener(user));
  }

  async signIn(email: string, _password: string): Promise<AuthUser> {
    void _password; // accepted but never used in demo mode
    if (!email.includes('@')) {
      throw new ApiError('Enter a valid email address.', 'INVALID_EMAIL', 422);
    }
    const user: AuthUser = {
      id: 'demo-user-0001',
      email,
      name: nameFromEmail(email),
    };
    writeDemoSession({ user, token: 'demo-access-token', createdAt: new Date().toISOString() });
    this.emit(user);
    return user;
  }

  async signUp(email: string, password: string): Promise<AuthUser> {
    return this.signIn(email, password);
  }

  async signOut(): Promise<void> {
    writeDemoSession(null);
    this.emit(null);
  }
}

// ----------------------------------------------------------------- supabase provider

interface SupabaseUserLike {
  id: string;
  email?: string | null;
  user_metadata?: Record<string, unknown>;
}

interface SupabaseClientLike {
  auth: {
    getSession: () => Promise<{ data: { session: { access_token: string } | null } }>;
    getUser: () => Promise<{ data: { user: SupabaseUserLike | null } }>;
    onAuthStateChange: (
      callback: (event: string, session: { access_token: string } | null) => void,
    ) => { data: { subscription: { unsubscribe: () => void } } };
    signInWithPassword: (credentials: {
      email: string;
      password: string;
    }) => Promise<{ data: { user: SupabaseUserLike | null }; error: { message: string } | null }>;
    signUp: (credentials: {
      email: string;
      password: string;
    }) => Promise<{ data: { user: SupabaseUserLike | null }; error: { message: string } | null }>;
    signOut: () => Promise<{ error: { message: string } | null }>;
  };
}

function toAuthUser(user: SupabaseUserLike): AuthUser {
  const email = user.email ?? '';
  const metaName = user.user_metadata?.full_name;
  return {
    id: user.id,
    email,
    name: typeof metaName === 'string' && metaName ? metaName : nameFromEmail(email),
  };
}

/** Real Supabase Auth. The SDK is imported lazily so mock mode never loads it. */
class SupabaseAuthProvider implements AuthProvider {
  readonly kind = 'supabase' as const;

  private client: SupabaseClientLike | null = null;
  private loading: Promise<SupabaseClientLike> | null = null;

  private async getClient(): Promise<SupabaseClientLike> {
    if (this.client) return this.client;
    if (!this.loading) {
      this.loading = (async () => {
        const module = (await import('@supabase/supabase-js')) as unknown as {
          createClient: (url: string, key: string) => unknown;
        };
        const created = module.createClient(SUPABASE_URL, SUPABASE_ANON_KEY) as SupabaseClientLike;
        this.client = created;
        return created;
      })();
    }
    return this.loading;
  }

  async getAccessToken(): Promise<string | null> {
    const client = await this.getClient();
    const { data } = await client.auth.getSession();
    return data.session?.access_token ?? null;
  }

  async getUser(): Promise<AuthUser | null> {
    const client = await this.getClient();
    const { data } = await client.auth.getUser();
    return data.user ? toAuthUser(data.user) : null;
  }

  subscribe(listener: (user: AuthUser | null) => void): () => void {
    let unsubscribe: (() => void) | undefined;
    let disposed = false;

    void (async () => {
      const client = await this.getClient();
      if (disposed) return;
      const { data } = client.auth.onAuthStateChange((_event, session) => {
        if (!session) {
          listener(null);
          return;
        }
        void (async () => {
          const user = await this.getUser();
          listener(user);
        })();
      });
      unsubscribe = () => data.subscription.unsubscribe();
    })();

    return () => {
      disposed = true;
      unsubscribe?.();
    };
  }

  async signIn(email: string, password: string): Promise<AuthUser> {
    const client = await this.getClient();
    const { data, error } = await client.auth.signInWithPassword({ email, password });
    if (error) throw new ApiError(error.message, 'AUTH_ERROR', 401);
    if (!data.user) throw new ApiError('Sign in did not return a user.', 'AUTH_ERROR', 401);
    return toAuthUser(data.user);
  }

  async signUp(email: string, password: string): Promise<AuthUser> {
    const client = await this.getClient();
    const { data, error } = await client.auth.signUp({ email, password });
    if (error) throw new ApiError(error.message, 'AUTH_ERROR', 422);
    if (!data.user) throw new ApiError('Sign up did not return a user.', 'AUTH_ERROR', 422);
    return toAuthUser(data.user);
  }

  async signOut(): Promise<void> {
    const client = await this.getClient();
    await client.auth.signOut();
  }
}

// -------------------------------------------------------------------------- factory

/**
 * Chooses the auth backend. Mock mode always wins, so a half-configured Supabase
 * environment cannot break the demo experience.
 */
export function createAuthProvider(): AuthProvider {
  if (!USE_MOCKS && HAS_SUPABASE) return new SupabaseAuthProvider();
  return new DemoAuthProvider();
}

/** Shape-check a `/users/me` response into an `AuthUser`. */
export function authUserFromResponse(response: UserResponse, fallbackEmail: string): AuthUser {
  const email = response.email ?? fallbackEmail;
  return { id: response.id, email, name: nameFromEmail(email) };
}
