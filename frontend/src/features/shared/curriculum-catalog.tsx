import { useMemo } from 'react';
import { Search, X } from 'lucide-react';

import { CurriculumGroupHeader, CurriculumItem } from '@/components/shared/curriculum-item';
import { PageHeader, FilterBar } from '@/components/shared/page-header';
import { Card } from '@/components/ui/card';
import { Input, Select } from '@/components/ui/input';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';
import { SkeletonRow } from '@/components/ui/skeleton';
import { ProgressBar } from '@/components/ui/progress';
import { percent } from '@/lib/helpers';
import { TOPIC_STATUS_OPTIONS } from '@/lib/status';
import { cn } from '@/lib/utils';
import type { TopicProgressSummary, TopicStatus } from '@/types/common';

/** The shape both `LLDTopicSummary` and `HLDTopicSummary` satisfy. */
export interface CatalogTopicRow {
  id: string;
  title: string;
  category: string;
  description: string | null;
  difficulty: string;
  estimated_minutes: number;
  key_concepts: string[];
  progress: TopicProgressSummary;
}

export interface CurriculumCatalogProps<C extends string> {
  title: string;
  description: string;
  /** Singular noun for the meta line ("topic", "system"). */
  noun: string;
  categoryLabels: Record<C, string>;
  /** Presentation order for the category groups. */
  categoryOrder: C[];
  topics: CatalogTopicRow[] | undefined;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  search: string;
  onSearchChange: (value: string) => void;
  status: TopicStatus | 'all';
  onStatusChange: (value: TopicStatus | 'all') => void;
  category: C | 'all';
  onCategoryChange: (value: C | 'all') => void;
  /** Builds the workspace route for a topic. */
  hrefFor: (topicId: string) => string;
  /** Extra copy shown above the overall-progress panel. */
  progressNote?: string;
}

/**
 * Shared curriculum catalogue for LLD and HLD.
 *
 * Both curricula are the same shape — a categorised topic list with per-user progress — so
 * the screen is written once and parameterised. Duplicating it would guarantee the two
 * drift apart the first time a filter is added.
 */
