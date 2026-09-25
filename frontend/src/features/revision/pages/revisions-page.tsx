import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Clock,
  Code2,
  Eye,
  FileText,
  RotateCcw,
  Sparkles,
  TrendingDown,
  TrendingUp,
  X,
} from 'lucide-react';

import { RevisionCard } from '@/components/shared/revision-card';
import { PageHeader } from '@/components/shared/page-header';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';
import { ProgressBar, ProgressStat } from '@/components/ui/progress';
import { SkeletonCard } from '@/components/ui/skeleton';
import { Tabs } from '@/components/ui/tabs';
import { AITutorPanel } from '@/features/ai/ai-tutor-panel';
import { CodeBlock } from '@/features/code/code-editor';
import {
  useCompleteRevision,
  useProblem,
  usePromoteStale,
  useRevisionSummary,
  useRevisions,
  useTopicStats,
} from '@/hooks/use-api';
import { useStudyTimer } from '@/hooks/use-study-timer';
import { describeDue, formatClock } from '@/lib/format';
import { routes } from '@/lib/query-keys';
import { confidenceLabel } from '@/lib/status';
import { cn } from '@/lib/utils';
import type { Revision } from '@/types/dsa';

type Bucket = 'due' | 'overdue' | 'upcoming';

/**
 * Revision dashboard and session runner.
 *
 * The session enforces active recall: the previous approach and code are present but
 * *hidden* until the user explicitly asks for them, and the outcome buttons record the
 * result that advances (or resets) the spaced-repetition ladder.
 */
