import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { CurriculumCatalog } from '@/features/shared/curriculum-catalog';
import { useLldTopics } from '@/hooks/use-api';
import { LLD_CATEGORY_LABELS } from '@/lib/constants';
import { routes } from '@/lib/query-keys';
import type { LLDCategory, TopicStatus } from '@/types/common';

const CATEGORY_ORDER: LLDCategory[] = ['fundamentals', 'design_patterns', 'design_exercises'];

/**
 * LLD curriculum tracker: fundamentals, patterns and design problems.
 *
 * Progress is shown per category as well as overall, because "Fundamentals done, patterns
 * half-learned, problems untouched" is the useful signal — one global percentage hides it.
 */
export function LldCatalogPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  const [search, setSearch] = useState(searchParams.get('search') ?? '');
  const [status, setStatus] = useState<TopicStatus | 'all'>(
    (searchParams.get('status') as TopicStatus | null) ?? 'all',
  );
  const [category, setCategory] = useState<LLDCategory | 'all'>(
    (searchParams.get('category') as LLDCategory | null) ?? 'all',
  );

  /** Keep filters in the URL so a filtered view is shareable and survives reload. */
  const syncParam = (key: string, value: string) => {
    const params = new URLSearchParams(searchParams);
    if (!value || value === 'all') params.delete(key);
    else params.set(key, value);
    setSearchParams(params, { replace: true });
  };

  const topics = useLldTopics({
    search: search.trim() || undefined,
    status: status === 'all' ? undefined : status,
    category: category === 'all' ? undefined : category,
    order_by: 'curriculum',
    limit: 200,
  });

  return (
    <CurriculumCatalog
      title="Low-Level Design"
      description="Fundamentals, design patterns and classic design problems — each with responsibilities, notes and a working implementation."
      noun="topic"
      categoryLabels={LLD_CATEGORY_LABELS}
      categoryOrder={CATEGORY_ORDER}
      topics={topics.data?.items}
      isLoading={topics.isLoading}
      isError={topics.isError}
      onRetry={() => void topics.refetch()}
      search={search}
      onSearchChange={(value) => {
        setSearch(value);
        syncParam('search', value);
      }}
      status={status}
      onStatusChange={(value) => {
        setStatus(value);
        syncParam('status', value);
      }}
      category={category}
      onCategoryChange={(value) => {
        setCategory(value);
        syncParam('category', value);
      }}
      hrefFor={routes.lldTopic}
      progressNote="Counts include anything flagged for revision — if it is not solid, it is not done."
    />
  );
}
