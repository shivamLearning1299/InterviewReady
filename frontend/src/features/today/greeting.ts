/** Time-of-day greeting and other small Today-specific derivations. */

export function greetingFor(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 5) return 'Still up';
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  if (hour < 22) return 'Good evening';
  return 'Good night';
}

/** Inclusive ISO date bounds for the last `days` days, ending today. */
export function weekBounds(days = 7): { start_date: string; end_date: string } {
  const end = new Date();
  const start = new Date();
  start.setDate(end.getDate() - (days - 1));

  const key = (value: Date) => {
    const year = value.getFullYear();
    const month = `${value.getMonth() + 1}`.padStart(2, '0');
    const day = `${value.getDate()}`.padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  return { start_date: key(start), end_date: key(end) };
}
