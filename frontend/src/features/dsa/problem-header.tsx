import { useEffect, useMemo, useState } from 'react';
import { Check, Clock, Star } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/input';
import { ConfidencePicker } from '@/components/ui/switch';
import { Tooltip } from '@/components/ui/tooltip';
import { DifficultyBadge, PatternList } from '@/components/shared/domain-badges';
import { useStudyTimer } from '@/hooks/use-study-timer';
import { useUpdateProgress } from '@/hooks/use-api';
import { formatClock, formatMinutes, describeDue, formatRelativeDay } from '@/lib/format';
import { PROBLEM_STATUS_OPTIONS } from '@/lib/status';
import { cn } from '@/lib/utils';
import type { DSAProblemDetail } from '@/types/dsa';
import type { ProblemStatus } from '@/types/common';

/**
 * Problem header and progress controls.
 *
 * Status and confidence write through immediately — a single click is enough to record
 * progress, which is the whole point of the study loop. The confidence picker is optimistic
 * so the star feels instant.
 */
export function ProblemHeader({ problem }: { problem: DSAProblemDetail }) {
  const updateProgress = useUpdateProgress();
  const timer = useStudyTimer();

  const progress = problem.progress;
  const status: ProblemStatus = progress?.status ?? 'not_started';
  const solved = status === 'solved' || status === 'mastered';

  const [confidence, setConfidence] = useState<number | null>(progress?.confidence ?? null);

  // Re-sync when the server value changes (e.g. after a revision completes elsewhere).
  useEffect(() => {
    setConfidence(progress?.confidence ?? null);
  }, [progress?.confidence]);

  const meta = useMemo(
    () => [
      problem.source ? problem.source.replace(/^\w/, (character) => character.toUpperCase()) : null,
      problem.estimated_minutes ? `~${problem.estimated_minutes}m` : null,
      progress?.attempts ? `${progress.attempts} attempt${progress.attempts === 1 ? '' : 's'}` : null,
      progress?.total_time_spent_minutes
        ? `${formatMinutes(progress.total_time_spent_minutes)} logged`
        : null,
    ].filter(Boolean) as string[],
    [problem.source, problem.estimated_minutes, progress],
  );

  return (
    <header className="border-b border-border px-4 py-4 sm:px-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-semibold tracking-tight">{problem.title}</h1>
            <DifficultyBadge difficulty={problem.difficulty} />
            <button
              type="button"
              aria-pressed={progress?.is_favorite ?? false}
              aria-label={progress?.is_favorite ? 'Remove from favourites' : 'Add to favourites'}
              onClick={() =>
                updateProgress.mutate({
                  problemId: problem.id,
                  payload: { is_favorite: !progress?.is_favorite },
                })
              }
              className="rounded p-1 text-subtle-foreground transition-colors hover:bg-accent hover:text-warning"
            >
              <Star
                className={cn('size-4', progress?.is_favorite && 'fill-warning text-warning')}
              />
            </button>
          </div>

          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-[13px] text-muted-foreground">{problem.primary_topic}</span>
            {problem.patterns.length > 0 ? (
              <>
                <span className="text-subtle-foreground">•</span>
                <PatternList patterns={problem.patterns} max={4} />
              </>
            ) : null}
          </div>

          {meta.length > 0 ? (
            <p className="mt-1.5 text-[12px] text-subtle-foreground">{meta.join(' · ')}</p>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {problem.external_url ? (
            <Button asChild variant="outline" size="sm">
              <a href={problem.external_url} target="_blank" rel="noreferrer noopener">
                Open on {problem.source === 'leetcode' ? 'LeetCode' : problem.source}
              </a>
            </Button>
          ) : null}
        </div>
      </div>

      {/* Progress controls */}
      <div className="mt-4 flex flex-wrap items-end gap-x-5 gap-y-3">
        <div className="space-y-1.5">
          <label htmlFor="problem-status" className="text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">
            Status
          </label>
          <Select
            id="problem-status"
            value={status}
            aria-label="Problem status"
            onChange={(event) =>
              updateProgress.mutate({
                problemId: problem.id,
                payload: { status: event.target.value as ProblemStatus },
              })
            }
            className="w-40"
          >
            {PROBLEM_STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </div>

        <div className="space-y-1.5">
          <span className="text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">
            Confidence
          </span>
          <div className="flex items-center gap-2">
            <ConfidencePicker
              value={confidence}
              onChange={(value) => {
                setConfidence(value);
                updateProgress.mutate({ problemId: problem.id, payload: { confidence: value } });
              }}
            />
            <span className="text-[12px] text-muted-foreground">
              {confidence ? `${confidence} / 5` : 'Not rated'}
            </span>
          </div>
        </div>

        {/* Revision state */}
        <div className="space-y-1.5">
          <span className="text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">
            Next revision
          </span>
          <div className="flex items-center gap-2">
            <span className="tabular text-[13px]">
              {progress?.next_revision_at ? describeDue(progress.next_revision_at) : 'Not scheduled'}
            </span>
            {solved && !progress?.next_revision_at ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  updateProgress.mutate({ problemId: problem.id, payload: { schedule_revision: true } })
                }
              >
                Schedule
              </Button>
            ) : null}
          </div>
        </div>

        {/* Session controls */}
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant={solved ? 'secondary' : 'primary'}
            size="sm"
            onClick={() =>
              updateProgress.mutate({
                problemId: problem.id,
                payload: { status: solved ? 'attempted' : 'solved' },
              })
            }
            loading={updateProgress.isPending}
          >
            <Check />
            {solved ? 'Mark unsolved' : 'Mark solved'}
          </Button>

          {timer.isRunning ? (
            <>
              <Tooltip content="Study time is measured by the server">
                <span className="tabular flex items-center gap-1.5 rounded-[var(--radius-control)] border border-primary/25 bg-primary-soft px-2.5 py-1.5 text-[13px] font-medium text-primary">
                  <Clock className="size-3.5" />
                  {formatClock(timer.elapsedSeconds)}
                </span>
              </Tooltip>
              <Button variant="ghost" size="sm" loading={timer.isStopping} onClick={() => void timer.stop()}>
                Stop
              </Button>
            </>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              loading={timer.isStarting}
              onClick={() => void timer.start('dsa', problem.id)}
            >
              <Clock />
              Time me
            </Button>
          )}
        </div>
      </div>

      {progress?.solved_at ? (
        <p className="mt-2 text-[12px] text-subtle-foreground">
          Solved {formatRelativeDay(progress.solved_at)} ·{' '}
          {problem.revisions.length} revision{problem.revisions.length === 1 ? '' : 's'} recorded
        </p>
      ) : null}
    </header>
  );
}
