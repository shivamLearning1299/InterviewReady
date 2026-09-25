import type {
  ActivityPoint,
  ActivityRange,
  DifficultyBreakdown,
  TopicBreakdown,
} from '@/types/common';

/** Analytics payloads — mirrors `schemas/stats.py`. */

// `ActivityRange` lives in the shared layer but is re-exported here, since this is the
// module that consumes it.
export type { ActivityRange };

export interface DSAStats {
  total: number;
  solved: number;
  mastered: number;
  attempted: number;
  needs_revision: number;
  not_started: number;
}

export interface TopicStats {
  completed: number;
  total: number;
  mastered: number;
  learning: number;
}

export interface StudyTimeStats {
  today_minutes: number;
  week_minutes: number;
  month_minutes: number;
  total_minutes: number;
}

export interface StatsOverview {
  dsa: DSAStats;
  lld: TopicStats;
  hld: TopicStats;
  streak: {
    current: number;
    longest: number;
    last_active_date: string | null;
    today_active: boolean;
  };
  study_time: StudyTimeStats;
  revision_due: number;
  revision_overdue: number;
  problems_solved_today: number;
  days_active_last_30: number;
}

export interface TopicStatsResponse {
  items: TopicBreakdown[];
  total: number;
}

export interface DifficultyStatsResponse {
  items: DifficultyBreakdown[];
}

export interface ActivityResponse {
  range: ActivityRange;
  start: string;
  end: string;
  granularity: 'day' | 'week' | 'month';
  items: ActivityPoint[];
  totals: Record<string, number>;
}

export interface StreakResponse {
  current: number;
  longest: number;
  last_active_date: string | null;
  today_active: boolean;
  min_minutes_required: number;
  timezone: string;
}

export interface MasteryResponse {
  dsa?: Record<string, number>;
  lld?: Record<string, number>;
  hld?: Record<string, number>;
  [key: string]: Record<string, number> | undefined;
}
