/**
 * Shared primitives. These mirror `backend/app/schemas/common.py` and
 * `backend/app/core/constants.py` so the client can never drift from the API contract.
 */

export type UUID = string;

/** Timestamps as returned by the API (ISO-8601 strings). */
export interface Timestamped {
  id: UUID;
  created_at: string;
  updated_at: string;
  version: number;
}

/** Generic paged envelope: `Page[T]` on the server. */
export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface DeletedResponse {
  id: string;
  message: string;
}

export interface HealthResponse {
  status: 'ok';
}

export interface ReadinessResponse {
  status: 'ok' | 'degraded';
  database: boolean;
  auth: boolean;
  detail?: string | null;
  auth_config?: Record<string, unknown> | null;
}

export interface ErrorDetail {
  code: string;
  message: string;
  details?: unknown;
}

/** The single error envelope every endpoint uses. */
export interface ErrorResponse {
  error: ErrorDetail;
}

export interface UserResponse {
  id: UUID;
  email: string | null;
}

// ------------------------------------------------------------------------- enums

export type ProblemStatus =
  | 'not_started'
  | 'attempted'
  | 'solved'
  | 'needs_revision'
  | 'mastered';

export type Difficulty = 'easy' | 'medium' | 'hard';

export type AttemptOutcome =
  | 'gave_up'
  | 'partial'
  | 'solved'
  | 'solved_with_hint'
  | 'revision_success'
  | 'revision_failed';

export type TopicStatus = 'not_started' | 'learning' | 'completed' | 'needs_revision' | 'mastered';

export type LLDCategory = 'fundamentals' | 'design_patterns' | 'design_exercises';

export type HLDCategory = 'fundamentals' | 'system_design';

export type ItemType = 'dsa_new' | 'dsa_revision' | 'lld' | 'hld';

export type PlanStatus = 'active' | 'completed' | 'abandoned';

export type RevisionReason =
  | 'low_confidence'
  | 'failed_attempt'
  | 'scheduled_revision'
  | 'manual'
  | 'long_time_since_review';

export type RevisionResult = 'success' | 'failed' | 'partial';

export type SessionType = 'dsa' | 'lld' | 'hld' | 'revision' | 'mock_interview';

export type Language =
  | 'python'
  | 'java'
  | 'swift'
  | 'cpp'
  | 'javascript'
  | 'typescript'
  | 'go'
  | 'other';

export type AIContextType = 'dsa' | 'lld' | 'hld' | 'general';

export type AIAction =
  | 'explain_concept'
  | 'give_hint'
  | 'explain_code'
  | 'find_bug'
  | 'complexity'
  | 'alternative_approach'
  | 'interview_me'
  | 'general'
  // Design-workspace actions. The server exposes these through `GET /ai/actions`; they are
  // listed here so the panel can request them without a cast.
  | 'review_design'
  | 'solid_check'
  | 'missing_classes'
  | 'review_architecture'
  | 'scaling_bottlenecks'
  | 'database_choice'
  | 'api_design_review'
  | 'challenge_assumptions'
  | 'failure_scenarios';

export type DeviceType = 'ios' | 'web' | 'android' | 'other';

// ---------------------------------------------------------------- shared shapes

/** Per-row progress embedded in catalog listings. */
export interface ProgressSummary {
  status: ProblemStatus;
  attempts: number;
  confidence: number | null;
  is_favorite: boolean;
  next_revision_at: string | null;
  solved_at: string | null;
  total_time_spent_minutes: number;
}

export interface TopicProgressSummary {
  status: TopicStatus;
  confidence: number | null;
  completed_at: string | null;
  next_revision_at: string | null;
  last_reviewed_at: string | null;
  total_time_spent_minutes: number;
}

export interface StreakInfo {
  current: number;
  longest: number;
  last_active_date: string | null;
  today_active: boolean;
}

export interface DifficultyBreakdown {
  difficulty: string;
  total: number;
  solved: number;
  mastered: number;
  attempted: number;
  completion_percentage: number;
}

export interface TopicBreakdown {
  topic: string;
  total: number;
  solved: number;
  mastered: number;
  attempted: number;
  needs_revision: number;
  completion_percentage: number;
  average_confidence: number | null;
}

export interface ActivityPoint {
  date: string;
  problems_attempted: number;
  problems_solved: number;
  revisions_completed: number;
  study_minutes: number;
  activity_count: number;
}

/** Chart ranges accepted by `GET /stats/activity`. */
export type ActivityRange = '7d' | '30d' | '90d' | '1y';

export interface CatalogTopic {
  slug: string;
  name?: string;
  title?: string;
  total?: number;
  solved?: number;
  count?: number;
}
