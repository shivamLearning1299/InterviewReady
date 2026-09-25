import { Link } from 'react-router-dom';
import { ArrowRight, Check, ExternalLink, Play } from 'lucide-react';

import { DifficultyBadge, PatternList, StatusBadge } from '@/components/shared/domain-badges';
import { Button } from '@/components/ui/button';
import { ConfidenceMeter } from '@/components/ui/switch';
import { cn } from '@/lib/utils';
import { routes } from '@/lib/query-keys';
import type { TodayItem } from '@/types/today';

/**
 * A row in yesterday-or-today's plan.
 *
 * Completion is the plan item's own state (not the problem's status) so ticking a task off
 * is what feeds the streak — matching exactly how the backend records activity.
 */
export function TodayItemRow({
  item,
  index,
  onToggle,
  isToggling,
  onStart,
}: {
  item: TodayItem;
  index: number;
  onToggle: () => void;
  isToggling: boolean;
  onStart?: () => void;
}) {
  const href = item.problem_id ? routes.dsaProblem(item.problem_id) : null;

  return (
    <div
      className={cn(
        'group flex items-start gap-3 px-4 py-3.5 transition-colors hover:bg-surface-hover',
        item.is_completed && 'opacity-70',
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        disabled={isToggling}
        role="checkbox"
        aria-checked={item.is_completed}
        aria-label={`Mark "${item.title ?? 'item'}" as ${item.is_completed ? 'not done' : 'done'}`}
        className={cn(
          'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded border transition-colors',
          item.is_completed
            ? 'border-success bg-success text-white'
            : 'border-border-strong hover:border-primary hover:bg-primary-soft',
        )}
      >
        {item.is_completed ? <Check className="size-3" strokeWidth={3} /> : null}
      </button>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="tabular w-4 shrink-0 text-[13px] text-subtle-foreground">{index}</span>
          {href ? (
            <Link
              to={href}
              onClick={onStart}
              className={cn(
                'truncate text-sm font-medium hover:text-primary hover:underline',
                item.is_completed && 'line-through decoration-border-strong',
              )}
            >
              {item.title}
            </Link>
          ) : (
            <span className={cn('truncate text-sm font-medium', item.is_completed && 'line-through')}>
              {item.title}
            </span>
          )}
          {item.external_url ? (
            <a
              href={item.external_url}
              target="_blank"
              rel="noreferrer noopener"
              aria-label="Open on the original site"
              className="shrink-0 text-subtle-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-foreground"
            >
              <ExternalLink className="size-3.5" />
            </a>
          ) : null}
        </div>

        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {item.difficulty ? <DifficultyBadge difficulty={item.difficulty} size="sm" /> : null}
          {item.primary_topic ? (
            <span className="text-[12px] text-muted-foreground">{item.primary_topic}</span>
          ) : null}
          {item.patterns.length > 0 ? (
            <span className="hidden items-center gap-1 sm:flex">
              <span className="text-subtle-foreground">•</span>
              <PatternList patterns={item.patterns} max={2} />
            </span>
          ) : null}
        </div>

        {item.reason ? (
          <p className="mt-1 text-[11px] text-subtle-foreground">Why today: {item.reason}</p>
        ) : null}
      </div>

      <div className="flex shrink-0 flex-col items-end gap-1.5">
        {item.progress ? (
          <div className="flex items-center gap-2">
            <StatusBadge status={item.progress.status} size="sm" />
            {item.progress.confidence ? <ConfidenceMeter value={item.progress.confidence} /> : null}
          </div>
        ) : null}
        {item.estimated_minutes ? (
          <span className="tabular text-[11px] text-subtle-foreground">{item.estimated_minutes}m</span>
        ) : null}
        {href ? (
          <Button asChild variant="secondary" size="sm">
            <Link to={href} onClick={onStart}>
              {(item.progress?.attempts ?? 0) > 0 ? 'Continue' : 'Start'}
              <ArrowRight />
            </Link>
          </Button>
        ) : item.topic_id ? (
          <Button asChild variant="secondary" size="sm">
            <Link to={`/${item.item_type === 'lld' ? 'lld' : 'hld'}/${item.topic_id}`} onClick={onStart}>
              <Play />
              Open
            </Link>
          </Button>
        ) : null}
      </div>
    </div>
  );
}

/** Section wrapper: title, counter and progress bar with an empty state. */
export function TodaySectionCard({
  title,
  completed,
  total,
  description,
  action,
  children,
  className,
}: {
  title: string;
  completed: number;
  total: number;
  description?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  const percentage = total > 0 ? Math.round((completed / total) * 100) : 0;
  const done = total > 0 && completed >= total;

  return (
    <section
      className={cn(
        'flex flex-col overflow-hidden rounded-[var(--radius-card)] border border-border bg-surface',
        className,
      )}
    >
      <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            {title}
            {done ? (
              <span className="rounded border border-success/25 bg-success-soft px-1.5 text-[11px] font-medium text-success">
                Done
              </span>
            ) : null}
          </h2>
          {description ? (
            <p className="mt-0.5 text-[12px] text-muted-foreground">{description}</p>
          ) : null}
        </div>

        <div className="flex shrink-0 items-center gap-3">
          <span className="tabular text-[13px] font-medium">
            {completed}
            <span className="text-muted-foreground"> / {total}</span>
          </span>
          {action}
        </div>
      </header>

      <div className="h-0.5 w-full bg-muted" aria-hidden>
        <div
          className={cn('h-full transition-[width] duration-300', done ? 'bg-success' : 'bg-primary')}
          style={{ width: `${percentage}%` }}
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col divide-y divide-border">{children}</div>
    </section>
  );
}

/** Placeholder row while a section loads, matching the real row's height. */
export function TodaySectionSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="flex items-start gap-3 px-4 py-3.5">
          <div className="mt-0.5 size-5 shrink-0 animate-soft-pulse rounded border border-border bg-muted" />
          <div className="min-w-0 flex-1 space-y-2">
            <div className="h-3.5 w-2/5 animate-soft-pulse rounded bg-muted" />
            <div className="h-3 w-1/3 animate-soft-pulse rounded bg-muted" />
          </div>
          <div className="h-7 w-20 shrink-0 animate-soft-pulse rounded bg-muted" />
        </div>
      ))}
    </>
  );
}
