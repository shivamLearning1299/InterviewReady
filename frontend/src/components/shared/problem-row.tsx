import { Link } from 'react-router-dom';
import { ArrowRight, Check, ExternalLink, Star } from 'lucide-react';

import { DifficultyBadge, PatternList, StatusBadge, TopicBadge } from '@/components/shared/domain-badges';
import { Button } from '@/components/ui/button';
import { ConfidenceMeter } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import { describeDue, formatRelativeDay } from '@/lib/format';
import { PROBLEM_STATUS_META } from '@/lib/status';
import { routes } from '@/lib/query-keys';
import type { DSAProblemSummary } from '@/types/dsa';

/**
 * A single DSA problem, rendered either as a table row (desktop catalog) or a stacked card
 * (mobile catalog and Today's list).
 *
 * Shared between Today and the DSA catalog so the two screens cannot drift apart.
 */
export function ProblemRow({
  problem,
  index,
  variant = 'row',
  showCompleted = false,
  onToggleComplete,
  isToggling = false,
  className,
}: {
  problem: DSAProblemSummary;
  /** Position shown in the `#` column. Falls back to the catalog order index. */
  index?: number;
  variant?: 'row' | 'card';
  /** Today's list shows a completion affordance instead of the status badge. */
  showCompleted?: boolean;
  onToggleComplete?: () => void;
  isToggling?: boolean;
  className?: string;
}) {
  const progress = problem.progress;
  const statusMeta = PROBLEM_STATUS_META[progress.status];

  const action = (
    <Button asChild variant={showCompleted ? 'ghost' : 'secondary'} size="sm">
      <Link to={routes.dsaProblem(problem.id)}>
        {progress.status === 'not_started' ? 'Start' : 'Continue'}
        <ArrowRight />
      </Link>
    </Button>
  );

  if (variant === 'card') {
    return (
      <div className={cn('flex flex-col gap-3 px-4 py-3.5', className)}>
        <div className="flex items-start gap-3">
          {showCompleted ? (
            <button
              type="button"
              onClick={onToggleComplete}
              disabled={isToggling}
              aria-label={progress.status === 'solved' ? 'Mark as not done' : 'Mark as done'}
              className={cn(
                'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded border transition-colors',
                progress.status === 'solved' || progress.status === 'mastered'
                  ? 'border-success bg-success text-white'
                  : 'border-border-strong hover:border-primary',
              )}
            >
              {(progress.status === 'solved' || progress.status === 'mastered') && (
                <Check className="size-3" strokeWidth={3} />
              )}
            </button>
          ) : (
            <span className="tabular mt-0.5 w-6 shrink-0 text-[13px] text-subtle-foreground">
              {index ?? problem.order_index}
            </span>
          )}
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <h3 className="truncate text-sm font-medium">{problem.title}</h3>
              {progress.is_favorite ? (
                <Star className="mt-0.5 size-3.5 shrink-0 fill-warning text-warning" />
              ) : null}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
              <DifficultyBadge difficulty={problem.difficulty} size="sm" />
              <TopicBadge topic={problem.primary_topic} size="sm" />
            </div>
            {problem.patterns.length > 0 ? (
              <div className="mt-1.5">
                <PatternList patterns={problem.patterns} max={2} />
              </div>
            ) : null}
          </div>
        </div>

        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            {showCompleted ? (
              <span className="text-[13px] text-muted-foreground">{statusMeta.label}</span>
            ) : (
              <StatusBadge status={progress.status} size="sm" />
            )}
            {progress.confidence ? <ConfidenceMeter value={progress.confidence} /> : null}
          </div>
          {action}
        </div>
      </div>
    );
  }

  return (
    <tr className={cn('group transition-colors hover:bg-surface-hover', className)}>
      <td className="tabular w-10 px-3 py-2.5 text-[13px] text-subtle-foreground">
        {index ?? problem.order_index}
      </td>

      <td className="min-w-0 px-3 py-2.5">
        <div className="flex items-center gap-2">
          {showCompleted ? (
            <button
              type="button"
              onClick={onToggleComplete}
              disabled={isToggling}
              aria-label="Toggle completed"
              className={cn(
                'flex size-4 shrink-0 items-center justify-center rounded border transition-colors',
                progress.status === 'solved' || progress.status === 'mastered'
                  ? 'border-success bg-success text-white'
                  : 'border-border-strong hover:border-primary',
              )}
            >
              {(progress.status === 'solved' || progress.status === 'mastered') && (
                <Check className="size-2.5" strokeWidth={3} />
              )}
            </button>
          ) : null}
          <Link
            to={routes.dsaProblem(problem.id)}
            className="truncate text-sm font-medium hover:text-primary hover:underline"
          >
            {problem.title}
          </Link>
          {progress.is_favorite ? (
            <Star aria-label="Favourite" className="size-3.5 shrink-0 fill-warning text-warning" />
          ) : null}
          {problem.external_url ? (
            <a
              href={problem.external_url}
              target="_blank"
              rel="noreferrer noopener"
              aria-label={`Open ${problem.title} on ${problem.source}`}
              className="shrink-0 text-subtle-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-foreground focus-visible:opacity-100"
            >
              <ExternalLink className="size-3.5" />
            </a>
          ) : null}
        </div>
      </td>

      <td className="px-3 py-2.5">
        <DifficultyBadge difficulty={problem.difficulty} size="sm" />
      </td>

      <td className="px-3 py-2.5">
        <TopicBadge topic={problem.primary_topic} size="sm" />
      </td>

      <td className="max-w-56 px-3 py-2.5">
        <PatternList patterns={problem.patterns} max={2} />
      </td>

      <td className="px-3 py-2.5">
        <StatusBadge status={progress.status} size="sm" />
      </td>

      <td className="px-3 py-2.5">
        {progress.confidence ? (
          <ConfidenceMeter value={progress.confidence} />
        ) : (
          <span className="text-[13px] text-subtle-foreground">—</span>
        )}
      </td>

      <td className="tabular px-3 py-2.5 text-[13px] text-muted-foreground">
        {progress.solved_at ? formatRelativeDay(progress.solved_at) : '—'}
      </td>

      <td className="px-3 py-2.5 text-[13px]">
        {progress.next_revision_at ? (
          <span
            className={cn(
              'tabular',
              new Date(progress.next_revision_at) <= new Date()
                ? 'font-medium text-warning'
                : 'text-muted-foreground',
            )}
            title={describeDue(progress.next_revision_at)}
          >
            {formatRelativeDay(progress.next_revision_at)}
          </span>
        ) : (
          <span className="text-subtle-foreground">—</span>
        )}
      </td>

      <td className="px-3 py-2.5 text-right">{action}</td>
    </tr>
  );
}

