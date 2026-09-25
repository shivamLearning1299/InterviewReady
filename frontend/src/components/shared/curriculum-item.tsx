import { Link } from 'react-router-dom';
import { ArrowRight, Check } from 'lucide-react';

import { StatusBadge } from '@/components/shared/domain-badges';
import { ProgressBar } from '@/components/ui/progress';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { percent } from '@/lib/helpers';
import type { TopicProgressSummary, TopicStatus } from '@/types/common';

/**
 * One curriculum topic row, shared by the LLD and HLD catalogues.
 *
 * The progress bar reflects *done* topics (completed + mastered + flagged for revision),
 * which is what the backend's `TopicStats.completed` counts.
 */
export function CurriculumItem({
  title,
  description,
  status,
  confidence,
  keyConcepts,
  estimatedMinutes,
  href,
  variant = 'row',
  className,
  actions,
  isCompleted = false,
  onToggleComplete,
  isToggling = false,
}: {
  title: string;
  description?: string | null;
  status: TopicStatus | TopicProgressSummary;
  confidence?: number | null;
  keyConcepts?: string[];
  estimatedMinutes?: number;
  href: string;
  variant?: 'row' | 'card';
  className?: string;
  actions?: React.ReactNode;
  /** Today's list allows ticking a lesson off directly. */
  isCompleted?: boolean;
  onToggleComplete?: () => void;
  isToggling?: boolean;
}) {
  const topicStatus: TopicStatus = typeof status === 'string' ? status : status.status;
  const resolvedConfidence =
    confidence ?? (typeof status === 'string' ? null : status.confidence);

  const completion = topicStatus === 'mastered' ? 100 : topicStatus === 'completed' ? 80 : topicStatus === 'needs_revision' ? 60 : topicStatus === 'learning' ? 35 : 0;

  if (variant === 'card') {
    return (
      <div className={cn('flex flex-col gap-3 px-4 py-3.5', className)}>
        <div className="flex items-start gap-3">
          {onToggleComplete ? (
            <button
              type="button"
              onClick={onToggleComplete}
              disabled={isToggling}
              aria-label={isCompleted ? 'Mark as not done' : 'Mark as done'}
              className={cn(
                'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded border transition-colors',
                isCompleted ? 'border-success bg-success text-white' : 'border-border-strong hover:border-primary',
              )}
            >
              {isCompleted ? <Check className="size-3" strokeWidth={3} /> : null}
            </button>
          ) : null}
          <div className="min-w-0 flex-1">
            <Link to={href} className="text-sm font-medium hover:text-primary hover:underline">
              {title}
            </Link>
            {description ? (
              <p className="mt-0.5 line-clamp-2-safe text-[13px] text-muted-foreground">{description}</p>
            ) : null}
          </div>
          <StatusBadge status={topicStatus} domain="topic" size="sm" />
        </div>
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0 flex-1">
            <ProgressBar value={completion} tone={completion >= 80 ? 'success' : 'primary'} size="xs" />
          </div>
          <Link
            to={href}
            className="inline-flex shrink-0 items-center gap-1 text-[13px] font-medium text-primary hover:underline"
          >
            Open
            <ArrowRight className="size-3.5" />
          </Link>
        </div>
      </div>
    );
  }

  return (
    <Link
      to={href}
      className={cn(
        'group flex items-center gap-4 px-4 py-3 transition-colors hover:bg-surface-hover',
        className,
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium group-hover:text-primary">{title}</span>
        </div>
        {description ? (
          <p className="mt-0.5 line-clamp-2-safe text-[13px] text-muted-foreground">{description}</p>
        ) : null}
        {keyConcepts && keyConcepts.length > 0 ? (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {keyConcepts.slice(0, 3).map((concept) => (
              <Badge key={concept} tone="outline" size="sm" className="font-normal">
                {concept}
              </Badge>
            ))}
          </div>
        ) : null}
      </div>

      <div className="hidden w-32 shrink-0 flex-col gap-1.5 md:flex">
        <ProgressBar value={completion} tone={completion >= 80 ? 'success' : 'primary'} size="xs" />
        <span className="tabular text-[11px] text-subtle-foreground">{completion}% mastered</span>
      </div>

      <div className="hidden shrink-0 items-center gap-3 lg:flex">
        {resolvedConfidence ? (
          <span className="tabular text-[12px] text-muted-foreground">
            conf {resolvedConfidence}/5
          </span>
        ) : null}
        {estimatedMinutes ? (
          <span className="tabular text-[12px] text-subtle-foreground">{estimatedMinutes}m</span>
        ) : null}
      </div>

      <StatusBadge status={topicStatus} domain="topic" size="sm" className="shrink-0" />
      {actions}
    </Link>
  );
}

/** Category group header with an inline completion figure. */
export function CurriculumGroupHeader({
  title,
  completed,
  total,
  className,
}: {
  title: string;
  completed: number;
  total: number;
  className?: string;
}) {
  const percentage = percent(completed, total);
  return (
    <div className={cn('flex items-center justify-between gap-4', className)}>
      <div className="flex items-baseline gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="tabular text-[13px] text-muted-foreground">
          {completed} / {total}
        </span>
      </div>
      <div className="flex w-32 items-center gap-2">
        <ProgressBar value={percentage} tone={percentage >= 75 ? 'success' : 'primary'} size="xs" />
        <span className="tabular w-8 shrink-0 text-right text-[11px] text-subtle-foreground">
          {percentage}%
        </span>
      </div>
    </div>
  );
}
