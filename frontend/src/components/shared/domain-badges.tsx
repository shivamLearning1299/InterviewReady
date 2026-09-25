import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import {
  DIFFICULTY_META,
  PROBLEM_STATUS_META,
  TOPIC_STATUS_META,
} from '@/lib/status';
import type { Difficulty, ProblemStatus, TopicStatus } from '@/types/common';

/**
 * Domain badges.
 *
 * Each one resolves its label and colour from `lib/status.ts` so a badge in a table, a
 * filter chip and a chart legend always agree.
 */

export function DifficultyBadge({
  difficulty,
  size = 'md',
  className,
}: {
  difficulty: Difficulty | string | null | undefined;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}) {
  const meta = difficulty ? DIFFICULTY_META[difficulty as Difficulty] : undefined;
  if (!meta) {
    return (
      <Badge tone="neutral" size={size === 'lg' ? 'lg' : size} className={className}>
        Unknown
      </Badge>
    );
  }
  return (
    <Badge tone={difficulty as Difficulty} size={size === 'lg' ? 'lg' : size} className={className}>
      {meta.label}
    </Badge>
  );
}

export function StatusBadge({
  status,
  size = 'md',
  domain = 'problem',
  className,
  showDot = false,
}: {
  status: ProblemStatus | TopicStatus | string | null | undefined;
  size?: 'sm' | 'md' | 'lg';
  /** Which enum the value belongs to. */
  domain?: 'problem' | 'topic';
  className?: string;
  showDot?: boolean;
}) {
  const meta =
    domain === 'problem'
      ? PROBLEM_STATUS_META[status as ProblemStatus]
      : TOPIC_STATUS_META[status as TopicStatus];

  if (!meta) {
    return (
      <Badge tone="neutral" size={size} className={className} dot={showDot}>
        Unknown
      </Badge>
    );
  }

  const tone =
    status === 'mastered'
      ? 'primary'
      : status === 'solved' || status === 'completed'
        ? 'success'
        : status === 'needs_revision'
          ? 'warning'
          : status === 'attempted' || status === 'learning'
            ? 'info'
            : 'neutral';

  return (
    <Badge tone={tone} size={size} className={className} dot={showDot} title={meta.description}>
      {meta.label}
    </Badge>
  );
}

/** Topic chip. Renders as a subtle outline so it does not compete with status badges. */
export function TopicBadge({
  topic,
  size = 'md',
  className,
}: {
  topic: string;
  size?: 'sm' | 'md';
  className?: string;
}) {
  return (
    <Badge tone="outline" size={size} className={cn('font-normal', className)}>
      {topic}
    </Badge>
  );
}

/** Pattern chip, e.g. "Sliding Window • Hash Map". */
export function PatternList({
  patterns,
  max = 2,
  className,
}: {
  patterns: string[];
  max?: number;
  className?: string;
}) {
  if (patterns.length === 0) {
    return <span className="text-[13px] text-subtle-foreground">—</span>;
  }

  const shown = patterns.slice(0, max);
  const overflow = patterns.length - shown.length;

  return (
    <span className={cn('inline-flex flex-wrap items-center gap-1', className)}>
      {shown.map((pattern) => (
        <Badge key={pattern} tone="outline" size="sm" className="font-normal">
          {pattern}
        </Badge>
      ))}
      {overflow > 0 ? (
        <span className="text-[11px] text-subtle-foreground" title={patterns.join(', ')}>
          +{overflow}
        </span>
      ) : null}
    </span>
  );
}

/** Attempt outcome chip, used in the attempts table. */
export function OutcomeBadge({
  outcome,
  label,
  tone,
  className,
}: {
  outcome: string;
  label: string;
  tone: 'success' | 'info' | 'warning' | 'danger' | 'neutral';
  className?: string;
}) {
  return (
    <Badge tone={tone} size="sm" className={className} title={outcome}>
      {label}
    </Badge>
  );
}
