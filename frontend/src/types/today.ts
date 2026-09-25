import type { ItemType, ProgressSummary, UUID } from '@/types/common';

/** Daily plan payloads — mirrors `schemas/today.py`. */

export interface TodayItem {
  id: UUID;
  item_type: ItemType;
  position: number;
  problem_id: string | null;
  topic_id: UUID | null;
  title: string | null;
  slug: string | null;
  difficulty: string | null;
  primary_topic: string | null;
  patterns: string[];
  external_url: string | null;
  estimated_minutes: number | null;
  reason: string | null;
  is_completed: boolean;
  completed_at: string | null;
  progress: ProgressSummary | null;
}

export interface TodaySection {
  completed: number;
  total: number;
  items: TodayItem[];
}

export interface RevisionDueSummary {
  total: number;
  overdue: number;
  due_today: number;
  upcoming: number;
}

export interface TodayResponse {
  date: string;
  timezone: string;
  plan_id: UUID | null;
  status: string;
  generated_at: string | null;
  is_completed: boolean;

  streak: {
    current: number;
    longest: number;
    last_active_date: string | null;
    today_active: boolean;
  };

  dsa: TodaySection;
  lld: TodaySection;
  hld: TodaySection;
  revisions: TodaySection;
  revisions_due: number;
  revision_summary: RevisionDueSummary;

  study_minutes_today: number;
  active_session_id: UUID | null;
  total_estimated_minutes: number;
}

export interface DailyPlanSummary {
  id: UUID;
  created_at: string;
  updated_at: string;
  version: number;
  user_id: UUID;
  plan_date: string;
  timezone: string;
  status: string;
  generated_by: string;
  total_items: number;
  completed_items: number;
}

export interface DailyPlanDetail extends DailyPlanSummary {
  dsa: TodaySection;
  lld: TodaySection;
  hld: TodaySection;
  revisions: TodaySection;
}

export interface PlanGenerationDebug {
  candidate_count: number;
  new_problem_count: number;
  revision_count: number;
  weak_topics: string[];
  covered_topics: string[];
  scoring_version: string;
  explanation: Record<string, unknown>;
}

/** Weekly rollup composed on the client from plans + activity (no dedicated endpoint). */
export interface WeeklyProgress {
  dsaCompleted: number;
  dsaTarget: number;
  lldLessons: number;
  hldLessons: number;
  revisionsCompleted: number;
  studyMinutes: number;
}
