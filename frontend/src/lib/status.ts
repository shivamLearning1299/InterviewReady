import type { AttemptOutcome, Difficulty, ProblemStatus, TopicStatus } from '@/types/common';

/**
 * Presentation metadata for the status enums.
 *
 * Kept in one module so a badge, a filter chip and a chart legend can never disagree about
 * what "needs_revision" looks like or what it is called.
 */

export interface StatusMeta {
  label: string;
  /** Tailwind classes for a subtle, bordered badge. */
  badgeClass: string;
  /** Solid dot / bar colour, for charts and progress indicators. */
  dotClass: string;
  /** Short description for tooltips and empty states. */
  description: string;
}

const NEUTRAL_BADGE = 'bg-neutral-soft text-muted-foreground border-border';

export const PROBLEM_STATUS_META: Record<ProblemStatus, StatusMeta> = {
  not_started: {
    label: 'Not Started',
    badgeClass: NEUTRAL_BADGE,
    dotClass: 'bg-subtle-foreground',
    description: 'No attempt logged yet',
  },
  attempted: {
    label: 'Attempted',
    badgeClass: 'bg-info-soft text-info border-info/25',
    dotClass: 'bg-info',
    description: 'Attempted but not solved cleanly',
  },
  solved: {
    label: 'Solved',
    badgeClass: 'bg-success-soft text-success border-success/25',
    dotClass: 'bg-success',
    description: 'Solved without help',
  },
  needs_revision: {
    label: 'Needs Revision',
    badgeClass: 'bg-warning-soft text-warning border-warning/25',
    dotClass: 'bg-warning',
    description: 'Flagged for revision',
  },
  mastered: {
    label: 'Mastered',
    badgeClass: 'bg-primary-soft text-primary border-primary/25',
    dotClass: 'bg-primary',
    description: 'Solved repeatedly with confidence',
  },
};

export const TOPIC_STATUS_META: Record<TopicStatus, StatusMeta> = {
  not_started: {
    label: 'Not Started',
    badgeClass: NEUTRAL_BADGE,
    dotClass: 'bg-subtle-foreground',
    description: 'Not begun',
  },
  learning: {
    label: 'Learning',
    badgeClass: 'bg-info-soft text-info border-info/25',
    dotClass: 'bg-info',
    description: 'In progress',
  },
  completed: {
    label: 'Completed',
    badgeClass: 'bg-success-soft text-success border-success/25',
    dotClass: 'bg-success',
    description: 'Completed once',
  },
  needs_revision: {
    label: 'Needs Revision',
    badgeClass: 'bg-warning-soft text-warning border-warning/25',
    dotClass: 'bg-warning',
    description: 'Flagged for revision',
  },
  mastered: {
    label: 'Mastered',
    badgeClass: 'bg-primary-soft text-primary border-primary/25',
    dotClass: 'bg-primary',
    description: 'Confident and retained',
  },
};

export const DIFFICULTY_META: Record<Difficulty, StatusMeta> = {
  easy: {
    label: 'Easy',
    badgeClass: 'bg-easy-soft text-easy border-easy/25',
    dotClass: 'bg-easy',
    description: 'Warm-up difficulty',
  },
  medium: {
    label: 'Medium',
    badgeClass: 'bg-medium-soft text-medium border-medium/25',
    dotClass: 'bg-medium',
    description: 'Standard interview difficulty',
  },
  hard: {
    label: 'Hard',
    badgeClass: 'bg-hard-soft text-hard border-hard/25',
    dotClass: 'bg-hard',
    description: 'Stretch difficulty',
  },
};

export const ATTEMPT_OUTCOME_META: Record<AttemptOutcome, { label: string; tone: 'success' | 'info' | 'warning' | 'danger' | 'neutral' }> = {
  solved: { label: 'Solved', tone: 'success' },
  solved_with_hint: { label: 'Solved with hint', tone: 'info' },
  partial: { label: 'Partial', tone: 'warning' },
  gave_up: { label: 'Gave up', tone: 'danger' },
  revision_success: { label: 'Revision passed', tone: 'success' },
  revision_failed: { label: 'Revision failed', tone: 'danger' },
};

export const REVISION_REASON_LABEL: Record<string, string> = {
  low_confidence: 'Low confidence',
  failed_attempt: 'Failed attempt',
  scheduled_revision: 'Scheduled review',
  manual: 'Scheduled manually',
  long_time_since_review: 'Long time since review',
};

/** Confidence is a 0–5 scale; present it as words plus a filled-bar count. */
export function confidenceLabel(confidence: number | null | undefined): string {
  if (confidence === null || confidence === undefined || confidence <= 0) return 'Not rated';
  if (confidence >= 5) return 'Very confident';
  if (confidence === 4) return 'Confident';
  if (confidence === 3) return 'Getting there';
  if (confidence === 2) return 'Shaky';
  return 'Struggling';
}

export function confidenceTone(confidence: number | null | undefined): 'neutral' | 'warning' | 'info' | 'success' {
  if (!confidence) return 'neutral';
  if (confidence <= 1) return 'warning';
  if (confidence <= 2) return 'warning';
  if (confidence <= 3) return 'info';
  return 'success';
}

export function isSolvedStatus(status: ProblemStatus): boolean {
  return status === 'solved' || status === 'mastered';
}

export function isTopicDone(status: TopicStatus): boolean {
  return status === 'completed' || status === 'mastered' || status === 'needs_revision';
}

/** Options for filter selects, derived from the metadata so labels stay consistent. */
export const PROBLEM_STATUS_OPTIONS = (
  Object.keys(PROBLEM_STATUS_META) as ProblemStatus[]
).map((value) => ({ value, label: PROBLEM_STATUS_META[value].label }));

export const TOPIC_STATUS_OPTIONS = (Object.keys(TOPIC_STATUS_META) as TopicStatus[]).map(
  (value) => ({ value, label: TOPIC_STATUS_META[value].label }),
);

export const DIFFICULTY_OPTIONS = (Object.keys(DIFFICULTY_META) as Difficulty[]).map((value) => ({
  value,
  label: DIFFICULTY_META[value].label,
}));
