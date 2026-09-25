import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, ExternalLink, Timer } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ProgressBar } from '@/components/ui/progress';
import { ConfidencePicker, SegmentedControl } from '@/components/ui/switch';
import { DifficultyBadge, StatusBadge } from '@/components/shared/domain-badges';
import { formatClock, formatRelativeDay } from '@/lib/format';
import { TOPIC_STATUS_OPTIONS } from '@/lib/status';
import { cn } from '@/lib/utils';
import type { TopicProgressSummary, TopicStatus } from '@/types/common';

/** Coarse completion per status — the API exposes status, not a mastery percentage. */
const STATUS_PROGRESS: Record<TopicStatus, number> = {
  not_started: 0,
  learning: 35,
  needs_revision: 60,
  completed: 80,
  mastered: 100,
};

/**
 * Shared shell for the LLD and HLD workspaces.
 *
 * Both screens share their top matter — breadcrumb, title, status and confidence controls,
 * study timer — so it is defined once here. Everything below is feature-specific.
 */
export function DesignWorkspaceShell({
  backHref,
  backLabel,
  title,
  subtitle,
  externalUrl,
  difficulty,
  progress,
  onStatusChange,
  onConfidenceChange,
  isSaving,
  timer,
  children,
  className,
}: {
  backHref: string;
  backLabel: string;
  title: string;
  subtitle?: ReactNode;
  externalUrl?: string | null;
  difficulty?: string | null;
  progress: TopicProgressSummary | null;
  onStatusChange: (status: TopicStatus) => void;
  onConfidenceChange: (confidence: number) => void;
  isSaving: boolean;
  timer: {
    elapsedSeconds: number;
    isRunning: boolean;
    start: () => void;
    stop: () => void;
  };
  children: ReactNode;
  className?: string;
}) {
  const status: TopicStatus = progress?.status ?? 'not_started';
  const confidence = progress?.confidence ?? 3;
  const completion = STATUS_PROGRESS[status];

  return (
    <div className={cn('flex h-full min-h-0 flex-col', className)}>
      {/* Breadcrumb */}
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-1.5 sm:px-5">
        <Button asChild variant="subtle" size="sm">
          <Link to={backHref}>
            <ArrowLeft />
            {backLabel}
          </Link>
        </Button>
        <span className="text-[12px] text-subtle-foreground">/</span>
        <span className="truncate text-[12px] text-muted-foreground">{title}</span>
        {externalUrl ? (
          <a
            href={externalUrl}
            target="_blank"
            rel="noreferrer noopener"
            className="ml-auto flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground"
          >
            <ExternalLink className="size-3" />
            Reference
          </a>
        ) : null}
      </div>

      {/* Title + timer */}
      <header className="shrink-0 border-b border-border px-4 py-3.5 sm:px-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
              <StatusBadge status={status} domain="topic" size="sm" />
              {difficulty ? <DifficultyBadge difficulty={difficulty} size="sm" /> : null}
            </div>
            {subtitle ? (
              <div className="mt-1 text-[13px] text-muted-foreground">{subtitle}</div>
            ) : null}
          </div>

          {/* Study timer — server-timed, so it survives a reload. */}
          <div className="flex items-center gap-2">
            <span className="tabular flex items-center gap-1.5 rounded-[var(--radius-control)] border border-border bg-muted px-2.5 py-1 text-[13px]">
              <Timer className="size-3.5" />
              {formatClock(timer.elapsedSeconds)}
            </span>
            <Button
              variant={timer.isRunning ? 'subtle' : 'secondary'}
              size="sm"
              onClick={() => (timer.isRunning ? timer.stop() : timer.start())}
            >
              {timer.isRunning ? 'Stop' : 'Start'}
            </Button>
          </div>
        </div>

        {/* Progress controls */}
        <div className="mt-3.5 flex flex-wrap items-end gap-x-6 gap-y-3">
          <div className="space-y-1.5">
            <p className="text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">
              Status
            </p>
            <SegmentedControl
              size="sm"
              label="Topic status"
              value={status}
              onChange={onStatusChange}
              options={TOPIC_STATUS_OPTIONS.map((option) => ({
                value: option.value,
                label: option.label,
              }))}
            />
          </div>

          <div className="space-y-1.5">
            <p className="text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">
              Confidence
            </p>
            <ConfidencePicker value={confidence} onChange={onConfidenceChange} disabled={isSaving} />
          </div>

          <div className="min-w-40 flex-1 space-y-1.5">
            <div className="flex items-baseline justify-between">
              <p className="text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">
                Completion
              </p>
              <span className="tabular text-[11px] text-subtle-foreground">{completion}%</span>
            </div>
            <ProgressBar
              value={completion}
              tone={completion >= 80 ? 'success' : completion >= 50 ? 'primary' : 'neutral'}
              label="Topic completion"
            />
          </div>
        </div>
      </header>

      {children}

      {progress?.last_reviewed_at || progress?.total_time_spent_minutes ? (
        <footer className="shrink-0 border-t border-border bg-muted/40 px-4 py-2 text-[12px] text-muted-foreground sm:px-5">
          {progress.total_time_spent_minutes
            ? `${progress.total_time_spent_minutes} min studied`
            : 'Not studied yet'}
          {progress.last_reviewed_at
            ? ` · last reviewed ${formatRelativeDay(progress.last_reviewed_at)}`
            : ''}
        </footer>
      ) : null}
    </div>
  );
}

/** Labelled reference list used by both design workspaces. */
export function ReferenceCard({
  title,
  items,
  className,
}: {
  title: string;
  items: string[];
  className?: string;
}) {
  if (items.length === 0) return null;
  return (
    <Card padding="md" className={cn('space-y-2', className)}>
      <h3 className="text-[13px] font-semibold">{title}</h3>
      <ul className="space-y-1.5">
        {items.map((item) => (
          <li key={item} className="flex gap-2 text-[13px] text-muted-foreground">
            <span aria-hidden className="mt-1.5 size-1 shrink-0 rounded-full bg-border-strong" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
