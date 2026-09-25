import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Flame, Target, TrendingUp } from 'lucide-react';

import { PageHeader } from '@/components/shared/page-header';
import { StatCard, StreakBadge } from '@/components/shared/stat-card';
import { Card } from '@/components/ui/card';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';
import { ProgressBar, StackedBar } from '@/components/ui/progress';
import { SkeletonCard } from '@/components/ui/skeleton';
import { SegmentedControl } from '@/components/ui/switch';
import {
  useActivityStats,
  useDifficultyStats,
  useStatsOverview,
  useStreak,
  useTopicStats,
} from '@/hooks/use-api';
import { ACTIVITY_RANGE_OPTIONS } from '@/lib/constants';
import { formatMinutes, formatShortDate } from '@/lib/format';
import { DIFFICULTY_META } from '@/lib/status';
import { percent } from '@/lib/helpers';
import { cn } from '@/lib/utils';
import type { ActivityRange, Difficulty } from '@/types/common';
const DIFFICULTY_TONE: Record<string, 'easy' | 'medium' | 'hard'> = {
  easy: 'easy',
  medium: 'medium',
  hard: 'hard',
};

/**
 * Statistics.
 *
 * Ordered by decision value: where am I, what is weak, am I consistent, then the long-run
 * trend. Charts stay deliberately plain — a study dashboard is read in glances, and
 * decoration competes with the numbers.
 */