export function RevisionsPage() {
  const [bucket, setBucket] = useState<Bucket>('due');
  const [sessionOpen, setSessionOpen] = useState(false);

  const summary = useRevisionSummary();
  const list = useRevisions({ bucket, completed: false, limit: 100 });
  const topicStats = useTopicStats();
  const promoteStale = usePromoteStale();

  const revisions = useMemo(() => list.data?.items ?? [], [list.data]);

  /** Lowest completion first — that is where revision pays off the most. */
  const weakestTopics = useMemo(
    () =>
      (topicStats.data?.items ?? [])
        .slice()
        .sort((a, b) => a.completion_percentage - b.completion_percentage)
        .slice(0, 6),
    [topicStats.data],
  );

  const dueToday = summary.data?.due_today ?? 0;
  const overdue = summary.data?.overdue ?? 0;
  const upcoming = summary.data?.upcoming ?? 0;

  return (
    <div className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6">
      <PageHeader
        title="Revisions"
        description="Spaced repetition over everything you have solved. Reviewing is what turns solved into mastered."
        meta={
          <>
            <span className="tabular">
              <span className="font-medium text-foreground">{dueToday + overdue}</span> due now
            </span>
            <span className="text-subtle-foreground">•</span>
            <span className="tabular">
              <span className="font-medium text-foreground">{upcoming}</span> upcoming
            </span>
          </>
        }
        actions={
          <>
            <Button
              variant="ghost"
              size="sm"
              loading={promoteStale.isPending}
              onClick={() => promoteStale.mutate(10)}
              title="Find problems you have not reviewed in a while and queue them"
            >
              <RotateCcw />
              Queue stale problems
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={revisions.length === 0}
              onClick={() => setSessionOpen(true)}
            >
              <Sparkles />
              Start revision session
            </Button>
          </>
        }
      />

      {sessionOpen ? (
        <RevisionSession
          revisions={revisions}
          onClose={() => {
            setSessionOpen(false);
            void list.refetch();
          }}
        />
      ) : null}

      {/* Buckets — the cards double as filters for the list below. */}
      <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <BucketCard
          label="Due today"
          value={dueToday}
          tone={dueToday > 0 ? 'warning' : 'neutral'}
          description="Scheduled for today"
          active={bucket === 'due'}
          onClick={() => setBucket('due')}
        />
        <BucketCard
          label="Overdue"
          value={overdue}
          tone={overdue > 0 ? 'danger' : 'neutral'}
          description="Missed their date"
          active={bucket === 'overdue'}
          onClick={() => setBucket('overdue')}
        />
        <BucketCard
          label="Upcoming"
          value={upcoming}
          tone="neutral"
          description="Not due yet"
          active={bucket === 'upcoming'}
          onClick={() => setBucket('upcoming')}
        />
        <Card padding="md" className="flex flex-col justify-between gap-2">
          <p className="text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">
            Queue
          </p>
          <ProgressStat
            label="In this bucket"
            value={revisions.length}
            total={Math.max(revisions.length, dueToday + overdue + upcoming)}
            tone="primary"
            compact
            hint={`${dueToday + overdue} need attention now`}
          />
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        {/* Queue */}
        <div className="min-w-0">
          <Tabs
            className="mb-3"
            value={bucket}
            onChange={setBucket}
            items={[
              { value: 'due', label: 'Due today', hint: dueToday || undefined },
              { value: 'overdue', label: 'Overdue', hint: overdue || undefined },
              { value: 'upcoming', label: 'Upcoming', hint: upcoming || undefined },
            ]}
          />

          <Card padding="none" className="overflow-hidden">
            {list.isLoading ? (
              <div className="space-y-3 p-4">
                <SkeletonCard lines={2} />
                <SkeletonCard lines={2} />
                <SkeletonCard lines={2} />
              </div>
            ) : list.isError ? (
              <ErrorState
                title="Could not load the revision queue"
                onRetry={() => void list.refetch()}
              />
            ) : revisions.length === 0 ? (
              <EmptyState
                icon={<Check className="size-4" />}
                title={
                  bucket === 'overdue'
                    ? 'Nothing overdue'
                    : bucket === 'upcoming'
                      ? 'Nothing scheduled yet'
                      : 'The queue is clear'
                }
                description={
                  bucket === 'upcoming'
                    ? 'Solve and mark problems and the scheduler will queue reviews for you.'
                    : 'You are fully caught up. Queue stale problems to keep the practice going.'
                }
                action={
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={promoteStale.isPending}
                    onClick={() => promoteStale.mutate(10)}
                  >
                    Queue stale problems
                  </Button>
                }
              />
            ) : (
              <div className="divide-y divide-border">
                {revisions.map((revision) => (
                  <RevisionCard key={revision.id} revision={revision} />
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* Weak topics */}
        <Card padding="md" className="space-y-3 self-start">
          <div>
            <h2 className="text-sm font-semibold">Weak topics</h2>
            <p className="mt-0.5 text-[12px] text-muted-foreground">
              Lowest completion first. Revision returns the most here.
            </p>
          </div>

          {topicStats.isLoading ? (
            <SkeletonCard lines={2} />
          ) : weakestTopics.length === 0 ? (
            <p className="text-[12px] text-muted-foreground">No topic data yet.</p>
          ) : (
            <ul className="space-y-3">
              {weakestTopics.map((topic) => (
                <li key={topic.topic} className="space-y-1">
                  <div className="flex items-baseline justify-between gap-2 text-[12px]">
                    <Link
                      to={`/dsa?topic=${encodeURIComponent(topic.topic)}`}
                      className="truncate hover:text-primary hover:underline"
                    >
                      {topic.topic}
                    </Link>
                    <span className="tabular shrink-0 text-muted-foreground">
                      {topic.completion_percentage}%
                    </span>
                  </div>
                  <ProgressBar
                    value={topic.completion_percentage}
                    tone={topic.completion_percentage >= 60 ? 'primary' : 'warning'}
                    size="xs"
                    label={`${topic.topic} completion`}
                  />
                  <p className="text-[11px] text-subtle-foreground">
                    {topic.solved} / {topic.total} solved
                    {topic.needs_revision > 0 ? ` · ${topic.needs_revision} flagged` : ''}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}

/** One queue bucket, doubling as the filter control for the list. */
function BucketCard({
  label,
  value,
  tone,
  description,
  active,
  onClick,
}: {
  label: string;
  value: number;
  tone: 'neutral' | 'warning' | 'danger';
  description: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button type="button" onClick={onClick} className="text-left">
      <Card
        padding="md"
        className={cn(
          'h-full transition-colors hover:border-border-strong',
          active && 'border-primary/40 bg-primary-soft/40',
        )}
      >
        <p className="text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">
          {label}
        </p>
        <p
          className={cn(
            'tabular mt-1 text-2xl leading-none font-semibold',
            value > 0 && tone === 'danger'
              ? 'text-danger'
              : value > 0 && tone === 'warning'
                ? 'text-warning'
                : 'text-foreground',
          )}
        >
          {value}
        </p>
        <p className="mt-1 text-[12px] text-muted-foreground">{description}</p>
      </Card>
    </button>
  );
}

// ------------------------------------------------------------------- session

/**
 * The revision session.
 *
 * One problem at a time, with a server-timed clock. Previous approach and code start
 * concealed, because the point of the session is recall rather than recognition.
 */
function RevisionSession({
  revisions,
  onClose,
}: {
  revisions: Revision[];
  onClose: () => void;
}) {
  const [index, setIndex] = useState(0);
  const [revealedApproach, setRevealedApproach] = useState(false);
  const [revealedCode, setRevealedCode] = useState(false);
  const [reviewedIds, setReviewedIds] = useState<ReadonlySet<string>>(new Set());
  const [weakIds, setWeakIds] = useState<ReadonlySet<string>>(new Set());

  const completeRevision = useCompleteRevision();
  const timer = useStudyTimer();
  const startedRef = useRef(false);

  const current = revisions[index] ?? null;

  // The problem detail carries the notes and code the session reveals on demand.
  const problem = useProblem(current?.problem_id);

  // One server-side session covers the whole sitting, so pauses between problems still count.
  useEffect(() => {
    if (startedRef.current || timer.isRunning) return;
    startedRef.current = true;
    void timer.start('revision');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-conceal the previous answers whenever the problem changes.
  useEffect(() => {
    setRevealedApproach(false);
    setRevealedCode(false);
  }, [index]);

  const handleOutcome = useCallback(
    async (result: 'success' | 'partial' | 'failed') => {
      if (!current) return;

      if (result === 'failed') {
        setWeakIds((previous) => new Set(previous).add(current.id));
      } else {
        setReviewedIds((previous) => new Set(previous).add(current.id));
      }

      try {
        await completeRevision.mutateAsync({
          revisionId: current.id,
          payload: { result, schedule_next: true },
        });
      } catch {
        // The hook already surfaced a toast; keep the session usable rather than trapping
        // the user on a problem they cannot record.
        return;
      }

      if (index < revisions.length - 1) setIndex((value) => value + 1);
      else onClose();
    },
    [completeRevision, current, index, onClose, revisions.length],
  );

  if (!current) return null;

  const total = revisions.length;
  const done = reviewedIds.size + weakIds.size;

  return (
    <Card padding="none" className="mt-5 overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-[13px] font-semibold">
            Problem {index + 1} / {total}
          </span>
          <span className="tabular flex items-center gap-1.5 rounded-[var(--radius-control)] border border-border bg-muted px-2.5 py-1 text-[13px]">
            <Clock className="size-3.5" />
            {formatClock(timer.elapsedSeconds)}
          </span>
          {weakIds.size > 0 ? (
            <span className="tabular text-[12px] text-warning">{weakIds.size} flagged weak</span>
          ) : null}
        </div>

        <div className="flex items-center gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIndex((value) => Math.max(0, value - 1))}
            disabled={index === 0}
          >
            <ChevronLeft />
            Previous
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIndex((value) => Math.min(total - 1, value + 1))}
            disabled={index >= total - 1}
          >
            Skip
            <ChevronRight />
          </Button>
          <Button variant="subtle" size="sm" onClick={onClose}>
            <X />
            End session
          </Button>
        </div>
      </header>

      <div className="h-1 w-full bg-muted" aria-hidden>
        <div
          className="h-full bg-primary transition-[width] duration-300"
          style={{ width: `${(done / Math.max(1, total)) * 100}%` }}
        />
      </div>

      <div className="grid min-h-0 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-4 p-4 sm:p-5">
          {/* Problem under review */}
          <div>
            <div className="flex flex-wrap items-baseline gap-2">
              <h2 className="text-base font-semibold">
                {current.problem_title ?? 'Untitled problem'}
              </h2>
              {current.problem_topic ? (
                <span className="text-[13px] text-muted-foreground">{current.problem_topic}</span>
              ) : null}
            </div>
            <p className="mt-1 text-[12px] text-muted-foreground">
              {describeDue(current.due_at)} · confidence before{' '}
              {confidenceLabel(current.confidence_before)} ·{' '}
              {current.interval_days ? `${current.interval_days}-day interval` : 'first review'}
            </p>
          </div>

          {/* Active recall prompt */}
          <div className="rounded-[var(--radius-card)] border border-border bg-muted px-4 py-3">
            <p className="text-[13px] leading-relaxed text-foreground">
              Explain the approach out loud before revealing anything. What was the key insight,
              and which edge cases mattered?
            </p>
            <p className="mt-1.5 text-[12px] text-muted-foreground">
              Only reveal if you are genuinely stuck — the effort of recalling is what builds
              retention.
            </p>
          </div>

          {/* Reveal controls */}
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setRevealedApproach((value) => !value)}
            >
              <FileText />
              {revealedApproach ? 'Hide previous approach' : 'Show previous approach'}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setRevealedCode((value) => !value)}
            >
              <Code2 />
              {revealedCode ? 'Hide previous code' : 'Show previous code'}
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link to={routes.dsaProblem(current.problem_id)} target="_blank" rel="noreferrer">
                Open problem
              </Link>
            </Button>
          </div>

          {/* Concealed content */}
          {revealedApproach ? (
            <div className="space-y-3 rounded-[var(--radius-card)] border border-border p-3.5">
              <h3 className="text-[13px] font-semibold">Previous approach</h3>
              {problem.isLoading ? (
                <p className="text-[12px] text-muted-foreground">Loading…</p>
              ) : (
                <>
                  {problem.data?.notes?.approach ? (
                    <p className="text-[13px] leading-relaxed whitespace-pre-wrap">
                      {problem.data.notes.approach}
                    </p>
                  ) : (
                    <p className="text-[12px] text-muted-foreground">
                      No approach was recorded for this problem.
                    </p>
                  )}
                  {problem.data?.notes?.mistakes ? (
                    <div className="rounded-[var(--radius-control)] border border-warning/25 bg-warning-soft px-3 py-2">
                      <p className="text-[11px] font-medium tracking-wide text-warning uppercase">
                        Mistakes last time
                      </p>
                      <p className="mt-1 text-[12px] whitespace-pre-wrap">
                        {problem.data.notes.mistakes}
                      </p>
                    </div>
                  ) : null}
                </>
              )}
            </div>
          ) : null}

          {revealedCode ? (
            <div className="space-y-2">
              <h3 className="text-[13px] font-semibold">Previous code</h3>
              {problem.isLoading ? (
                <p className="text-[12px] text-muted-foreground">Loading…</p>
              ) : problem.data && problem.data.code_snippets.length > 0 ? (
                problem.data.code_snippets.map((snippet) => (
                  <div key={snippet.id} className="space-y-1">
                    <p className="text-[12px] text-muted-foreground">
                      {snippet.title ?? snippet.language}
                    </p>
                    <CodeBlock code={snippet.code} language={snippet.language} maxHeight="22rem" />
                  </div>
                ))
              ) : (
                <p className="rounded-[var(--radius-card)] border border-dashed border-border px-4 py-6 text-center text-[13px] text-muted-foreground">
                  No solution was saved for this problem.
                </p>
              )}
            </div>
          ) : null}

          {!revealedApproach && !revealedCode ? (
            <div className="rounded-[var(--radius-card)] border border-dashed border-border px-4 py-6 text-center">
              <Eye className="mx-auto size-4 text-subtle-foreground" />
              <p className="mt-2 text-[13px] text-muted-foreground">
                Previous approach and code are hidden.
              </p>
            </div>
          ) : null}

          {/* Outcome buttons — last, so the hand reaches them deliberately */}
          <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4">
            <Button
              variant="primary"
              size="sm"
              loading={completeRevision.isPending}
              onClick={() => void handleOutcome('success')}
            >
              <TrendingUp />
              Mark successful
            </Button>
            <Button
              variant="secondary"
              size="sm"
              loading={completeRevision.isPending}
              onClick={() => void handleOutcome('partial')}
            >
              Partially recalled
            </Button>
            <Button
              variant="outline"
              size="sm"
              loading={completeRevision.isPending}
              onClick={() => void handleOutcome('failed')}
              className="border-warning/40 text-warning hover:bg-warning-soft"
            >
              <TrendingDown />
              Still weak
            </Button>
            <span className="ml-auto text-[11px] text-subtle-foreground">
              Marking weak brings it back tomorrow at highest priority.
            </span>
          </div>
        </div>

        {/* Tutor, scoped to this problem */}
        <aside className="hidden min-h-0 border-l border-border xl:flex xl:flex-col">
          <AITutorPanel
            contextType="dsa"
            contextId={current.problem_id}
            contextLabel={current.problem_title}
            className="h-full"
          />
        </aside>
      </div>

      <footer className="flex items-center justify-between gap-3 border-t border-border bg-muted/40 px-4 py-2 text-[12px] text-muted-foreground">
        <span className="tabular">
          {done} reviewed · {total - done} remaining
        </span>
        <span className="hidden items-center gap-1.5 sm:flex">
          <Eye className="size-3" />
          Previous answers stay hidden until you ask for them
        </span>
      </footer>
    </Card>
  );
}
