/**
 * Deterministic helpers for the mock data layer.
 *
 * Seeded rather than random so a reload produces the same catalogs, streaks and charts —
 * mock data that shifts on every refresh makes UI bugs impossible to reproduce.
 */

/** FNV-1a — small, fast, stable across runs. */
function hashString(input: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/** Mulberry32 PRNG returning floats in [0, 1). */
export function seededRandom(seed: string): () => number {
  let state = hashString(seed);
  return () => {
    state |= 0;
    state = (state + 0x6d2b79f5) | 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Deterministic integer in [min, max]. */
export function seededInt(seed: string, min: number, max: number): number {
  const value = seededRandom(seed)();
  return Math.floor(min + value * (max - min + 1));
}

/** Deterministic pick from a list. */
export function seededPick<T>(seed: string, values: readonly T[]): T {
  const index = seededInt(`${seed}:pick`, 0, Math.max(0, values.length - 1));
  return values[index] as T;
}

// ------------------------------------------------------------------- time helpers

const DAY_MS = 24 * 60 * 60 * 1000;

/** Local calendar day key (`YYYY-MM-DD`) — matches how the API keys daily plans. */
export function dayKey(date: Date): string {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, '0');
  const day = `${date.getDate()}`.padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function todayKey(): string {
  return dayKey(new Date());
}

export function startOfDay(date: Date): Date {
  const copy = new Date(date);
  copy.setHours(0, 0, 0, 0);
  return copy;
}

export function addDays(date: Date, days: number): Date {
  return new Date(date.getTime() + days * DAY_MS);
}

/** ISO timestamp `days` away from now, at a fixed hour so values look hand-written. */
export function isoAtOffsetDays(days: number, hour = 9, minute = 0): string {
  const target = addDays(startOfDay(new Date()), days);
  target.setHours(hour, minute, 0, 0);
  return target.toISOString();
}

export function isoNow(offsetMinutes = 0): string {
  return new Date(Date.now() + offsetMinutes * 60_000).toISOString();
}

/** A monotonically increasing, UUID-shaped id — indistinguishable in shape from the API's. */
export function createIdFactory(seed: string): () => string {
  let counter = hashString(seed) % 4096;
  return () => {
    counter += 1;
    const hex = counter.toString(16).padStart(12, '0');
    return `00000000-0000-4000-8000-${hex}`;
  };
}

export { hashString };