export function CurriculumCatalog<C extends string>({
  title,
  description,
  noun,
  categoryLabels,
  categoryOrder,
  topics,
  isLoading,
  isError,
  onRetry,
  search,
  onSearchChange,
  status,
  onStatusChange,
  category,
  onCategoryChange,
  hrefFor,
  progressNote,
}: CurriculumCatalogProps<C>) {
  const items = topics ?? [];

  const grouped = useMemo(() => {
    const groups = new Map<C, CatalogTopicRow[]>();
    categoryOrder.forEach((key) => groups.set(key, []));
    items.forEach((topic) => {
      const bucket = groups.get(topic.category as C);
      if (bucket) bucket.push(topic);
    });
    return groups;
  }, [items, categoryOrder]);

  const overall = useMemo(() => {
    const done = items.filter((topic) =>
      ['completed', 'mastered', 'needs_revision'].includes(topic.progress.status),
    ).length;
    return {
      done,
      total: items.length,
      mastered: items.filter((topic) => topic.progress.status === 'mastered').length,
      learning: items.filter((topic) => topic.progress.status === 'learning').length,
      notStarted: items.filter((topic) => topic.progress.status === 'not_started').length,
      needsRevision: items.filter((topic) => topic.progress.status === 'needs_revision').length,
    };
  }, [items]);

  const isFiltering = Boolean(search.trim()) || status !== 'all' || category !== 'all';
  const completion = percent(overall.done, overall.total);

  return (
    <div className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6">
      <PageHeader
        title={title}
        description={description}
        meta={
          <>
            <span className="tabular">
              <span className="font-medium text-foreground">{overall.done}</span> / {overall.total}{' '}
              completed
            </span>
            <span className="text-subtle-foreground">•</span>
            <span className="tabular">{overall.mastered} mastered</span>
            <span className="text-subtle-foreground">•</span>
            <span className="tabular">{overall.needsRevision} need revision</span>
          </>
        }
      />

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-4">
          <FilterBar>
            <div className="relative min-w-56 flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-subtle-foreground" />
              <Input
                value={search}
                onChange={(event) => onSearchChange(event.target.value)}
                placeholder={`Search ${noun}s…`}
                aria-label={`Search ${noun}s`}
                className="pl-8"
              />
              {search ? (
                <button
                  type="button"
                  onClick={() => onSearchChange('')}
                  aria-label="Clear search"
                  className="absolute top-1/2 right-2 -translate-y-1/2 text-subtle-foreground hover:text-foreground"
                >
                  <X className="size-3.5" />
                </button>
              ) : null}
            </div>

            <Select
              value={category}
              aria-label="Filter by category"
              onChange={(event) => onCategoryChange(event.target.value as C | 'all')}
              className="w-auto"
            >
              <option value="all">All categories</option>
              {categoryOrder.map((value) => (
                <option key={value} value={value}>
                  {categoryLabels[value]}
                </option>
              ))}
            </Select>

            <Select
              value={status}
              aria-label="Filter by status"
              onChange={(event) => onStatusChange(event.target.value as TopicStatus | 'all')}
              className="w-auto"
            >
              <option value="all">Any status</option>
              {TOPIC_STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </FilterBar>

          {isLoading ? (
            <Card padding="none">
              {Array.from({ length: 6 }).map((_, index) => (
                <SkeletonRow key={index} />
              ))}
            </Card>
          ) : isError ? (
            <Card padding="none">
              <ErrorState title={`Could not load the ${title} curriculum`} onRetry={onRetry} />
            </Card>
          ) : items.length === 0 ? (
            <Card padding="none">
              <EmptyState
                title={isFiltering ? 'Nothing matches these filters' : 'The curriculum is empty'}
                description={
                  isFiltering
                    ? 'Try a different category, or clear the search.'
                    : 'Seed the backend curriculum to start tracking progress.'
                }
              />
            </Card>
          ) : (
            categoryOrder.map((key) => {
              const group = grouped.get(key) ?? [];
              if (group.length === 0) return null;
              const done = group.filter((topic) =>
                ['completed', 'mastered', 'needs_revision'].includes(topic.progress.status),
              ).length;

              return (
                <Card key={key} padding="none" className="overflow-hidden">
                  <div className="border-b border-border px-4 py-3">
                    <CurriculumGroupHeader
                      title={categoryLabels[key]}
                      completed={done}
                      total={group.length}
                    />
                  </div>
                  <div className="divide-y divide-border">
                    {group.map((topic) => (
                      <CurriculumItem
                        key={topic.id}
                        title={topic.title}
                        description={topic.description}
                        status={topic.progress}
                        keyConcepts={topic.key_concepts}
                        estimatedMinutes={topic.estimated_minutes}
                        href={hrefFor(topic.id)}
                      />
                    ))}
                  </div>
                </Card>
              );
            })
          )}
        </div>

        {/* Progress summary */}
        <div className="space-y-4">
          <Card padding="md" className="space-y-3">
            <div>
              <h2 className="text-sm font-semibold">Overall progress</h2>
              {progressNote ? (
                <p className="mt-0.5 text-[12px] text-muted-foreground">{progressNote}</p>
              ) : null}
            </div>

            <div className="space-y-1.5">
              <div className="flex items-baseline justify-between">
                <span className="text-[13px]">Completed</span>
                <span className="tabular text-[13px]">
                  <span className="font-semibold">{overall.done}</span>
                  <span className="text-muted-foreground"> / {overall.total}</span>
                </span>
              </div>
              <ProgressBar
                value={completion}
                tone={completion >= 70 ? 'success' : 'primary'}
                label={`${title} completion`}
              />
            </div>

            <dl className="grid grid-cols-2 gap-2 pt-1">
              <StatusCount
                label="Completed"
                value={Math.max(0, overall.done - overall.mastered - overall.needsRevision)}
                tone="success"
              />
              <StatusCount label="Mastered" value={overall.mastered} tone="primary" />
              <StatusCount label="Learning" value={overall.learning} tone="info" />
              <StatusCount label="Needs revision" value={overall.needsRevision} tone="warning" />
              <StatusCount label="Not started" value={overall.notStarted} tone="neutral" />
            </dl>
          </Card>

          {categoryOrder.map((key) => {
            const group = grouped.get(key) ?? [];
            if (group.length === 0) return null;
            const done = group.filter((topic) =>
              ['completed', 'mastered', 'needs_revision'].includes(topic.progress.status),
            ).length;
            const groupCompletion = percent(done, group.length);

            return (
              <Card key={key} padding="md" className="space-y-1.5">
                <div className="flex items-baseline justify-between">
                  <h3 className="text-[13px] font-medium">{categoryLabels[key]}</h3>
                  <span className="tabular text-[12px] text-muted-foreground">
                    {done} / {group.length}
                  </span>
                </div>
                <ProgressBar
                  value={groupCompletion}
                  tone={groupCompletion >= 70 ? 'success' : 'primary'}
                  size="xs"
                  label={`${categoryLabels[key]} completion`}
                />
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function StatusCount({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: 'primary' | 'success' | 'info' | 'warning' | 'neutral';
}) {
  const toneClass =
    tone === 'primary'
      ? 'text-primary'
      : tone === 'success'
        ? 'text-success'
        : tone === 'info'
          ? 'text-info'
          : tone === 'warning'
            ? 'text-warning'
            : 'text-muted-foreground';

  return (
    <div className="rounded-[var(--radius-control)] border border-border px-2.5 py-2">
      <dt className="text-[11px] tracking-wide text-subtle-foreground uppercase">{label}</dt>
      <dd className={cn('tabular mt-0.5 text-base leading-none font-semibold', toneClass)}>{value}</dd>
    </div>
  );
}
