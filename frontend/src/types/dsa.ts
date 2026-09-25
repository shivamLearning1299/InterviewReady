import type {
  AttemptOutcome,
  Difficulty,
  Language,
  ProgressSummary,
  ProblemStatus,
  Timestamped,
  UUID,
} from '@/types/common';

/** DSA catalog, progress, attempts, notes and code — mirrors `schemas/dsa.py`. */

// The API's status/attempt/language enums belong to the shared layer, but re-exporting them
// here means a consumer working on DSA data only needs this one import.
export type { AttemptOutcome, Difficulty, Language, ProblemStatus };

export interface DSAProblemSummary extends Timestamped {
  title: string;
  slug: string;
  external_url: string | null;
  source: string;
  difficulty: Difficulty;
  primary_topic: string;
  secondary_topics: string[];
  patterns: string[];
  companies: string[];
  problem_type: string;
  order_index: number;
  importance: number;
  estimated_minutes: number;
  is_active: boolean;
  progress: ProgressSummary;
}

export interface DSAProblemDetail extends Omit<DSAProblemSummary, 'progress'> {
  hints: unknown[] | null;
  progress: ProgressSummary | null;
  notes: ProblemNotes | null;
  code_snippets: CodeSnippet[];
  attempts: Attempt[];
  revisions: Revision[];
}

export interface DSAFilters {
  search?: string;
  topic?: string;
  pattern?: string;
  difficulty?: Difficulty | 'all';
  status?: ProblemStatus | 'all';
  company?: string;
  source?: string;
  revision_due?: boolean;
  favorites_only?: boolean;
  order_by?: 'curriculum' | 'difficulty' | 'title' | 'importance' | 'recent';
}

// ---------------------------------------------------------------------- progress

export interface ProgressUpdateRequest {
  status?: ProblemStatus;
  confidence?: number;
  time_spent_minutes?: number;
  attempts?: number;
  is_favorite?: boolean;
  notes?: string;
  schedule_revision?: boolean;
}

export interface ProgressResponse extends Timestamped {
  user_id: UUID;
  problem_id: string;
  status: ProblemStatus;
  attempts: number;
  confidence: number | null;
  revision_count: number;
  first_attempt_at: string | null;
  solved_at: string | null;
  last_reviewed_at: string | null;
  next_revision_at: string | null;
  total_time_spent_minutes: number;
  is_favorite: boolean;
}

// ---------------------------------------------------------------------- attempts

export interface AttemptCreateRequest {
  started_at?: string;
  completed_at?: string;
  duration_minutes?: number;
  outcome?: AttemptOutcome;
  notes?: string;
  update_progress?: boolean;
  confidence?: number;
}

export interface AttemptUpdateRequest {
  outcome?: AttemptOutcome;
  duration_minutes?: number;
  notes?: string;
  confidence?: number;
}

export interface Attempt extends Timestamped {
  user_id: UUID;
  problem_id: string;
  started_at: string | null;
  completed_at: string | null;
  duration_minutes: number | null;
  outcome: AttemptOutcome | null;
  notes: string | null;
  confidence: number | null;
}

// ------------------------------------------------------------------------- notes

export interface ProblemNotes extends Timestamped {
  user_id: UUID;
  problem_id: string;
  approach: string | null;
  notes: string | null;
  mistakes: string | null;
  revision_notes: string | null;
  time_complexity: string | null;
  space_complexity: string | null;
}

export interface ProblemNotesUpsert {
  approach?: string;
  notes?: string;
  mistakes?: string;
  revision_notes?: string;
  time_complexity?: string;
  space_complexity?: string;
}

// -------------------------------------------------------------------------- code

export interface CodeSnippet extends Timestamped {
  user_id: UUID;
  context_type: string;
  context_id: UUID;
  problem_id: string | null;
  title: string | null;
  language: Language;
  code: string;
  is_primary: boolean;
}

export interface CodeSnippetCreate {
  code: string;
  language: Language;
  title?: string;
  is_primary?: boolean;
}

export interface CodeSnippetUpdate {
  code?: string;
  language?: Language;
  title?: string;
  is_primary?: boolean;
}

// --------------------------------------------------------------------- revisions

export interface Revision extends Timestamped {
  user_id: UUID;
  problem_id: string;
  due_at: string;
  reason: string;
  priority: number;
  completed: boolean;
  completed_at: string | null;
  result: string | null;
  confidence_before: number | null;
  interval_days: number | null;
  notes: string | null;
  problem_title: string | null;
  problem_slug: string | null;
  problem_difficulty: string | null;
  problem_topic: string | null;
}

export interface RevisionCreateRequest {
  due_at?: string;
  reason?: string;
  priority?: number;
  notes?: string;
}

export interface RevisionCompleteRequest {
  result: 'success' | 'failed' | 'partial';
  confidence?: number;
  notes?: string;
  schedule_next?: boolean;
}

export interface RevisionCompleteResponse {
  revision: Revision;
  progress: ProgressResponse | null;
  next_revision: Revision | null;
  interval_days: number | null;
  message: string;
}

export interface RevisionSummary {
  due: number;
  overdue: number;
  due_today: number;
  upcoming: number;
}

// ------------------------------------------------------------------------ topics

export interface TopicOption {
  slug: string;
  name: string;
  total: number;
  solved?: number;
  mastered?: number;
}
