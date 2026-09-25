import { DEFAULT_PAGE_SIZE } from '@/api/config';
import { http } from '@/api/http';
import type { PageParams } from '@/api/contract';
import type { Page } from '@/types/common';
import type {
  StudySession,
  StudySessionStartRequest,
  StudySessionStopRequest,
  SyncStatus,
  UserDevice,
  UserSettings,
  UserSettingsUpdate,
} from '@/types/settings';

export const settingsEndpoints = {
  get: () => http.get<UserSettings>('/settings'),

  update: (payload: UserSettingsUpdate) => http.put<UserSettings>('/settings', payload),

  devices: () => http.get<{ items: UserDevice[] }>('/settings/devices'),

  upsertDevice: (payload: {
    device_identifier: string;
    device_type: string;
    display_name?: string;
  }) => http.put<UserDevice>('/settings/devices', payload),
};

export const syncEndpoints = {
  status: (deviceId?: string) =>
    http.get<SyncStatus>('/sync/status', { query: { device_id: deviceId } }),

  push: (payload: {
    device_id?: string;
    device_type?: string;
    mutations: {
      mutation_id: string;
      entity: string;
      operation?: string;
      record_id?: string;
      base_version?: number;
      payload?: Record<string, unknown>;
      client_timestamp?: string;
    }[];
  }) => http.post<{ results: unknown[]; cursor?: number }>('/sync/push', payload),

  pull: (params: { cursor?: number; limit?: number; device_id?: string } = {}) =>
    http.get<{ changes: unknown[]; next_cursor: number; has_more: boolean }>('/sync/pull', {
      query: {
        cursor: params.cursor ?? 0,
        limit: params.limit,
        device_id: params.device_id,
      },
    }),
};

export const studySessionEndpoints = {
  start: (payload: StudySessionStartRequest) =>
    http.post<StudySession>('/study-sessions/start', payload),

  stop: (sessionId: string, payload: StudySessionStopRequest = {}) =>
    http.post<StudySession>(`/study-sessions/${sessionId}/stop`, payload),

  list: (params: PageParams = {}) =>
    http.get<Page<StudySession>>('/study-sessions', {
      query: { limit: params.limit ?? DEFAULT_PAGE_SIZE, offset: params.offset ?? 0 },
    }),

  running: () => http.get<StudySession | null>('/study-sessions/running'),
};
