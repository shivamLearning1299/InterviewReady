/**
 * Client timezone, sent as the `X-Timezone` header so the server can resolve "today"
 * against the user's calendar day rather than UTC.
 */
export function getClientTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/** A short, human list of IANA zones for the settings picker. */
export const COMMON_TIMEZONES: string[] = [
  'UTC',
  'Asia/Kolkata',
  'Asia/Dubai',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Europe/London',
  'Europe/Berlin',
  'Europe/Paris',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'Australia/Sydney',
];

/** Include the machine's own zone in the picker even when it is unusual. */
export function timezoneOptions(): string[] {
  const current = getClientTimezone();
  return COMMON_TIMEZONES.includes(current) ? COMMON_TIMEZONES : [current, ...COMMON_TIMEZONES];
}
