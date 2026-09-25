import { API_BASE_URL, USE_MOCKS } from '@/api/config';
import { ApiError, errorFromResponse, toApiError } from '@/api/errors';
import { getClientTimezone } from '@/lib/timezone';

export type QueryValue = string | number | boolean | null | undefined;

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  /** JSON request body. Mutually exclusive with `formData`. */
  body?: unknown;
  query?: Record<string, QueryValue>;
  /** Extra headers merged over the defaults. */
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Set false for endpoints that must be reachable without a token. */
  auth?: boolean;
  /** Return the raw `Response` instead of parsed JSON (used by the export endpoint). */
  raw?: boolean;
}

/** Builds `?a=1&b=2`, dropping empty values so filters stay out of the URL when unset. */
export function buildQuery(query?: Record<string, QueryValue>): string {
  if (!query) return '';
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    params.set(key, String(value));
  }
  const serialised = params.toString();
  return serialised ? `?${serialised}` : '';
}

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const normalised = path.startsWith('/') ? path : `/${path}`;
  return `${API_BASE_URL}${normalised}${buildQuery(query)}`;
}

/**
 * Injected by the auth provider at app start. Kept as a module-level callback rather than
 * an import so the auth provider can be swapped (mock <-> Supabase) without a cycle.
 */
type TokenResolver = () => Promise<string | null>;

let resolveToken: TokenResolver = async () => null;

export function setTokenResolver(resolver: TokenResolver): void {
  resolveToken = resolver;
}

/** Notified on every 401 so the auth layer can clear a dead session once. */
type UnauthorizedHandler = () => void;

let onUnauthorized: UnauthorizedHandler = () => {};

export function setUnauthorizedHandler(handler: UnauthorizedHandler): void {
  onUnauthorized = handler;
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204 || response.status === 205) return null;

  const text = await response.text();
  if (!text) return null;

  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.includes('json')) {
    try {
      return JSON.parse(text) as unknown;
    } catch {
      return text;
    }
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

/**
 * The single entry point for every HTTP call.
 *
 * Responsibilities: URL/query assembly, auth header, timezone header, JSON parsing and
 * uniform error normalisation. It deliberately knows nothing about React or caching.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, query, headers, signal, auth = true, raw = false } = options;

  if (USE_MOCKS) {
    // Defensive: the mock router intercepts at the `api` layer, so reaching here means a
    // call bypassed it. Failing loudly is better than silently hitting a real server.
    throw new ApiError(
      `Mock mode is enabled but "${path}" was called directly. Use the "api" service object.`,
      'MOCK_BYPASS',
      0,
    );
  }

  const requestHeaders: Record<string, string> = {
    Accept: 'application/json',
    'X-Timezone': getClientTimezone(),
    ...headers,
  };

  if (body !== undefined) {
    requestHeaders['Content-Type'] = 'application/json';
  }

  if (auth) {
    const token = await resolveToken();
    if (token) {
      requestHeaders.Authorization = `Bearer ${token}`;
    }
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      headers: requestHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    throw toApiError(error);
  }

  if (!response.ok) {
    const parsed = await parseBody(response);
    const apiError = errorFromResponse(response.status, parsed);
    if (apiError.isAuthError) onUnauthorized();
    throw apiError;
  }

  if (raw) {
    return response as unknown as T;
  }

  return (await parseBody(response)) as T;
}

/** Convenience wrappers — keeps endpoint modules free of method strings. */
export const http = {
  get: <T>(path: string, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'PATCH', body }),
  delete: <T>(path: string, options?: Omit<RequestOptions, 'method' | 'body'>) =>
    request<T>(path, { ...options, method: 'DELETE' }),
};

/** Trigger a browser download for the export endpoint (or any Blob). */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