export function StatisticsPage() {
  const [range, setRange] = useState<ActivityRange>('30d');

  const overview = useStatsOverview();
  const topics = useTopicStats();
  const difficulty = useDifficultyStats();
  const activity = useActivityStats(range);
  const streak = useStreak();

  const dsa = overview.data?.dsa;
  const lld = overview.data?.lld;
  const hld = overview.data?.hld;

  /** Sorted by completion so the weakest topics are impossible to miss. */
  const topicRows = useMemo(
    () =>
      (topics.data?.items ?? [])
        .slice()
        .sort((a, b) => b.completion_percentage - a.completion_percentage),
    [topics.data],
  );

  const weakest = useMemo(
    () =>
      topicRows
        .filter((topic) => topic.attempted > 0)
        .slice()
        .sort((a, b) => a.completion_percentage - b.completion_percentage)
        .slice(0, 5),
    [topicRows],
  );

  const strongest = useMemo(
    () => topicRows.filter((topic) => topic.solved > 0).slice(0, 5),
    [topicRows],
  );

  const activitySeries = useMemo(() => {
    return (activity.data?.items ?? []).map((point) => ({
      date: point.date,
      label: formatShortDate(point.date),
      solved: point.problems_solved,
      attempted: point.problems_attempted,
      revisions: point.revisions_completed,
      minutes: point.study_minutes,
    }));
  }, [activity.data]);

  if (overview.isError) {
    return (
      <ErrorState
        title="Could not load your statistics"
        description="The analytics service did not respond."
        onRetry={() => void overview.refetch()}
        className="min-h-[60vh]"
      />
    );
  }

  return (
    <div className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6">
      <PageHeader
        title="Statistics"
        description="Where you stand, what is weak, and whether the work is actually happening."
        actions={
          streak.data ? (
            <StreakBadge
              current={streak.data.current}
              todayActive={streak.data.today_active}
              size="lg"
            />
          ) : undefined
        }
      />

      {/* ------------------------------------------------------------------ figures */}
      <section className="mt-5">
        <h2 className="mb-3 text-[11px] font-semibold tracking-wide text-subtle-foreground uppercase">
          Coverage
        </h2>
        {overview.isLoading ? (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <SkeletonCard lines={2} />
            <SkeletonCard lines={2} />
            <SkeletonCard lines={2} />
            <SkeletonCard lines={2} />
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label="DSA solved"
              value={dsa ? `${dsa.solved} / ${dsa.total}` : '—'}
              hint={dsa ? `${dsa.mastered} mastered · ${dsa.attempted} attempted` : undefined}
              icon={<Target />}
              className="gap-3"
            >
              <ProgressBar
                value={percent(dsa?.solved ?? 0, dsa?.total ?? 0)}
                tone="primary"
                size="xs"
                label="DSA solved"
              />
            </StatCard>

            <StatCard
              label="LLD completed"
              value={lld ? `${lld.completed} / ${lld.total}` : '—'}
              hint={lld ? `${lld.mastered} mastered · ${lld.learning} learning` : undefined}
            >
              <ProgressBar
                value={percent(lld?.completed ?? 0, lld?.total ?? 0)}
                tone="primary"
                size="xs"
                label="LLD completed"
              />
            </StatCard>

            <StatCard
              label="HLD completed"
              value={hld ? `${hld.completed} / ${hld.total}` : '—'}
              hint={hld ? `${hld.mastered} mastered · ${hld.learning} learning` : undefined}
            >
              <ProgressBar
                value={percent(hld?.completed ?? 0, hld?.total ?? 0)}
                tone="primary"
                size="xs"
                label="HLD completed"
              />
            </StatCard>

            <StatCard
              label="Revision backlog"
              value={overview.data?.revision_due ?? 0}
              hint={`${overview.data?.revision_overdue ?? 0} overdue`}
              tone={overview.data && overview.data.revision_overdue > 0 ? 'warning' : 'default'}
              icon={<Flame />}
              action={
                <Link
                  to="/revisions"
                  className="text-[12px] font-medium text-primary hover:underline"
                >
                  Review now
                </Link>
              }
            />
          </div>
        )}
      </section>

      {/* ------------------------------------------------------------------ cadence */}
      <section className="mt-5">
        <h2 className="mb-3 text-[11px] font-semibold tracking-wide text-subtle-foreground uppercase">
          Study cadence
        </h2>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label="Current streak"
            value={streak.data ? `${streak.data.current} d` : '—'}
            hint={streak.data?.today_active ? 'Active today' : 'Not active today yet'}
            tone={streak.data?.today_active ? 'success' : 'default'}
          />
          <StatCard
            label="Longest streak"
            value={streak.data ? `${streak.data.longest} d` : '—'}
            hint="Personal record"
          />
          <StatCard
            label="Study time this week"
            value={overview.data ? formatMinutes(overview.data.study_time.week_minutes) : '—'}
            hint={
              overview.data
                ? `${formatMinutes(overview.data.study_time.today_minutes)} today`
                : undefined
            }
          />
          <StatCard
            label="Solved today"
            value={overview.data?.problems_solved_today ?? 0}
            hint={
              overview.data
                ? `${overview.data.days_active_last_30} active days in the last 30`
                : undefined
            }
          />
        </div>
      </section>

      {/* ------------------------------------------------------------------ trends */}
      <section className="mt-5 grid gap-4 xl:grid-cols-2">
        <Card padding="md" className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">Problems solved</h2>
              <p className="mt-0.5 text-[12px] text-muted-foreground">
                Solved versus attempted, per {activity.data?.granularity ?? 'day'}.
              </p>
            </div>
            <SegmentedControl
              size="sm"
              label="Activity range"
              value={range}
              onChange={setRange}
              options={ACTIVITY_RANGE_OPTIONS}
            />
          </div>

          {activity.isLoading ? (
            <div className="h-56 animate-soft-pulse rounded bg-muted" />
          ) : activitySeries.length === 0 ? (
            <EmptyState
              compact
              title="No activity in this range"
              description="Solve or revise something and the graph will populate."
            />
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={activitySeries} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
                  <defs>
                    <linearGradient id="solvedFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.28} />
                      <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                  <XAxis
                    dataKey="label"
                    tick={{ fontSize: 11, fill: 'var(--chart-axis)' }}
                    tickLine={false}
                    axisLine={{ stroke: 'var(--chart-grid)' }}
                    minTickGap={24}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: 'var(--chart-axis)' }}
                    tickLine={false}
                    axisLine={false}
                    allowDecimals={false}
                    width={36}
                  />
                  <RechartsTooltip
                    contentStyle={{
                      background: 'var(--surface)',
                      border: '1px solid var(--border)',
                      borderRadius: 'var(--radius-control)',
                      fontSize: 12,
                    }}
                    labelStyle={{ color: 'var(--muted-foreground)' }}
                  />
                  <Area
                    type="monotone"
                    dataKey="attempted"
                    name="Attempted"
                    stroke="var(--chart-3)"
                    strokeWidth={1.5}
                    fill="transparent"
                  />
                  <Area
                    type="monotone"
                    dataKey="solved"
                    name="Solved"
                    stroke="var(--chart-1)"
                    strokeWidth={2}
                    fill="url(#solvedFill)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card padding="md" className="space-y-3">
          <div>
            <h2 className="text-sm font-semibold">Study time</h2>
            <p className="mt-0.5 text-[12px] text-muted-foreground">
              Minutes per {activity.data?.granularity ?? 'day'}, from timed sessions.
            </p>
          </div>

          {activity.isLoading ? (
            <div className="h-56 animate-soft-pulse rounded bg-muted" />
          ) : activitySeries.length === 0 ? (
            <EmptyState
              compact
              title="No timed sessions yet"
              description="Start the timer on a problem and the trend will appear here."
            />
          ) : (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={activitySeries} margin={{ top: 4, right: 4, bottom: 0, left: -18 }}>
                  <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
                  <XAxis
                    dataKey="label"
                    tick={{ fontSize: 11, fill: 'var(--chart-axis)' }}
                    tickLine={false}
                    axisLine={{ stroke: 'var(--chart-grid)' }}
                    minTickGap={24}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: 'var(--chart-axis)' }}
                    tickLine={false}
                    axisLine={false}
                    width={36}
                  />
                  <RechartsTooltip
                    contentStyle={{
                      background: 'var(--surface)',
                      border: '1px solid var(--border)',
                      borderRadius: 'var(--radius-control)',
                      fontSize: 12,
                    }}
                    labelStyle={{ color: 'var(--muted-foreground)' }}
                    formatter={(value) => [`${String(value)} min`, 'Study time']}
                  />
                  <Bar dataKey="minutes" name="Minutes" radius={[2, 2, 0, 0]} maxBarSize={28}>
                    {activitySeries.map((point) => (
                      <Cell
                        key={point.date}
                        fill={point.minutes > 0 ? 'var(--chart-2)' : 'var(--chart-grid)'}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </section>

      {/* ------------------------------------------------------------------ breakdowns */}
      <section className="mt-5 grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <Card padding="md" className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold">Topic strength</h2>
              <p className="mt-0.5 text-[12px] text-muted-foreground">
                Attempted topics only. The bar is solved as a share of the topic's total.
              </p>
            </div>
            {topics.data ? (
              <span className="tabular text-[12px] text-subtle-foreground">
                {topics.data.total} topics
              </span>
            ) : null}
          </div>

          {topics.isLoading ? (
            <div className="space-y-2">
              <div className="h-4 w-full animate-soft-pulse rounded bg-muted" />
              <div className="h-4 w-full animate-soft-pulse rounded bg-muted" />
              <div className="h-4 w-full animate-soft-pulse rounded bg-muted" />
            </div>
          ) : topicRows.length === 0 ? (
            <EmptyState compact title="No topic data" description="Solve a problem to begin." />
          ) : (
            <div className="h-[22rem]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={topicRows.map((topic) => ({
                    name: topic.topic,
                    solved: topic.solved,
                    attempted: topic.attempted,
                    completion: topic.completion_percentage,
                  }))}
                  layout="vertical"
                  margin={{ top: 4, right: 24, bottom: 0, left: 8 }}
                >
                  <CartesianGrid stroke="var(--chart-grid)" horizontal={false} />
                  <XAxis
                    type="number"
                    tick={{ fontSize: 11, fill: 'var(--chart-axis)' }}
                    tickLine={false}
                    axisLine={false}
                    allowDecimals={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={132}
                    tick={{ fontSize: 11, fill: 'var(--chart-axis)' }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <RechartsTooltip
                    contentStyle={{
                      background: 'var(--surface)',
                      border: '1px solid var(--border)',
                      borderRadius: 'var(--radius-control)',
                      fontSize: 12,
                    }}
                    labelStyle={{ color: 'var(--muted-foreground)' }}
                  />
                  <Legend
                    wrapperStyle={{ fontSize: 11, color: 'var(--muted-foreground)' }}
                    iconType="circle"
                    iconSize={8}
                  />
                  <Bar
                    dataKey="attempted"
                    name="Attempted"
                    stackId="topics"
                    fill="var(--chart-grid)"
                    radius={[0, 0, 0, 0]}
                    maxBarSize={14}
                  />
                  <Bar
                    dataKey="solved"
                    name="Solved"
                    stackId="topics"
                    fill="var(--chart-1)"
                    radius={[0, 2, 2, 0]}
                    maxBarSize={14}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <div className="space-y-4">
          <Card padding="md" className="space-y-3">
            <div>
              <h2 className="text-sm font-semibold">Difficulty mix</h2>
              <p className="mt-0.5 text-[12px] text-muted-foreground">
                Solved against the catalog, by difficulty.
              </p>
            </div>

            {difficulty.isLoading ? (
              <SkeletonCard lines={2} />
            ) : (difficulty.data?.items ?? []).length === 0 ? (
              <p className="text-[12px] text-muted-foreground">No data yet.</p>
            ) : (
              <>
                <StackedBar
                  segments={(difficulty.data?.items ?? []).map((item) => ({
                    value: item.solved,
                    tone: DIFFICULTY_TONE[item.difficulty] ?? 'neutral',
                    label: DIFFICULTY_META[item.difficulty as Difficulty]?.label ?? item.difficulty,
                  }))}
                />
                <dl className="space-y-2.5 pt-1">
                  {(difficulty.data?.items ?? []).map((item) => (
                    <div key={item.difficulty} className="space-y-1">
                      <div className="flex items-baseline justify-between text-[12px]">
                        <dt className="flex items-center gap-1.5">
                          <span
                            aria-hidden
                            className={cn(
                              'size-2 rounded-full',
                              item.difficulty === 'easy'
                                ? 'bg-easy'
                                : item.difficulty === 'medium'
                                  ? 'bg-medium'
                                  : 'bg-hard',
                            )}
                          />
                          {DIFFICULTY_META[item.difficulty as Difficulty]?.label ?? item.difficulty}
                        </dt>
                        <dd className="tabular text-muted-foreground">
                          <span className="font-medium text-foreground">{item.solved}</span> /{' '}
                          {item.total}
                        </dd>
                      </div>
                      <ProgressBar
                        value={item.completion_percentage}
                        tone={DIFFICULTY_TONE[item.difficulty] ?? 'primary'}
                        size="xs"
                        label={`${item.difficulty} completion`}
                      />
                    </div>
                  ))}
                </dl>
              </>
            )}
          </Card>

          <Card padding="md" className="space-y-3">
            <h2 className="flex items-center gap-1.5 text-sm font-semibold">
              <TrendingUp className="size-3.5" />
              Strongest
            </h2>
            {strongest.length === 0 ? (
              <p className="text-[12px] text-muted-foreground">Nothing solved yet.</p>
            ) : (
              <ul className="space-y-2">
                {strongest.map((topic) => (
                  <li key={topic.topic} className="flex items-center justify-between gap-3 text-[12px]">
                    <Link
                      to={`/dsa?topic=${encodeURIComponent(topic.topic)}`}
                      className="truncate hover:text-primary hover:underline"
                    >
                      {topic.topic}
                    </Link>
                    <span className="tabular shrink-0 text-muted-foreground">
                      {topic.completion_percentage}%
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card padding="md" className="space-y-3">
            <h2 className="text-sm font-semibold">Weakest</h2>
            {weakest.length === 0 ? (
              <p className="text-[12px] text-muted-foreground">
                Not enough data yet — attempt a few problems first.
              </p>
            ) : (
              <ul className="space-y-2.5">
                {weakest.map((topic) => (
                  <li key={topic.topic} className="space-y-1">
                    <div className="flex items-center justify-between gap-3 text-[12px]">
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
                    {topic.needs_revision > 0 ? (
                      <p className="text-[11px] text-warning">
                        {topic.needs_revision} flagged for revision
                      </p>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </section>
    </div>
  );
}
