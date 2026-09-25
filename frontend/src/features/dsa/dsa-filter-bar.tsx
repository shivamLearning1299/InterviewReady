import { useMemo } from 'react';
import { Search, SlidersHorizontal, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input, Select } from '@/components/ui/input';
import { SegmentedControl } from '@/components/ui/switch';
import { FilterBar } from '@/components/shared/page-header';
import { COMMON_COMPANIES } from '@/lib/constants';
import { DIFFICULTY_OPTIONS, PROBLEM_STATUS_OPTIONS } from '@/lib/status';
import { cn } from '@/lib/utils';
import type { Difficulty, ProblemStatus } from '@/types/common';

export interface CatalogFilters {
  search: string;
  topic: string;
  pattern: string;
  difficulty: Difficulty | 'all';
  status: ProblemStatus | 'all';
  company: string;
  revisionDue: boolean;
  orderBy: 'curriculum' | 'difficulty' | 'title' | 'importance' | 'recent';
}

export const EMPTY_FILTERS: CatalogFilters = {
  search: '',
  topic: 'all',
  pattern: 'all',
  difficulty: 'all',
  status: 'all',
  company: 'all',
  revisionDue: false,
  orderBy: 'curriculum',
};

const SORT_OPTIONS = [
  { value: 'curriculum', label: 'Curriculum order' },
  { value: 'difficulty', label: 'Difficulty' },
  { value: 'title', label: 'Title' },
  { value: 'importance', label: 'Importance' },
  { value: 'recent', label: 'Recently updated' },
] as const;

/**
 * Catalog filter bar.
 *
 * Filters combine with AND on the server, so each control maps to exactly one query
 * parameter. Active filters are summarised with a count and cleared in one action — a
 * long-running filter set is otherwise easy to lose track of.
 */
export function DsaFilterBar({
  filters,
  onChange,
  topics,
  patterns,
  resultCount,
  totalCount,
  className,
}: {
  filters: CatalogFilters;
  onChange: (next: Partial<CatalogFilters>) => void;
  topics: { slug: string; name: string }[];
  patterns: string[];
  resultCount?: number;
  totalCount?: number;
  className?: string;
}) {
  const activeCount = useMemo(() => {
    let count = 0;
    if (filters.search.trim()) count += 1;
    if (filters.topic !== 'all') count += 1;
    if (filters.pattern !== 'all') count += 1;
    if (filters.difficulty !== 'all') count += 1;
    if (filters.status !== 'all') count += 1;
    if (filters.company !== 'all') count += 1;
    if (filters.revisionDue) count += 1;
    return count;
  }, [filters]);

  return (
    <FilterBar className={className}>
      {/* Search */}
      <div className="relative min-w-56 flex-1">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-subtle-foreground" />
        <Input
          value={filters.search}
          onChange={(event) => onChange({ search: event.target.value })}
          placeholder="Search problems, topics…"
          aria-label="Search problems"
          className="pl-8"
        />
        {filters.search ? (
          <button
            type="button"
            onClick={() => onChange({ search: '' })}
            aria-label="Clear search"
            className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-0.5 text-subtle-foreground hover:text-foreground"
          >
            <X className="size-3.5" />
          </button>
        ) : null}
      </div>

      {/* Topic */}
      <Select
        value={filters.topic}
        onChange={(event) => onChange({ topic: event.target.value })}
        aria-label="Filter by topic"
        className="w-auto min-w-36"
      >
        <option value="all">All topics</option>
        {topics.map((topic) => (
          <option key={topic.slug} value={topic.name}>
            {topic.name}
          </option>
        ))}
      </Select>

      {/* Pattern */}
      <Select
        value={filters.pattern}
        onChange={(event) => onChange({ pattern: event.target.value })}
        aria-label="Filter by pattern"
        className="w-auto min-w-40"
      >
        <option value="all">All patterns</option>
        {patterns.map((pattern) => (
          <option key={pattern} value={pattern}>
            {pattern}
          </option>
        ))}
      </Select>

      {/* Difficulty */}
      <Select
        value={filters.difficulty}
        onChange={(event) => onChange({ difficulty: event.target.value as CatalogFilters['difficulty'] })}
        aria-label="Filter by difficulty"
        className="w-auto"
      >
        <option value="all">Any difficulty</option>
        {DIFFICULTY_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </Select>

      {/* Status */}
      <Select
        value={filters.status}
        onChange={(event) => onChange({ status: event.target.value as CatalogFilters['status'] })}
        aria-label="Filter by status"
        className="w-auto"
      >
        <option value="all">Any status</option>
        {PROBLEM_STATUS_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </Select>

      {/* Company */}
      <Select
        value={filters.company}
        onChange={(event) => onChange({ company: event.target.value })}
        aria-label="Filter by company"
        className="w-auto"
      >
        <option value="all">Any company</option>
        {COMMON_COMPANIES.map((company) => (
          <option key={company} value={company}>
            {company}
          </option>
        ))}
      </Select>

      {/* Revision due */}
      <button
        type="button"
        onClick={() => onChange({ revisionDue: !filters.revisionDue })}
        aria-pressed={filters.revisionDue}
        className={cn(
          'h-9 rounded-[var(--radius-control)] border px-3 text-[13px] font-medium transition-colors',
          filters.revisionDue
            ? 'border-warning/30 bg-warning-soft text-warning'
            : 'border-border text-muted-foreground hover:border-border-strong hover:text-foreground',
        )}
      >
        Revision due
      </button>

      {/* Sort */}
      <div className="ml-auto flex items-center gap-2">
        <SlidersHorizontal className="size-3.5 text-subtle-foreground" aria-hidden />
        <Select
          value={filters.orderBy}
          onChange={(event) => onChange({ orderBy: event.target.value as CatalogFilters['orderBy'] })}
          aria-label="Sort order"
          className="w-auto"
        >
          {SORT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>

        {activeCount > 0 ? (
          <Button variant="subtle" size="sm" onClick={() => onChange(EMPTY_FILTERS)}>
            <X />
            Clear {activeCount} filter{activeCount === 1 ? '' : 's'}
          </Button>
        ) : null}
      </div>

      {resultCount !== undefined && totalCount !== undefined ? (
        <p className="tabular w-full text-[12px] text-muted-foreground sm:w-auto">
          Showing <span className="font-medium text-foreground">{resultCount}</span> of {totalCount}
        </p>
      ) : null}
    </FilterBar>
  );
}

/** View toggle (table on desktop, cards on mobile) shared by the catalogs. */
export function ViewToggle<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (value: T) => void;
  options: readonly { value: T; label: string }[];
}) {
  return (
    <SegmentedControl
      label="View"
      options={options.map((option) => ({ value: option.value, label: option.label }))}
      value={value}
      onChange={onChange}
      size="sm"
    />
  );
}
