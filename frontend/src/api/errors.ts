import type { ErrorResponse } from '@/types/common';

/**
 * Every API failure is normalised into this one error type, so UI code can switch on
 * `code` without caring whether the failure was HTTP, network or parsing related.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: unknown;

  constructor(message: string, code = 'UNKNOWN_ERROR', status = 0, details: unknown = null) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.details = details;
  }

  /** True when retrying might succeed (network blips, 5xx, throttling). */
  get isRetryable(): boolean {
    return this.status === 0 || this.status === 429 || this.status >= 500;
  }

  get isAuthError(): boolean {
    return this.status === 401 || this.code === 'UNAUTHORIZED';
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

/** Narrow an unknown thrown value into an `ApiError`. */
export function toApiError(value: unknown): ApiError {
  if (isApiError(value)) return value;

  if (value instanceof DOMException && value.name === 'AbortError') {
    return new ApiError('Request cancelled', 'REQUEST_ABORTED', 0);
  }

  if (value instanceof TypeError) {
    return new ApiError(
      'Could not reach the server. Check your connection and try again.',
      'NETWORK_ERROR',
      0,
    );
  }

  if (value instanceof Error) {
    return new ApiError(value.message, 'CLIENT_ERROR', 0);
  }

  return new ApiError('Something went wrong', 'UNKNOWN_ERROR', 0, value);
}

/** Map the backend's `{error: {code, message}}` envelope, tolerating loose shapes. */
export function errorFromResponse(status: number, body: unknown): ApiError {
  const envelope = body as Partial<ErrorResponse> | null | undefined;
  const detail = envelope?.error;

  if (detail && typeof detail.message === 'string') {
    return new ApiError(detail.message, detail.code || `HTTP_${status}`, status, detail.details);
  }

  // FastAPI's own validation/handler shapes (`detail`) and bare strings.
  if (typeof body === 'string' && body.trim()) {
    return new ApiError(body, `HTTP_${status}`, status);
  }

  const fallback = (body as { detail?: unknown } | null | undefined)?.detail;
  if (typeof fallback === 'string') {
    return new ApiError(fallback, `HTTP_${status}`, status);
  }
  if (Array.isArray(fallback)) {
    const first = fallback[0] as { msg?: string } | undefined;
    return new ApiError(
      first?.msg ?? 'The request was rejected by the server.',
      'VALIDATION_ERROR',
      status,
      fallback,
    );
  }

  return new ApiError(defaultMessageForStatus(status), `HTTP_${status}`, status);
}

function defaultMessageForStatus(status: number): string {
  switch (status) {
    case 400:
      return 'That request was not valid.';
    case 401:
      return 'Your session has expired. Please sign in again.';
    case 403:
      return 'You do not have access to that.';
    case 404:
      return 'We could not find what you were looking for.';
    case 409:
      return 'That conflicts with a change made elsewhere.';
    case 422:
      return 'Some of the submitted values were rejected.';
    case 429:
      return 'Too many requests. Please slow down for a moment.';
    case 503:
      return 'The server is not ready to serve this request yet.';
    default:
      return status >= 500 ? 'The server ran into a problem.' : 'Something went wrong.';
  }
}

/** Short, non-technical message suitable for a toast. */
export function messageFor(error: unknown): string {
  return toApiError(error).message;
}
