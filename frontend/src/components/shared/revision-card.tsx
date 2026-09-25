import { Link } from 'react-router-dom';
import { Clock, RotateCcw } from 'lucide-react';

import { DifficultyBadge, PatternList, StatusBadge } from '@/components/shared/domain-badges';
import { ProgressBar } from '@/components/ui/progress';
import { cn } from '@/lib/utils';
import { describeDue, formatRelativeDay } from '@/lib/format';
import { REVISION_REASON_LABEL, confidenceLabel, confidenceTone } from '@/lib/status';
import { routes } from '@/lib/query-keys';
import type { Revision } from '@/types/dsa';

const TONE_CLASS = {
  neutral: 'text-muted-foreground',
  warning: 'text-warning',
  info: 'text-info',
  success: 'text-success',
} as const;

/**
 * One item in the revision queue.
 *
 * Confidence is rendered as data, never as prose the user has to decode, and the reason is
 * always shown — a queue that says *why* something is due is far easier to trust.
 */
export function RevisionCard({
  revision,
  /** Hides the previous confidence while a session is running (active recall). */
  concealed = false,
  compact = false,
  className,
  actions,
}: {
  revision: Revision;
  concealed?: boolean;
  compact?: boolean;
  className?: string;
  actions?: React.ReactNode;
}) {
  const overdue = new Date(revision.due_at) < new Date();
  const tone = confidenceTone(revision.confidence_before);

  return (
    <div className={cn('flex flex-col gap-2.5 px-4 py-3.5', className)}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Link
              to={revision.problem_id ? routes.dsaProblem(revision.problem_id) : routes.dsa}
              className="truncate text-sm font-medium hover:text-primary hover:underline"
            >
              {revision.problem_title ?? 'Untitled problem'}
            </Link>
            {overdue && !revision.completed ? (
              <span
                className="inline-flex items-center gap-1 rounded border border-danger/25 bg-danger-soft px-1.5 text-[11px] font-medium text-danger"
                title="Past its due date"
              >
                <Clock className="size-3" />
                Overdue
              </span>
            ) : null}
          </div>

          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {revision.problem_difficulty ? (
              <DifficultyBadge difficulty={revision.problem_difficulty} size="sm" />
            ) : null}
            {revision.problem_topic ? (
              <span className="text-[12px] text-muted-foreground">{revision.problem_topic}</span>
            ) : null}
          </div>
        </div>

        <div className="shrink-0 text-right">
          <p
            className={cn(
              'tabular text-[13px] font-medium',
              overdue && !revision.completed ? 'text-danger' : 'text-muted-foreground',
            )}
          >
            {revision.completed
              ? `Reviewed ${formatRelativeDay(revision.completed_at)}`
              : describeDue(revision.due_at)}
          </p>
          {!revision.completed ? (
            <p className="mt-0.5 text-[11px] text-subtle-foreground">
              priority {revision.priority}
            </p>
          ) : null}
        </div>
      </div>

      {!compact ? (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px] sm:grid-cols-3">
          <div>
            <dt className="text-subtle-foreground">Last solved</dt>
            <dd className="tabular text-foreground">
              {revision.created_at ? formatRelativeDay(revision.created_at) : '—'}
            </dd>
          </div>
          <div>
            <dt className="text-subtle-foreground">Confidence</dt>
            <dd className={cn('font-medium', concealed ? 'text-subtle-foreground' : TONE_CLASS[tone])}>
              {concealed ? 'Hidden' : confidenceLabel(revision.confidence_before)}
            </dd>
          </div>
          <div>
            <dt className="text-subtle-foreground">Interval</dt>
            <dd className="tabular text-foreground">
              {revision.interval_days ? `${revision.interval_days}d` : '—'}
            </dd>
          </div>
        </dl>
      ) : null}

      <div className="flex flex-wrap items-center gap-2 text-[12px] text-muted-foreground">
        <RotateCcw className="size-3.5 shrink-0" />
        <span>
          Scheduled because:{' '}
          <span className="text-foreground">
            {REVISION_REASON_LABEL[revision.reason] ?? revision.reason.replace(/_/g, ' ')}
          </span>
        </span>
      </div>

      {revision.notes ? (
        <p className="rounded-md border border-border bg-muted px-2.5 py-1.5 text-[12px] text-muted-foreground">
          {revision.notes}
        </p>
      ) : null}

      {actions ? <div className="flex flex-wrap items-center gap-2 pt-0.5">{actions}</div> : null}
    </div>
  );
}

/** Compact table row for the revision history inside the problem workspace. */
export function RevisionHistoryRow({ revision }: { revision: Revision }) {
  return (
    <tr className="border-b border-border last:border-0">
      <td className="px-3 py-2 text-[13px] text-muted-foreground">
        {formatRelativeDay(revision.due_at)}
      </td>
      <td className="px-3 py-2">
        <StatusBadge
          status={revision.completed ? 'mastered' : 'needs_revision'}
          size="sm"
          domain="topic"
        />
      </td>
      <td className="px-3 py-2">
        <PatternList patterns={revision.result ? [revision.result] : []} max={1} />
      </td>
      <td className="px-3 py-2 text-[13px] text-muted-foreground">
        {confidenceLabel(revision.confidence_before)}
      </td>
      <td className="tabular px-3 py-2 text-[13px] text-muted-foreground">
        {revision.interval_days ? `${revision.interval_days}d` : '—'}
      </td>
    </tr>
  );
}

/** Weekly revision throughput bar, used on the revision dashboard. */
export function RevisionProgress({
  completed,
  total,
  className,
}: {
  completed: number;
  total: number;
  className?: string;
}) {
  return (
    <div className={cn('space-y-1.5', className)}>
      <div className="flex items-baseline justify-between text-[13px]">
        <span className="text-muted-foreground">Session progress</span>
        <span className="tabular font-medium">
          {completed} <span className="text-muted-foreground">/ {total}</span>
        </span>
      </div>
      <ProgressBar value={completed} max={Math.max(total, 1)} tone="primary" label="Revision progress" />
    </div>
  );
}
