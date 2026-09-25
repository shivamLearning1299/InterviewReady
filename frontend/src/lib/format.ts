import { format, formatDistanceToNowStrict, isToday, isYesterday, parseISO } from 'date-fns';

import { percent } from '@/lib/helpers';

/** Parse an ISO timestamp/date defensively — bad data yields `null`, never an exception. */
export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const parsed = parseISO(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatDate(value: string | null | undefined, pattern = 'd MMM yyyy'): string {
  const date = parseDate(value);
  return date ? format(date, pattern) : '—';
}

export function formatShortDate(value: string | null | undefined): string {
  return formatDate(value, 'd MMM');
}

/** "Today" / "Yesterday" / "12 Mar" — used in revision and attempt tables. */
export function formatRelativeDay(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return '—';
  if (isToday(date)) return 'Today';
  if (isYesterday(date)) return 'Yesterday';
  return format(date, 'd MMM');
}

export function formatRelativeTime(value: string | null | undefined): string {
  const date = parseDate(value);
  if (!date) return '—';
  return `${formatDistanceToNowStrict(date)} ago`;
}

/** Days until a future date; negative when overdue. Null when the date is missing. */
export function daysUntil(value: string | null | undefined): number | null {
  const date = parseDate(value);
  if (!date) return null;
  const dayMs = 24 * 60 * 60 * 1000;
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const target = new Date(date);
  target.setHours(0, 0, 0, 0);
  return Math.round((target.getTime() - start.getTime()) / dayMs);
}

/** Human label for a due date, phrased for a revision queue. */
export function describeDue(value: string | null | undefined): string {
  const days = daysUntil(value);
  if (days === null) return 'Not scheduled';
  if (days === 0) return 'Due today';
  if (days === 1) return 'Due tomorrow';
  if (days === -1) return '1 day overdue';
  if (days < 0) return `${Math.abs(days)} days overdue`;
  return `Due in ${days} days`;
}

/** Minutes -> "1h 20m" / "45m". */
export function formatMinutes(minutes: number | null | undefined): string {
  const total = Math.max(0, Math.round(minutes ?? 0));
  if (total < 60) return `${total}m`;
  const hours = Math.floor(total / 60);
  const remainder = total % 60;
  return remainder === 0 ? `${hours}h` : `${hours}h ${remainder}m`;
}

/**
 * Seconds -> "MM:SS" / "H:MM:SS" for the study timer.
 */
export function formatClock(totalSeconds: number): string {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = safe % 60;
  const pad = (value: number) => value.toString().padStart(2, '0');
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`;
}

/** Elapsed seconds since an ISO start time, clamped at zero. */
export function elapsedSecondsFrom(startedAt: string | null | undefined, nowMs: number): number {
  const date = parseDate(startedAt);
  if (!date) return 0;
  return Math.max(0, Math.floor((nowMs - date.getTime()) / 1000));
}

export { percent };
