import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { ArrowLeft, ExternalLink, Loader2 } from 'lucide-react';

import { AITutorPanel } from '@/features/ai/ai-tutor-panel';
import { AttemptsPanel, RevisionHistoryPanel } from '@/features/dsa/attempts-panel';
import { NotesEditor } from '@/features/dsa/notes-editor';
import { ProblemHeader } from '@/features/dsa/problem-header';
import { SolutionsWorkspace, starterFor } from '@/features/code/solutions-workspace';
import { Button } from '@/components/ui/button';
import { Tabs } from '@/components/ui/tabs';
import { WorkspaceLayout } from '@/components/shared/page-header';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';
import { SkeletonText } from '@/components/ui/skeleton';
import { useCreateSnippet, useProblem } from '@/hooks/use-api';
import { routes } from '@/lib/query-keys';
import type { Language } from '@/types/common';

type TabValue = 'code' | 'notes' | 'attempts' | 'revisions';

/**
 * Problem workspace — the single most important screen after Today.
 *
 * Layout follows the study loop left-to-right: read the problem, write code, capture the
 * approach, then ask the tutor on the right when stuck. The AI panel is a sibling of the
 * tab content so its conversation survives tab switches (it is not unmounted by them).
 */
export function ProblemWorkspacePage() {
  const { problemId } = useParams<{ problemId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const problem = useProblem(problemId);
  const createSnippet = useCreateSnippet(problemId ?? '');

  const activeTab = (searchParams.get('tab') as TabValue | null) ?? 'code';
  const [activeSnippetId, setActiveSnippetId] = useState<string | null>(null);
  const [selectedCode, setSelectedCode] = useState<string | null>(null);

  const setTab = useCallback(
    (tab: TabValue) => {
      const next = new URLSearchParams(searchParams);
      next.set('tab', tab);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const snippets = problem.data?.code_snippets ?? [];

  // Default to the primary solution, or the first one available.
  useEffect(() => {
    if (snippets.length === 0) {
      setActiveSnippetId(null);
      return;
    }
    const preferred = snippets.find((snippet) => snippet.is_primary) ?? snippets[0];
    setActiveSnippetId((current) =>
      current && snippets.some((snippet) => snippet.id === current) ? current : (preferred?.id ?? null),
    );
  }, [snippets]);

  const defaultLanguage = useMemo<Language>(() => 'python', []);

  const handleCreateSnippet = async () => {
    if (!problemId) return;
    const created = await createSnippet.mutateAsync({
      code: starterFor(defaultLanguage),
      language: defaultLanguage,
      title: `Solution ${snippets.length + 1}`,
      is_primary: snippets.length === 0,
    });
    setActiveSnippetId(created.id);
  };

  const fullCode = useMemo(
    () => snippets.find((snippet) => snippet.id === activeSnippetId)?.code ?? null,
    [snippets, activeSnippetId],
  );

  if (problem.isLoading) {
    return (
      <div className="mx-auto w-full max-w-[1600px] px-4 py-5 sm:px-6">
        <div className="space-y-3">
          <div className="h-6 w-72 animate-soft-pulse rounded bg-muted" />
          <div className="h-4 w-96 animate-soft-pulse rounded bg-muted" />
          <div className="h-64 animate-soft-pulse rounded-[var(--radius-card)] bg-muted" />
        </div>
      </div>
    );
  }

  if (problem.isError || !problem.data) {
    return (
      <ErrorState
        title="Could not load this problem"
        description="It may have been removed from the catalog, or the request failed."
        onRetry={() => void problem.refetch()}
        className="min-h-[60vh]"
      />
    );
  }

  const data = problem.data;

  return (
    <WorkspaceLayout
      className="h-full"
      aside={
        <AITutorPanel
          contextType="dsa"
          contextId={data.id}
          contextLabel={data.title}
          selectedCode={selectedCode}
          getFullCode={() => fullCode}
          className="h-full"
        />
      }
    >
      <div className="flex h-full min-h-0 flex-col">
        {/* Breadcrumb */}
        <div className="flex shrink-0 items-center gap-2 border-b border-border px-4 py-1.5 sm:px-5">
          <Button asChild variant="subtle" size="sm">
            <Link to={routes.dsa}>
              <ArrowLeft />
              DSA
            </Link>
          </Button>
          <span className="text-[12px] text-subtle-foreground">/</span>
          <span className="truncate text-[12px] text-muted-foreground">{data.primary_topic}</span>
          {data.external_url ? (
            <a
              href={data.external_url}
              target="_blank"
              rel="noreferrer noopener"
              className="ml-auto flex items-center gap-1 text-[12px] text-muted-foreground hover:text-foreground"
            >
              <ExternalLink className="size-3" />
              Original
            </a>
          ) : null}
        </div>

        <ProblemHeader problem={data} />

        <Tabs
          className="shrink-0 px-4 sm:px-5"
          value={activeTab}
          onChange={setTab}
          items={[
            { value: 'code', label: 'Code', hint: snippets.length || undefined },
            { value: 'notes', label: 'Notes' },
            { value: 'attempts', label: 'Attempts', hint: data.attempts.length || undefined },
            { value: 'revisions', label: 'Revision History', hint: data.revisions.length || undefined },
          ]}
        />

        {/* Tab content: a fixed-height scroll region so Monaco and long notes both behave */}
        <div className="min-h-0 flex-1 overflow-y-auto">
          {activeTab === 'code' ? (
            <div className="flex h-full min-h-[32rem] flex-col">
              <SolutionsWorkspace
                problemId={data.id}
                snippets={snippets}
                activeId={activeSnippetId}
                onSelectSnippet={setActiveSnippetId}
                onCreateSnippet={() => void handleCreateSnippet()}
                creating={createSnippet.isPending}
                onSelectionChange={setSelectedCode}
                className="min-h-0 flex-1"
              />
            </div>
          ) : null}

          {activeTab === 'notes' ? (
            <div className="p-4 sm:p-5">
              <div className="mb-4 rounded-[var(--radius-card)] border border-border bg-muted px-3 py-2.5">
                <p className="text-[12px] leading-relaxed text-muted-foreground">
                  Write the approach in your own words. The revision screen surfaces{' '}
                  <span className="font-medium text-foreground">Mistakes</span> first, so that
                  field is worth being specific in.
                </p>
              </div>
              <NotesEditor problemId={data.id} notes={data.notes} className="max-w-3xl" />
            </div>
          ) : null}

          {activeTab === 'attempts' ? (
            <div className="p-4 sm:p-5">
              {data.attempts.length === 0 && data.progress?.attempts === 0 ? (
                <EmptyState
                  compact
                  title="Nothing logged yet"
                  description="Use “Log an attempt” below to record what happened on the first try."
                />
              ) : null}
              <div className="max-w-3xl">
                <AttemptsPanel problemId={data.id} attempts={data.attempts} />
              </div>
            </div>
          ) : null}

          {activeTab === 'revisions' ? (
            <div className="p-4 sm:p-5">
              <div className="max-w-3xl">
                <RevisionHistoryPanel revisions={data.revisions} />
              </div>
            </div>
          ) : null}
        </div>

        {problem.isFetching && !problem.isLoading ? (
          <div className="flex shrink-0 items-center justify-center gap-2 border-t border-border py-1.5 text-[11px] text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            Syncing
          </div>
        ) : null}
      </div>
    </WorkspaceLayout>
  );
}

/** Small helper for the notes tab's loading state. */
export function NotesSkeleton() {
  return <SkeletonText lines={8} className="max-w-3xl" />;
}
