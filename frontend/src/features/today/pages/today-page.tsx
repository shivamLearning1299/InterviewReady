import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Bug, CalendarCheck, Flame, Play, RotateCcw, Timer } from 'lucide-react';

import { AITutorPanel } from '@/features/ai/ai-tutor-panel';
import { greetingFor } from '@/features/today/greeting';
import { TodayItemRow, TodaySectionCard, TodaySectionSkeleton } from '@/features/today/today-item-row';
import { useWeeklyProgress } from '@/features/today/use-weekly-progress';
import { ProgressStat, ProgressBar } from '@/components/ui/progress';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { ErrorState, EmptyState } from '@/components/ui/empty-state';
import { InfoRow } from '@/components/ui/tooltip';
import { useSettings, useStatsOverview, useToday, useTogglePlanItem } from '@/hooks/use-api';
import { useStudyTimer } from '@/hooks/use-study-timer';
import { useAuth } from '@/providers/auth-provider';
import { formatClock, formatMinutes } from '@/lib/format';
import { cn } from '@/lib/utils';
import { routes } from '@/lib/query-keys';

/**
 * Today — the home screen and the most important surface in the app.
 *
 * Layout mirrors the study loop: greeting and streak, then today's three DSA questions as
 * the primary column, with the day's LLD/HLD focus, the revision queue and the weekly
 * rollup in the supporting column. Everything needed to start studying is reachable without
 * scrolling on a laptop.
 */
