import { USE_MOCKS } from '@/api/config';
import type { ApiClient } from '@/api/contract';

import { realClient } from '@/api/endpoints/all';
import { mockClient } from '@/mocks/client';

/**
 * The single API object the application talks to.
 *
 * `VITE_USE_MOCKS` decides which implementation is bound at build time. Components import
 * `api` and nothing else, so switching to the live backend is a one-line environment change.
 */
export const api: ApiClient = USE_MOCKS ? mockClient : realClient;

/** True when the app is running against the in-memory mock layer. */
export const isMockMode = api.mode === 'mock';

export type { ApiClient };
