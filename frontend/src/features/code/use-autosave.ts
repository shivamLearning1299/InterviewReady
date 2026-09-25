import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Debounced autosave with honest state reporting.
 *
 * The editor stays fully responsive: keystrokes update local state immediately and the
 * network write is deferred. The returned `status` is what the editor's status bar shows,
 * so "Saved" is never claimed before the server confirmed it.
 */
export interface AutosaveState {
  /** Current local value — always reflects what the user typed. */
  value: string;
  /** Update the local value (called on every keystroke). */
  setValue: (next: string) => void;
  status: 'idle' | 'saving' | 'saved' | 'error';
  /** Force an immediate write, e.g. on blur or before navigating away. */
  flush: () => Promise<void>;
  /** True when local state differs from the last successfully persisted value. */
  isDirty: boolean;
  lastSavedAt: string | null;
}

export function useAutosave<T>(
  initialValue: string,
  save: (value: string) => Promise<T>,
  options: { delayMs?: number; enabled?: boolean } = {},
): AutosaveState {
  // The generic is retained so callers can type the save result without a cast, but the
  // hook itself only reports status.
  void 0 as T | undefined;
  const { delayMs = 900, enabled = true } = options;

  const [value, setValueState] = useState(initialValue);
  const [status, setStatus] = useState<AutosaveState['status']>('idle');
  const [lastSavedAt, setLastSavedAt] = useState<string | null>(null);

  /** Last value confirmed by the server. */
  const savedRef = useRef(initialValue);
  /** Latest value, readable from timers without re-creating them. */
  const valueRef = useRef(initialValue);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlightRef = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  // Re-baseline when the caller swaps to a different record (e.g. another snippet).
  useEffect(() => {
    valueRef.current = initialValue;
    savedRef.current = initialValue;
    setValueState(initialValue);
    setStatus('idle');
    setLastSavedAt(null);
  }, [initialValue]);

  const persist = useCallback(async () => {
    if (!enabled) return;
    const pending = valueRef.current;
    if (pending === savedRef.current) return;
    if (inFlightRef.current) return;

    inFlightRef.current = true;
    setStatus('saving');

    try {
      await save(pending);
      savedRef.current = pending;
      if (!mountedRef.current) return;
      setLastSavedAt(new Date().toISOString());
      // Only claim "saved" if nothing changed while the request was in flight.
      setStatus(valueRef.current === pending ? 'saved' : 'idle');
    } catch {
      if (mountedRef.current) setStatus('error');
    } finally {
      inFlightRef.current = false;
    }
  }, [enabled, save]);

  const setValue = useCallback(
    (next: string) => {
      valueRef.current = next;
      setValueState(next);

      if (!enabled) return;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        void persist();
      }, delayMs);
    },
    [delayMs, enabled, persist],
  );

  const flush = useCallback(async () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    await persist();
  }, [persist]);

  // Best-effort write when the tab is hidden or closed mid-edit.
  useEffect(() => {
    if (!enabled) return;
    const handler = () => {
      if (valueRef.current !== savedRef.current) void persist();
    };
    document.addEventListener('visibilitychange', handler);
    return () => document.removeEventListener('visibilitychange', handler);
  }, [enabled, persist]);

  return {
    value,
    setValue,
    status,
    flush,
    isDirty: value !== savedRef.current,
    lastSavedAt,
  };
}
