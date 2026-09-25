import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Loader2, Plus } from 'lucide-react';

import {
  DsaFilterBar,
  EMPTY_FILTERS,
  ViewToggle,
  type CatalogFilters,
} from '@/features/dsa/dsa-filter-bar';
import { DifficultyBreakdownBar, DsaProgressPanel } from '@/features/dsa/dsa-progress-panel';
import { PageHeader } from '@/components/shared/page-header';
import { ProblemRow, ProblemTableHeader } from '@/components/shared/problem-row';
import { Button } from '@/components/ui/button';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';
import { SkeletonTable } from '@/components/ui/skeleton';
import { useDsaTopics, useProblemCatalog } from '@/hooks/use-api';
import { debounce } from '@/lib/helpers';
import { cn } from '@/lib/utils';
import { LANGUAGE_OPTIONS } from '@/lib/constants';

/**
 * DSA catalog.
 *
 * The full problem list with every filter the API supports, a sort control and the
 * progress panels. Filters live in the URL so a filtered view can be bookmarked, shared
 * between the sidebar and global search, and survives a refresh.
 */
export function DsaCatalogPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [view, setView] = useState<'table' | 'cards'>('table');

  // Seed from the URL so `/dsa?pattern=Sliding+Window` from global search works.
  const [filters, setFilters] = useState<CatalogFilters>(() => ({
    ...EMPTY_FILTERS,
    search: searchParams.get('search') ?? '',
    topic: searchParams.get('topic') ?? 'all',
    pattern: searchParams.get('pattern') ?? 'all',
    difficulty: (searchParams.get('difficulty') as CatalogFilters['difficulty']) ?? 'all',
    status: (searchParams.get('status') as CatalogFilters['status']) ?? 'all',
    revisionDue: searchParams.get('revision_due') === 'true',
  }));

  // Debounce only the free-text search; dropdowns should filter immediately.
  const [debouncedSearch, setDebouncedSearch] = useState(filters.search);
  useEffect(() => {
    const handle = debounce((value: string) => setDebouncedSearch(value), 250);
    handle(filters.search);
    return () => handle.cancel();
  }, [filters.search]);

  // Keep the URL in step with the active filters.
  useEffect(() => {
    const next = new URLSearchParams();
    if (filters.topic !== 'all') next.set('topic', filters.topic);
    if (filters.pattern !== 'all') next.set('pattern', filters.pattern);
    if (filters.difficulty !== 'all') next.set('difficulty', filters.difficulty);
    if (filters.status !== 'all') next.set('status', filters.status);
    if (filters.revisionDue) next.set('revision_due', 'true');
    if (filters.search.trim()) next.set('search', filters.search.trim());
    setSearchParams(next, { replace: true });
  }, [filters, setSearchParams]);

  const query = useMemo(
    () => ({
      search: debouncedSearch.trim() || undefined,
      topic: filters.topic === 'all' ? undefined : filters.topic,
      pattern: filters.pattern === 'all' ? undefined : filters.pattern,
      difficulty: filters.difficulty === 'all' ? undefined : filters.difficulty,
      status: filters.status === 'all' ? undefined : filters.status,
      company: filters.company === 'all' ? undefined : filters.company,
      revision_due: filters.revisionDue || undefined,
      order_by: filters.orderBy,
      limit: 200,
    }),
    [debouncedSearch, filters],
  );

  const catalog = useProblemCatalog(query);
  const topics = useDsaTopics();

  const problems = catalog.data?.items ?? [];
  const patterns = useMemo(() => {
    const set = new Set<string>();
    problems.forEach((problem) => problem.patterns.forEach((pattern) => set.add(pattern)));
    return [...set].sort();
  }, [problems]);

  const handleFilterChange = (next: Partial<CatalogFilters>) => {
    setFilters((current) => ({ ...current, ...next }));
  };

  const isFiltering =
    debouncedSearch.trim().length > 0 ||
    filters.topic !== 'all' ||
    filters.pattern !== 'all' ||
    filters.difficulty !== 'all' ||
    filters.status !== 'all' ||
    filters.company !== 'all' ||
    filters.revisionDue;

  return (
    <div className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6">
      <PageHeader
        title="DSA"
        description="Every problem in the curriculum, with your progress, confidence and revision schedule."
        actions={
          <>
            <ViewToggle
              value={view}
              onChange={setView}
              options={[
                { value: 'table', label: 'Table' },
                { value: 'cards', label: 'Cards' },
              ] as const}
            />
          </>
        }
      />

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
        {/* Catalog */}
        <div className="min-w-0 space-y-3">
          <DsaFilterBar
            filters={filters}
            onChange={handleFilterChange}
            topics={topics.data?.items.map((topic) => ({ slug: topic.slug, name: topic.name })) ?? []}
            patterns={patterns}
            resultCount={catalog.data?.total}
            totalCount={topics.data?.items.reduce((total, topic) => total + (topic.total ?? 0), 0)}
          />

          <div className="overflow-hidden rounded-[var(--radius-card)] border border-border bg-surface">
            {catalog.isLoading ? (
              <SkeletonTable rows={10} />
            ) : catalog.isError ? (
              <ErrorState
                title="Could not load the catalog"
                description="The problem list is served from the backend catalog."
                onRetry={() => void catalog.refetch()}
              />
            ) : problems.length === 0 ? (
              <EmptyState
                icon={<Plus className="size-4" />}
                title={isFiltering ? 'No problems match these filters' : 'The catalog is empty'}
                description={
                  isFiltering
                    ? 'Try loosening a filter — the combination may be too narrow.'
                    : 'Seed the backend catalog to start tracking progress.'
                }
                action={
                  isFiltering ? (
                    <Button variant="secondary" size="sm" onClick={() => setFilters(EMPTY_FILTERS)}>
                      Clear all filters
                    </Button>
                  ) : null
                }
              />
            ) : view === 'table' ? (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-sm">
                  <ProblemTableHeader />
                  <tbody className="divide-y divide-border">
                    {problems.map((problem, index) => (
                      <ProblemRow key={problem.id} problem={problem} index={index + 1} />
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="divide-y divide-border">
                {problems.map((problem, index) => (
                  <ProblemRow
                    key={problem.id}
                    problem={problem}
                    index={index + 1}
                    variant="card"
                  />
                ))}
              </div>
            )}

            {catalog.isFetching && !catalog.isLoading ? (
              <div className="flex items-center justify-center gap-2 border-t border-border py-2 text-[12px] text-muted-foreground">
                <Loader2 className="size-3 animate-spin" />
                Refreshing…
              </div>
            ) : null}
          </div>
        </div>

        {/* Progress panels */}
        <div className={cn('space-y-4', view === 'cards' && 'xl:block')}>
          <DsaProgressPanel
            problems={problems}
            topics={topics.data?.items ?? []}
          />
          <DifficultyBreakdownBar problems={problems} />

          <div className="rounded-[var(--radius-card)] border border-border bg-surface p-4">
            <h2 className="text-sm font-semibold">Languages</h2>
            <p className="mt-0.5 text-[12px] text-muted-foreground">
              Available in the problem workspace
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {LANGUAGE_OPTIONS.map((option) => (
                <span
                  key={option.value}
                  className="rounded border border-border px-1.5 py-0.5 text-[11px] text-muted-foreground"
                >
                  {option.label}
                </span>
              ))}
            </div>
            <p className="mt-2.5 text-[11px] text-subtle-foreground">
              Code is stored as plain text. InterviewReady does not compile or execute it.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
