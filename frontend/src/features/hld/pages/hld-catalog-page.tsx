import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { CurriculumCatalog } from '@/features/shared/curriculum-catalog';
import { useHldTopics } from '@/hooks/use-api';
import { HLD_CATEGORY_LABELS } from '@/lib/constants';
import { routes } from '@/lib/query-keys';
import type { HLDCategory, TopicStatus } from '@/types/common';

const CATEGORY_ORDER: HLDCategory[] = ['fundamentals', 'system_design'];

/** HLD curriculum tracker: fundamentals plus the classic system design problems. */
export function HldCatalogPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  const [search, setSearch] = useState(searchParams.get('search') ?? '');
  const [status, setStatus] = useState<TopicStatus | 'all'>(
    (searchParams.get('status') as TopicStatus | null) ?? 'all',
  );
  const [category, setCategory] = useState<HLDCategory | 'all'>(
    (searchParams.get('category') as HLDCategory | null) ?? 'all',
  );

  const syncParam = (key: string, value: string) => {
    const params = new URLSearchParams(searchParams);
    if (!value || value === 'all') params.delete(key);
    else params.set(key, value);
    setSearchParams(params, { replace: true });
  };

  const topics = useHldTopics({
    search: search.trim() || undefined,
    status: status === 'all' ? undefined : status,
    category: category === 'all' ? undefined : category,
    order_by: 'curriculum',
    limit: 200,
  });

  return (
    <CurriculumCatalog
      title="High-Level Design"
      description="Scaling, storage, caching and failure handling — each system documented end to end in a structured design doc."
      noun="system"
      categoryLabels={HLD_CATEGORY_LABELS}
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
      hrefFor={routes.hldTopic}
      progressNote="A system counts as done only once requirements, data model, scaling and trade-offs are all written."
    />
  );
}