/** Column headers for the desktop catalog table. Kept next to the row for alignment. */
export function ProblemTableHeader({
  showCompleted = false,
  onToggleAll,
  allCompleted = false,
}: {
  showCompleted?: boolean;
  onToggleAll?: () => void;
  allCompleted?: boolean;
}) {
  return (
    <thead className="sticky top-0 z-10 border-b border-border bg-surface">
      <tr className="text-left text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">
        <th scope="col" className="w-10 px-3 py-2">
          {showCompleted && onToggleAll ? (
            <button
              type="button"
              onClick={onToggleAll}
              aria-label="Toggle all"
              className={cn(
                'flex size-4 items-center justify-center rounded border transition-colors',
                allCompleted ? 'border-primary bg-primary text-white' : 'border-border-strong',
              )}
            >
              {allCompleted ? <Check className="size-2.5" strokeWidth={3} /> : null}
            </button>
          ) : (
            '#'
          )}
        </th>
        <th scope="col" className="px-3 py-2">
          Problem
        </th>
        <th scope="col" className="px-3 py-2">
          Difficulty
        </th>
        <th scope="col" className="px-3 py-2">
          Topic
        </th>
        <th scope="col" className="px-3 py-2">
          Pattern
        </th>
        <th scope="col" className="px-3 py-2">
          Status
        </th>
        <th scope="col" className="px-3 py-2">
          Confidence
        </th>
        <th scope="col" className="px-3 py-2">
          Last attempted
        </th>
        <th scope="col" className="px-3 py-2">
          Revision
        </th>
        <th scope="col" className="px-3 py-2">
          <span className="sr-only">Actions</span>
        </th>
      </tr>
    </thead>
  );
}