export function TodayPage() {
  const { user } = useAuth();
  const today = useToday();
  const overview = useStatsOverview();
  const settings = useSettings();
  const toggleItem = useTogglePlanItem();
  const timer = useStudyTimer();

  const dailyTarget = settings.data?.daily_dsa_count ?? 3;
  const { progress: weekly } = useWeeklyProgress(dailyTarget);

  const dsaStats = overview.data?.dsa;
  const solved = dsaStats?.solved ?? 0;
  const total = dsaStats?.total ?? 0;
  const streak = today.data?.streak.current ?? overview.data?.streak.current ?? 0;
  const todayActive = today.data?.streak.today_active ?? false;

  const firstName = useMemo(() => {
    const label = user?.name ?? user?.email?.split('@')[0] ?? '';
    return label.split(' ')[0] ?? '';
  }, [user]);

  if (today.isLoading) return <TodaySkeleton />;

  if (today.isError) {
    return (
      <ErrorState
        title="Could not load today's plan"
        description="The plan is generated server-side on first request. Check your connection and try again."
        onRetry={() => void today.refetch()}
        className="min-h-[60vh]"
      />
    );
  }

  const data = today.data;
  if (!data) return null;

  const dsaDone = data.dsa.completed;
  const dsaTotal = data.dsa.total;
  const dueRevisions = data.revision_summary.due_today + data.revision_summary.overdue;

  return (
    <div className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6">
      {/* ------------------------------------------------------------- greeting */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">
            {greetingFor()}
            {firstName ? `, ${firstName}` : ''}
          </h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[13px] text-muted-foreground">
            <span className="flex items-center gap-1.5">
              <Flame className={cn('size-3.5', todayActive ? 'text-warning' : 'text-subtle-foreground')} />
              <span className="tabular font-medium text-foreground">{streak}</span>
              day streak
              {!todayActive ? (
                <span className="text-subtle-foreground">· study today to keep it</span>
              ) : null}
            </span>
            <span className="hidden text-subtle-foreground sm:inline">•</span>
            <span className="flex items-center gap-1.5">
              <span className="tabular font-medium text-foreground">
                {solved} / {total}
              </span>
              DSA solved
            </span>
            {data.study_minutes_today > 0 ? (
              <>
                <span className="hidden text-subtle-foreground sm:inline">•</span>
                <span className="tabular tabular-nums">
                  {formatMinutes(data.study_minutes_today)} studied today
                </span>
              </>
            ) : null}
          </div>
        </div>

        {/* Study timer — server-timed, so the clock survives a reload */}
        <div className="flex items-center gap-2">
          {timer.isRunning ? (
            <>
              <span className="tabular flex items-center gap-2 rounded-[var(--radius-control)] border border-primary/25 bg-primary-soft px-3 py-1.5 text-[13px] font-medium text-primary">
                <Timer className="size-3.5" />
                {formatClock(timer.elapsedSeconds)}
              </span>
              <Button variant="secondary" size="sm" loading={timer.isStopping} onClick={() => void timer.stop()}>
                Stop
              </Button>
            </>
          ) : (
            <Button
              variant="secondary"
              size="sm"
              loading={timer.isStarting}
              onClick={() => void timer.start('dsa')}
            >
              <Play />
              Start study timer
            </Button>
          )}
        </div>
      </div>

      {/* ----------------------------------------------------------------- body */}
      <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        {/* Primary column */}
        <div className="min-w-0 space-y-4">
          {/* Today's DSA */}
          <TodaySectionCard
            title="Today's DSA"
            description={
              dsaTotal > 0
                ? `${dsaDone} / ${dsaTotal} completed today`
                : 'Nothing scheduled today'
            }
            completed={dsaDone}
            total={dsaTotal}
            action={
              <Button asChild variant="ghost" size="sm">
                <Link to={routes.dsa}>
                  All problems
                  <ArrowRight />
                </Link>
              </Button>
            }
          >
            {data.dsa.items.length === 0 ? (
              <EmptyState
                compact
                icon={<Bug className="size-4" />}
                title="No DSA questions scheduled"
                description="Either everything is caught up or your catalog is empty. Raise your daily target in Settings to push harder."
                action={
                  <Button asChild variant="secondary" size="sm">
                    <Link to={routes.settings}>Adjust daily target</Link>
                  </Button>
                }
              />
            ) : (
              data.dsa.items.map((item, index) => (
                <TodayItemRow
                  key={item.id}
                  item={item}
                  index={index + 1}
                  isToggling={toggleItem.isPending}
                  onToggle={() =>
                    toggleItem.mutate({ itemId: item.id, isCompleted: !item.is_completed })
                  }
                  onStart={() => {
                    if (!timer.isRunning) void timer.start('dsa', item.problem_id);
                  }}
                />
              ))
            )}
          </TodaySectionCard>

          {/* Revision due */}
          <Card padding="none" className="overflow-hidden">
            <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
              <div>
                <h2 className="text-sm font-semibold">Revision due</h2>
                <p className="mt-0.5 text-[12px] text-muted-foreground">
                  {dueRevisions > 0
                    ? `${dueRevisions} question${dueRevisions === 1 ? '' : 's'} due for revision`
                    : 'Nothing due — your queue is clear'}
                </p>
              </div>
              <Button
                asChild
                variant={dueRevisions > 0 ? 'primary' : 'secondary'}
                size="sm"
                disabled={dueRevisions === 0}
              >
                <Link to={routes.revisions}>
                  <RotateCcw />
                  {dueRevisions > 0 ? 'Start revision session' : 'Open revisions'}
                </Link>
              </Button>
            </header>

            {dueRevisions > 0 ? (
              <div className="grid grid-cols-2 divide-x divide-border sm:grid-cols-4">
                <DueStat label="Due today" value={data.revision_summary.due_today} tone="default" />
                <DueStat label="Overdue" value={data.revision_summary.overdue} tone="danger" />
                <DueStat label="Upcoming" value={data.revision_summary.upcoming} tone="default" />
                <DueStat label="Scheduled today" value={data.revisions.total} tone="default" />
              </div>
            ) : null}

            {data.revisions.items.length > 0 ? (
              <div className="divide-y divide-border border-t border-border">
                {data.revisions.items.slice(0, 3).map((item) => (
                  <TodayItemRow
                    key={item.id}
                    item={item}
                    index={item.position}
                    isToggling={toggleItem.isPending}
                    onToggle={() => toggleItem.mutate({ itemId: item.id, isCompleted: !item.is_completed })}
                    onStart={() => {
                      if (!timer.isRunning) void timer.start('revision', item.problem_id);
                    }}
                  />
                ))}
              </div>
            ) : null}
          </Card>

          {/* Weekly progress */}
          <Card padding="md">
            <header className="flex items-baseline justify-between gap-3">
              <h2 className="text-sm font-semibold">This week</h2>
              <span className="tabular text-[12px] text-muted-foreground">
                {formatMinutes(weekly.studyMinutes)} studied
              </span>
            </header>

            <div className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <ProgressStat
                label="DSA"
                value={weekly.dsaCompleted}
                total={weekly.dsaTarget}
                tone={weekly.dsaCompleted >= weekly.dsaTarget ? 'success' : 'primary'}
                compact
                hint={`target ${dailyTarget}/day`}
              />
              <ProgressStat
                label="LLD lessons"
                value={weekly.lldLessons}
                total={Math.max(weekly.lldLessons, 5)}
                tone="primary"
                compact
              />
              <ProgressStat
                label="HLD lessons"
                value={weekly.hldLessons}
                total={Math.max(weekly.hldLessons, 5)}
                tone="primary"
                compact
              />
              <ProgressStat
                label="Revisions"
                value={weekly.revisionsCompleted}
                total={Math.max(weekly.revisionsCompleted, 20)}
                tone="success"
                compact
              />
            </div>
          </Card>
        </div>

        {/* Supporting column */}
        <div className="space-y-4">
          {/* Today's LLD */}
          <Card padding="none" className="overflow-hidden">
            <header className="border-b border-border px-4 py-3">
              <h2 className="text-sm font-semibold">Today's LLD</h2>
              <p className="mt-0.5 text-[12px] text-muted-foreground">Learn + implement</p>
            </header>
            {data.lld.items.length === 0 ? (
              <EmptyState compact title="No lesson scheduled" description="Nothing queued for today." />
            ) : (
              <div className="divide-y divide-border">
                {data.lld.items.map((item, index) => (
                  <TodayItemRow
                    key={item.id}
                    item={item}
                    index={index + 1}
                    isToggling={toggleItem.isPending}
                    onToggle={() => toggleItem.mutate({ itemId: item.id, isCompleted: !item.is_completed })}
                    onStart={() => void timer.start('lld', item.topic_id)}
                  />
                ))}
              </div>
            )}
          </Card>

          {/* Today's HLD */}
          <Card padding="none" className="overflow-hidden">
            <header className="border-b border-border px-4 py-3">
              <h2 className="text-sm font-semibold">Today's HLD</h2>
              <p className="mt-0.5 text-[12px] text-muted-foreground">Study + notes</p>
            </header>
            {data.hld.items.length === 0 ? (
              <EmptyState compact title="No topic scheduled" description="Nothing queued for today." />
            ) : (
              <div className="divide-y divide-border">
                {data.hld.items.map((item, index) => (
                  <TodayItemRow
                    key={item.id}
                    item={item}
                    index={index + 1}
                    isToggling={toggleItem.isPending}
                    onToggle={() => toggleItem.mutate({ itemId: item.id, isCompleted: !item.is_completed })}
                    onStart={() => void timer.start('hld', item.topic_id)}
                  />
                ))}
              </div>
            )}
          </Card>

          {/* Day summary */}
          <Card padding="md">
            <h2 className="text-sm font-semibold">Day summary</h2>
            <dl className="mt-2 divide-y divide-border">
              <InfoRow label="Planned" value={`${dsaTotal + data.lld.total + data.hld.total} items`} />
              <InfoRow
                label="Completed"
                value={`${dsaDone + data.lld.completed + data.hld.completed} / ${
                  dsaTotal + data.lld.total + data.hld.total
                }`}
              />
              <InfoRow
                label="Estimated effort"
                value={formatMinutes(data.total_estimated_minutes)}
              />
              <InfoRow label="Study time today" value={formatMinutes(data.study_minutes_today)} />
              <InfoRow
                label="Days active (30d)"
                value={`${overview.data?.days_active_last_30 ?? 0} days`}
              />
            </dl>

            {data.is_completed ? (
              <div className="mt-3 flex items-center gap-2 rounded-[var(--radius-control)] border border-success/25 bg-success-soft px-3 py-2 text-[13px] text-success">
                <CalendarCheck className="size-4 shrink-0" />
                Everything planned for today is done.
              </div>
            ) : (
              <div className="mt-3">
                <ProgressBar
                  value={dsaDone + data.lld.completed + data.hld.completed}
                  max={Math.max(1, dsaTotal + data.lld.total + data.hld.total)}
                  tone="primary"
                  label="Today's completion"
                />
              </div>
            )}
          </Card>

          {/* AI tutor, scoped to general since Today spans several items */}
          <Card padding="none" className="flex h-[26rem] flex-col overflow-hidden">
            <AITutorPanel
              contextType="general"
              contextLabel="Today's plan"
              className="min-h-0 flex-1"
            />
          </Card>
        </div>
      </div>
    </div>
  );
}

function DueStat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: 'default' | 'danger';
}) {
  return (
    <div className="px-4 py-3">
      <p className="text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">{label}</p>
      <p
        className={cn(
          'tabular mt-1 text-lg leading-none font-semibold',
          tone === 'danger' && value > 0 ? 'text-danger' : 'text-foreground',
        )}
      >
        {value}
      </p>
    </div>
  );
}

