import { useMemo } from 'react';
import { Link } from 'react-router-dom';

import { ProgressBar, ProgressStat } from '@/components/ui/progress';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { percent } from '@/lib/helpers';
import { cn } from '@/lib/utils';
import type { DSAProblemSummary } from '@/types/dsa';
import type { TopicOption } from '@/types/dsa';

/**
 * Progress panel beside the catalog: overall completion plus per-topic strength.
 *
 * The "mastered" figure is broken out from "solved" because they mean different things —
 * solved once versus retained — and conflating them hides the revision backlog.
 */
export function DsaProgressPanel({
  problems,
  topics,
  className,
}: {
  problems: DSAProblemSummary[];
  topics: TopicOption[];
  className?: string;
}) {
  const summary = useMemo(() => {
    const mastered = problems.filter((problem) => problem.progress.status === 'mastered').length;
    const solved = problems.filter((problem) => problem.progress.status === 'solved').length;
    const needsRevision = problems.filter((problem) => problem.progress.status === 'needs_revision').length;
    const attempted = problems.filter((problem) => problem.progress.status === 'attempted').length;
    const untouched = problems.filter((problem) => problem.progress.status === 'not_started').length;
    const done = mastered + solved + needsRevision;

    return { mastered, solved, needsRevision, attempted, untouched, done, total: problems.length };
  }, [problems]);

  // Weakest topics first — this panel exists to point at what needs work.
  const ranked = useMemo(
    () =>
      topics
        .map((topic) => ({
          ...topic,
          percentage: percent(topic.solved ?? 0, topic.total ?? 0),
        }))
        .sort((a, b) => a.percentage - b.percentage),
    [topics],
  );

  return (
    <Card padding="md" className={cn('space-y-4', className)}>
      <div>
        <h2 className="text-sm font-semibold">Overall progress</h2>
        <p className="mt-0.5 text-[12px] text-muted-foreground">
          Across the whole catalog
        </p>
      </div>

      <div className="space-y-3">
        <ProgressStat
          label="Completed"
          value={summary.done}
          total={summary.total}
          tone="primary"
          hint={`${percent(summary.done, summary.total)}% of the catalog`}
        />

        <div className="grid grid-cols-2 gap-2">
          <MiniStat label="Mastered" value={summary.mastered} tone="primary" />
          <MiniStat label="Solved" value={summary.solved} tone="success" />
          <MiniStat label="Needs revision" value={summary.needsRevision} tone="warning" />
          <MiniStat label="Not started" value={summary.untouched} tone="neutral" />
        </div>
      </div>

      <div className="border-t border-border pt-3">
        <h3 className="text-[13px] font-semibold">Topic progress</h3>
        <ul className="mt-2 space-y-2.5">
          {ranked.slice(0, 12).map((topic) => (
            <li key={topic.slug} className="space-y-1">
              <div className="flex items-baseline justify-between gap-2 text-[12px]">
                <Link
                  to={`/dsa?topic=${encodeURIComponent(topic.name)}`}
                  className="truncate text-foreground hover:text-primary hover:underline"
                >
                  {topic.name}
                </Link>
                <span className="tabular shrink-0 text-muted-foreground">
                  {topic.solved ?? 0} / {topic.total ?? 0}
                </span>
              </div>
              <ProgressBar
                value={topic.percentage}
                tone={topic.percentage >= 75 ? 'success' : topic.percentage >= 40 ? 'primary' : 'warning'}
                size="xs"
                label={`${topic.name} progress`}
              />
            </li>
          ))}
          {ranked.length === 0 ? (
            <li className="text-[12px] text-muted-foreground">No topics yet.</li>
          ) : null}
        </ul>
      </div>
    </Card>
  );
}

function MiniStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: 'primary' | 'success' | 'warning' | 'neutral';
}) {
  const toneClass =
    tone === 'primary'
      ? 'text-primary'
      : tone === 'success'
        ? 'text-success'
        : tone === 'warning'
          ? 'text-warning'
          : 'text-muted-foreground';

  return (
    <div className="rounded-[var(--radius-control)] border border-border px-2.5 py-2">
      <p className="text-[11px] tracking-wide text-subtle-foreground uppercase">{label}</p>
      <p className={cn('tabular mt-0.5 text-base leading-none font-semibold', toneClass)}>{value}</p>
    </div>
  );
}

/** Difficulty split used on the catalog sidebar. */
export function DifficultyBreakdownBar({
  problems,
  className,
}: {
  problems: DSAProblemSummary[];
  className?: string;
}) {
  const counts = useMemo(() => {
    const easy = problems.filter((problem) => problem.difficulty === 'easy');
    const medium = problems.filter((problem) => problem.difficulty === 'medium');
    const hard = problems.filter((problem) => problem.difficulty === 'hard');
    return [
      { label: 'Easy', total: easy.length, solved: easy.filter((p) => p.progress.status !== 'not_started').length },
      { label: 'Medium', total: medium.length, solved: medium.filter((p) => p.progress.status !== 'not_started').length },
      { label: 'Hard', total: hard.length, solved: hard.filter((p) => p.progress.status !== 'not_started').length },
    ];
  }, [problems]);

  return (
    <Card padding="md" className={cn('space-y-3', className)}>
      <h2 className="text-sm font-semibold">By difficulty</h2>
      <ul className="space-y-2.5">
        {counts.map((entry) => (
          <li key={entry.label} className="space-y-1">
            <div className="flex items-center justify-between gap-2 text-[12px]">
              <Badge
                tone={entry.label.toLowerCase() as 'easy' | 'medium' | 'hard'}
                size="sm"
              >
                {entry.label}
              </Badge>
              <span className="tabular text-muted-foreground">
                {entry.solved} / {entry.total}
              </span>
            </div>
            <ProgressBar
              value={entry.solved}
              max={Math.max(1, entry.total)}
              tone={entry.label.toLowerCase() as 'easy' | 'medium' | 'hard'}
              size="xs"
              label={`${entry.label} progress`}
            />
          </li>
        ))}
      </ul>
    </Card>
  );
}
