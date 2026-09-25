import type { DeviceType, Language, Timestamped, UUID } from '@/types/common';

/** Preferences, devices and sync — mirrors `schemas/settings.py` and `schemas/sync.py`. */

export interface UserSettings extends Timestamped {
  user_id: UUID;
  daily_dsa_count: number;
  daily_revision_count: number;
  include_lld_daily: boolean;
  include_hld_daily: boolean;
  daily_plan_preferences: Record<string, unknown> | null;
  revision_preferences: Record<string, unknown> | null;
  revision_enabled: boolean;
  ai_preferences: Record<string, unknown> | null;
  ai_auto_reveal_solution: boolean;
  timezone: string;
  preferred_languages: Language[];
  theme: string;
}

export interface UserSettingsUpdate {
  daily_dsa_count?: number;
  daily_revision_count?: number;
  include_lld_daily?: boolean;
  include_hld_daily?: boolean;
  revision_enabled?: boolean;
  ai_auto_reveal_solution?: boolean;
  timezone?: string;
  preferred_languages?: Language[];
  theme?: string;
}

export interface UserDevice extends Timestamped {
  user_id: UUID;
  device_identifier: string;
  device_type: DeviceType;
  display_name: string | null;
  last_sync_at: string | null;
  last_pull_cursor: number | null;
}

export interface SyncStatus {
  cursor: number;
  last_change_at: string | null;
  last_sync_at: string | null;
  device_id: string | null;
  device_count?: number;
  pending_changes?: number;
  [key: string]: unknown;
}

export interface StudySession extends Timestamped {
  user_id: UUID;
  session_type: string;
  context_id: UUID | null;
  started_at: string;
  ended_at: string | null;
  duration_minutes: number | null;
  is_running: boolean;
  notes: string | null;
}

export interface StudySessionStartRequest {
  session_type: string;
  context_id?: UUID | null;
}

export interface StudySessionStopRequest {
  notes?: string;
}

/** Persisted UI preferences that are not part of the server contract. */
export interface LocalPreferences {
  theme: 'light' | 'dark' | 'system';
  sidebarCollapsed: boolean;
  showStreakInHeader: boolean;
}