/** Full-page skeleton mirroring the real layout so nothing shifts on load. */
function TodaySkeleton() {
  return (
    <div className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6">
      <div className="space-y-2">
        <div className="h-6 w-44 animate-soft-pulse rounded bg-muted" />
        <div className="h-3.5 w-72 animate-soft-pulse rounded bg-muted" />
      </div>

      <div className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-4">
          <SectionShell title>
            <TodaySectionSkeleton rows={3} />
          </SectionShell>
          <SectionShell title />
          <SectionShell title>
            <div className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-4">
              {Array.from({ length: 4 }).map((_, index) => (
                <div key={index} className="space-y-2">
                  <div className="h-3 w-16 animate-soft-pulse rounded bg-muted" />
                  <div className="h-4 w-full animate-soft-pulse rounded bg-muted" />
                </div>
              ))}
            </div>
          </SectionShell>
        </div>
        <div className="space-y-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <SectionShell key={index} title>
              <TodaySectionSkeleton rows={1} />
            </SectionShell>
          ))}
        </div>
      </div>
    </div>
  );
}

function SectionShell({ title, children }: { title?: boolean; children?: React.ReactNode }) {
  return (
    <div className="overflow-hidden rounded-[var(--radius-card)] border border-border bg-surface">
      {title ? (
        <div className="border-b border-border px-4 py-3">
          <div className="h-4 w-32 animate-soft-pulse rounded bg-muted" />
        </div>
      ) : null}
      {children ?? (
        <div className="space-y-2 p-4">
          <div className="h-3.5 w-1/3 animate-soft-pulse rounded bg-muted" />
          <div className="h-3 w-2/3 animate-soft-pulse rounded bg-muted" />
        </div>
      )}
    </div>
  );
}
