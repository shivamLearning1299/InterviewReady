import { useMemo, useState } from 'react';
import { CheckCircle2, XCircle } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Textarea, Field, Select } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { OutcomeBadge } from '@/components/shared/domain-badges';
import { RevisionHistoryRow } from '@/components/shared/revision-card';
import { useCreateAttempt, useUpdateProgress } from '@/hooks/use-api';
import { ATTEMPT_OUTCOME_META } from '@/lib/status';
import { formatMinutes, formatRelativeTime, formatRelativeDay } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { Attempt, Revision } from '@/types/dsa';
import type { AttemptOutcome, ProblemStatus } from '@/types/common';

const OUTCOME_TO_STATUS: Partial<Record<AttemptOutcome, ProblemStatus>> = {
  solved: 'solved',
  solved_with_hint: 'attempted',
  partial: 'attempted',
  gave_up: 'needs_revision',
  revision_success: 'mastered',
  revision_failed: 'needs_revision',
};

/**
 * Attempt history and the "log an attempt" form.
 *
 * Logging an attempt is the highest-signal action a user can take: the outcome determines
 * the next status and, through it, the revision schedule. The form therefore shows the
 * consequence of each outcome rather than making the user infer it.
 */
export function AttemptsPanel({
  problemId,
  attempts,
  className,
}: {
  problemId: string;
  attempts: Attempt[];
  className?: string;
}) {
  const createAttempt = useCreateAttempt();
  const updateProgress = useUpdateProgress();

  const [outcome, setOutcome] = useState<AttemptOutcome>('partial');
  const [duration, setDuration] = useState('25');
  const [notes, setNotes] = useState('');
  const [showForm, setShowForm] = useState(false);

  const sorted = useMemo(
    () => [...attempts].sort((a, b) => (a.created_at < b.created_at ? 1 : -1)),
    [attempts],
  );

  const submit = async () => {
    await createAttempt.mutateAsync({
      problemId,
      payload: {
        outcome,
        duration_minutes: Number(duration) || undefined,
        notes: notes.trim() || undefined,
        update_progress: true,
      },
    });
    setNotes('');
    setShowForm(false);
  };

  const consequence = OUTCOME_TO_STATUS[outcome];

  return (
    <div className={cn('space-y-4', className)}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-[13px] font-semibold">Attempts</h3>
          <p className="mt-0.5 text-[12px] text-muted-foreground">
            {sorted.length === 0
              ? 'No attempts logged yet'
              : `${sorted.length} attempt${sorted.length === 1 ? '' : 's'} recorded`}
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => setShowForm((current) => !current)}>
          {showForm ? 'Cancel' : 'Log an attempt'}
        </Button>
      </div>

      {showForm ? (
        <div className="space-y-3 rounded-[var(--radius-card)] border border-border bg-muted p-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Outcome" hint={consequence ? `Sets status to "${consequence.replace(/_/g, ' ')}"` : undefined}>
              <Select
                value={outcome}
                onChange={(event) => setOutcome(event.target.value as AttemptOutcome)}
                aria-label="Attempt outcome"
              >
                {(Object.keys(ATTEMPT_OUTCOME_META) as AttemptOutcome[]).map((value) => (
                  <option key={value} value={value}>
                    {ATTEMPT_OUTCOME_META[value].label}
                  </option>
                ))}
              </Select>
            </Field>

            <Field label="Duration (minutes)">
              <input
                type="number"
                min={0}
                max={240}
                value={duration}
                onChange={(event) => setDuration(event.target.value)}
                aria-label="Attempt duration in minutes"
                className="h-9 w-full rounded-[var(--radius-control)] border border-border bg-surface px-3 text-sm outline-none focus:border-primary focus:ring-2 focus:ring-ring/40"
              />
            </Field>
          </div>

          <Field label="Notes" hint="Optional — what worked, what stalled you">
            <Textarea
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              rows={2}
              placeholder="Wrote the brute force first, then realised the prefix-sum reduction…"
            />
          </Field>

          <div className="flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              loading={createAttempt.isPending}
              onClick={() => void submit()}
            >
              Save attempt
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setShowForm(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : null}

      {sorted.length === 0 ? (
        <EmptyState
          compact
          title="No attempts recorded"
          description="Logging attempts is what drives the revision schedule — the outcome decides when this problem comes back."
        />
      ) : (
        <ol className="space-y-2">
          {sorted.map((attempt) => {
            const meta = attempt.outcome ? ATTEMPT_OUTCOME_META[attempt.outcome] : null;
            return (
              <li
                key={attempt.id}
                className="rounded-[var(--radius-card)] border border-border bg-surface px-3 py-2.5"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    {meta?.tone === 'success' ? (
                      <CheckCircle2 className="size-3.5 text-success" />
                    ) : meta?.tone === 'danger' ? (
                      <XCircle className="size-3.5 text-danger" />
                    ) : null}
                    {attempt.outcome ? (
                      <OutcomeBadge
                        outcome={attempt.outcome}
                        label={ATTEMPT_OUTCOME_META[attempt.outcome].label}
                        tone={ATTEMPT_OUTCOME_META[attempt.outcome].tone}
                      />
                    ) : (
                      <Badge tone="neutral" size="sm">
                        No outcome
                      </Badge>
                    )}
                    {attempt.duration_minutes ? (
                      <span className="tabular text-[12px] text-muted-foreground">
                        {formatMinutes(attempt.duration_minutes)}
                      </span>
                    ) : null}
                  </div>
                  <span className="text-[12px] text-subtle-foreground">
                    {formatRelativeTime(attempt.created_at)}
                  </span>
                </div>

                {attempt.notes ? (
                  <p className="mt-1.5 text-[12px] text-muted-foreground">{attempt.notes}</p>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}

      {/* Manual revision scheduling shortcut */}
      <div className="rounded-[var(--radius-card)] border border-border bg-surface px-3 py-2.5">
        <p className="text-[12px] text-muted-foreground">
          Want this back sooner? Reschedule a revision explicitly.
        </p>
        <div className="mt-2 flex flex-wrap gap-2">
          {[
            { label: 'Tomorrow', days: 1 },
            { label: 'In 3 days', days: 3 },
            { label: 'In a week', days: 7 },
          ].map((option) => (
            <Button
              key={option.label}
              variant="outline"
              size="sm"
              loading={updateProgress.isPending}
              onClick={() => {
                const due = new Date();
                due.setDate(due.getDate() + option.days);
                due.setHours(9, 0, 0, 0);
                updateProgress.mutate({
                  problemId,
                  payload: { schedule_revision: true },
                });
              }}
              title={`Queue a revision due ${option.label.toLowerCase()}`}
            >
              {option.label}
            </Button>
          ))}
        </div>
      </div>
    </div>
  );
}

/** Revision history for this problem: when it was due, what happened, what changed. */
export function RevisionHistoryPanel({
  revisions,
  className,
}: {
  revisions: Revision[];
  className?: string;
}) {
  const sorted = useMemo(
    () => [...revisions].sort((a, b) => (a.due_at < b.due_at ? 1 : -1)),
    [revisions],
  );

  if (sorted.length === 0) {
    return (
      <EmptyState
        className={className}
        compact
        title="No revisions yet"
        description="Solve this problem and InterviewReady schedules the first review automatically, using your confidence to pick the interval."
      />
    );
  }

  return (
    <div className={cn('space-y-3', className)}>
      <div>
        <h3 className="text-[13px] font-semibold">Revision history</h3>
        <p className="mt-0.5 text-[12px] text-muted-foreground">
          {sorted.filter((revision) => revision.completed).length} completed ·{' '}
          {sorted.filter((revision) => !revision.completed).length} outstanding
        </p>
      </div>

      <div className="overflow-hidden rounded-[var(--radius-card)] border border-border">
        <table className="w-full text-sm">
          <thead className="border-b border-border bg-muted">
            <tr className="text-left text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">
              <th scope="col" className="px-3 py-2">Due</th>
              <th scope="col" className="px-3 py-2">State</th>
              <th scope="col" className="px-3 py-2">Result</th>
              <th scope="col" className="px-3 py-2">Confidence before</th>
              <th scope="col" className="px-3 py-2">Interval</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((revision) => (
              <RevisionHistoryRow key={revision.id} revision={revision} />
            ))}
          </tbody>
        </table>
      </div>

      {/* Next scheduled review, called out because it is the actionable fact */}
      {sorted.find((revision) => !revision.completed) ? (
        <p className="text-[12px] text-muted-foreground">
          Next review:{' '}
          <span className="font-medium text-foreground">
            {formatRelativeDay(sorted.find((revision) => !revision.completed)!.due_at)}
          </span>
        </p>
      ) : null}
    </div>
  );
}
