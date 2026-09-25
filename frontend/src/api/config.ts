/**
 * Runtime configuration, resolved once at module load.
 *
 * Defaults are chosen so `npm run dev` works with nothing else set up: mock mode on and
 * the API pointed at the Vite dev proxy.
 */

function readFlag(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined || value.trim() === '') return fallback;
  return value.trim().toLowerCase() !== 'false';
}

function readString(value: string | undefined, fallback: string): string {
  const trimmed = value?.trim();
  return trimmed ? trimmed : fallback;
}

/**
 * When true the app renders from the in-memory mock layer: no network calls, no auth
 * required. Flip `VITE_USE_MOCKS=false` to talk to FastAPI for real.
 */
export const USE_MOCKS = readFlag(import.meta.env.VITE_USE_MOCKS, true);

/**
 * Base URL for every API call. `/api/v1` is proxied to the backend by Vite in dev.
 * The trailing slash is stripped so path joins stay predictable.
 */
export const API_BASE_URL = readString(import.meta.env.VITE_API_BASE_URL, '/api/v1').replace(
  /\/+$/,
  '',
);

export const SUPABASE_URL = readString(import.meta.env.VITE_SUPABASE_URL, '');
export const SUPABASE_ANON_KEY = readString(import.meta.env.VITE_SUPABASE_ANON_KEY, '');

/** Whether a real Supabase project is configured. */
export const HAS_SUPABASE = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);

/** Artificial latency for the mock layer so loading states are exercised honestly. */
export const MOCK_LATENCY_MS = 220;

/** Default page size for catalog and history tables. */
export const DEFAULT_PAGE_SIZE = 50;

/** How long a resolved query stays fresh before a background refetch. */
export const STALE_TIME_MS = 30_000;

/** localStorage keys. Namespaced so they never collide with other apps on the origin. */
export const STORAGE_KEYS = {
  theme: 'ir-theme',
  sidebar: 'ir-sidebar-collapsed',
  demoSession: 'ir-demo-session',
  deviceId: 'ir-device-id',
  draftPrefix: 'ir-draft:',
} as const;
