/** Narrow runtime helpers shared across the app. */

export function isPresent<T>(value: T | null | undefined): value is T {
  return value !== null && value !== undefined;
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/** Percentage that never divides by zero and never exceeds 100. */
export function percent(part: number, total: number): number {
  if (!total) return 0;
  return clamp(Math.round((part / total) * 100), 0, 100);
}

export function pluralize(count: number, singular: string, plural?: string): string {
  return count === 1 ? singular : (plural ?? `${singular}s`);
}

/** Trailing-edge debounce for search inputs. */
export function debounce<Args extends unknown[]>(
  fn: (...args: Args) => void,
  waitMs = 300,
): ((...args: Args) => void) & { cancel: () => void } {
  let handle: ReturnType<typeof setTimeout> | undefined;

  const wrapped = (...args: Args) => {
    if (handle) clearTimeout(handle);
    handle = setTimeout(() => fn(...args), waitMs);
  };

  wrapped.cancel = () => {
    if (handle) clearTimeout(handle);
    handle = undefined;
  };

  return wrapped;
}

/** Stable-ish unique id for optimistic rows and local-only keys. */
export function localId(prefix = 'local'): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 10)}`;
}

/** First letters of a person's name/email, for the avatar fallback. */
export function initials(value: string): string {
  const source = value.split('@')[0] ?? value;
  const parts = source.split(/[.\-_\s]+/).filter(Boolean);
  if (parts.length === 0) return 'IR';
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return `${parts[0]![0]}${parts[1]![0]}`.toUpperCase();
}
