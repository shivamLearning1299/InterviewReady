import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { FileCode2, Lightbulb, Plus } from 'lucide-react';

import { AITutorPanel } from '@/features/ai/ai-tutor-panel';
import { CodeEditor } from '@/features/code/code-editor';
import { useAutosave } from '@/features/code/use-autosave';
import { DesignWorkspaceShell, ReferenceCard } from '@/features/shared/design-workspace-shell';
import { TopicNotesEditor, type NoteSectionSpec } from '@/features/shared/topic-notes-editor';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';
import { Badge } from '@/components/ui/badge';
import { Tabs } from '@/components/ui/tabs';
import { WorkspaceLayout } from '@/components/shared/page-header';
import {
  useCreateLldSnippet,
  useLldTopic,
  useSaveLldNotes,
  useUpdateLldProgress,
  useUpdateLldSnippet,
} from '@/hooks/use-api';
import { useStudyTimer } from '@/hooks/use-study-timer';
import { LANGUAGE_OPTIONS, languageLabel } from '@/lib/constants';
import { routes } from '@/lib/query-keys';
import type { Language } from '@/types/common';
import type { LLDNotes, LLDTopicDetail } from '@/types/lld';

type TabValue = 'description' | 'notes' | 'implementation';

/** Reads one section from an `LLDNotes` row, which has no index signature of its own. */
function readNote(notes: LLDNotes | null, key: string): string | null {
  if (!notes) return null;
  return (notes as unknown as Record<string, string | null>)[key] ?? null;
}

const STARTER: Record<string, string> = {
  python: `class Solution:\n    """Outline the classes, responsibilities and collaborations here."""\n\n    def __init__(self) -> None:\n        pass\n`,
  java: `// Outline the classes, responsibilities and collaborations here.\npublic class Solution {\n\n}\n`,
  cpp: `// Outline the classes, responsibilities and collaborations here.\nclass Solution {\n\n};\n`,
  typescript: `// Outline the classes, responsibilities and collaborations here.\nclass Solution {}\n`,
};

/**
 * The LLD sections, widened to the generic editor's shape.
 *
 * `LLD_NOTE_SECTIONS` is a `const` tuple, so its entries are missing `placeholder` and
 * `rows` — both are supplied here rather than at each call site.
 */
const LLD_SECTIONS: NoteSectionSpec[] = [
  {
    key: 'summary',
    label: 'Description',
    placeholder: 'Restate the problem in your own words: inputs, outputs, and what is out of scope.',
    rows: 5,
  },
  {
    key: 'design_explanation',
    label: 'Design Explanation',
    placeholder: 'The overall shape of the design, and why it decomposes this way.',
    rows: 6,
    hint: 'A reviewer should be able to follow this without seeing the code.',
  },
  {
    key: 'class_responsibilities',
    label: 'Entities & Responsibilities',
    placeholder:
      'One line per class: its name and the single job it owns. If a class needs "and", it probably wants splitting.',
    rows: 7,
  },
  {
    key: 'relationships',
    label: 'Relationships',
    placeholder:
      'How the entities connect — composition, inheritance, aggregation. Note the direction of each dependency.',
    rows: 5,
  },
  {
    key: 'design_notes',
    label: 'Design Notes',
    placeholder: 'Extensibility, the pattern you reached for, and where you knowingly simplified.',
    rows: 5,
  },
  {
    key: 'mistakes',
    label: 'Mistakes',
    placeholder: 'What you got wrong the first time, and what a reviewer pushed back on.',
    rows: 4,
  },
  {
    key: 'revision_notes',
    label: 'Revision Notes',
    placeholder: 'What to re-derive from scratch next time, and what to check.',
    rows: 3,
  },
];

/**
 * LLD workspace: read the prompt, write the design, keep the implementation.
 *
 * The three tabs follow the order of an interview answer — restate the problem, agree the
 * entities, then write code. The AI panel offers design-specific actions rather than DSA
 * hints.
 */
export function LldWorkspacePage() {
  const { topicId } = useParams<{ topicId: string }>();
  const topic = useLldTopic(topicId);
  const updateProgress = useUpdateLldProgress();
  const saveNotes = useSaveLldNotes(topicId ?? '');
  const createSnippet = useCreateLldSnippet(topicId ?? '');
  const timer = useStudyTimer();

  const [tab, setTab] = useState<TabValue>('description');
  const [language, setLanguage] = useState<Language>('python');
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [activeSnippetId, setActiveSnippetId] = useState<string | null>(null);

  const data: LLDTopicDetail | undefined = topic.data;
  const snippets = useMemo(() => data?.code_snippets ?? [], [data]);

  useEffect(() => {
    if (snippets.length === 0) {
      setActiveSnippetId(null);
      return;
    }
    const preferred = snippets.find((snippet) => snippet.is_primary) ?? snippets[0];
    setActiveSnippetId((current) =>
      current && snippets.some((snippet) => snippet.id === current)
        ? current
        : (preferred?.id ?? null),
    );
  }, [snippets]);

  const activeSnippet = useMemo(
    () => snippets.find((snippet) => snippet.id === activeSnippetId) ?? snippets[0] ?? null,
    [snippets, activeSnippetId],
  );

  if (topic.isLoading) {
    return (
      <div className="mx-auto w-full max-w-[1600px] space-y-3 px-4 py-5 sm:px-6">
        <div className="h-6 w-72 animate-soft-pulse rounded bg-muted" />
        <div className="h-10 w-full animate-soft-pulse rounded bg-muted" />
        <div className="h-64 animate-soft-pulse rounded-[var(--radius-card)] bg-muted" />
      </div>
    );
  }

  if (topic.isError || !data) {
    return (
      <ErrorState
        title="Could not load this topic"
        description="It may have been removed from the curriculum, or the request failed."
        onRetry={() => void topic.refetch()}
        className="min-h-[60vh]"
      />
    );
  }

  const noteValues: Record<string, string | null> = Object.fromEntries(
    LLD_SECTIONS.map((section) => [section.key, readNote(data.notes, section.key)]),
  );

  return (
    <WorkspaceLayout
      className="h-full"
      aside={
        <AITutorPanel
          contextType="lld"
          contextId={data.id}
          contextLabel={data.title}
          selectedCode={selectedCode}
          getFullCode={() => activeSnippet?.code ?? null}
          className="h-full"
        />
      }
    >
      <DesignWorkspaceShell
        className="h-full"
        backHref={routes.lld}
        backLabel="LLD"
        title={data.title}
        subtitle={data.description}
        externalUrl={data.external_url}
        difficulty={data.difficulty}
        progress={data.progress}
        isSaving={updateProgress.isPending}
        onStatusChange={(status) =>
          updateProgress.mutate({
            topicId: data.id,
            payload: { status, schedule_revision: status === 'needs_revision' },
          })
        }
        onConfidenceChange={(confidence) =>
          updateProgress.mutate({ topicId: data.id, payload: { confidence } })
        }
        timer={{
          elapsedSeconds: timer.elapsedSeconds,
          isRunning: timer.isRunning,
          start: () => void timer.start('lld', data.id),
          stop: () => void timer.stop(),
        }}
      >
        <Tabs
          className="shrink-0 px-4 sm:px-5"
          value={tab}
          onChange={setTab}
          items={[
            { value: 'description', label: 'Description' },
            { value: 'notes', label: 'Design Notes' },
            {
              value: 'implementation',
              label: 'Implementation',
              hint: snippets.length || undefined,
            },
          ]}
        />

        <div className="min-h-0 flex-1 overflow-y-auto">
          {tab === 'description' ? (
            <div className="grid gap-4 p-4 sm:p-5 lg:grid-cols-[minmax(0,1fr)_18rem]">
              <div className="space-y-4">
                <Card padding="md" className="space-y-3">
                  <h2 className="text-sm font-semibold">What to design</h2>
                  <p className="text-[13px] leading-relaxed whitespace-pre-wrap text-muted-foreground">
                    {data.description ??
                      'No prompt has been written for this topic yet. Add one from the admin tools, or use the notes tab to capture it yourself.'}
                  </p>
                </Card>

                {data.learning_objectives.length > 0 ? (
                  <ReferenceCard
                    title="You should be able to"
                    items={data.learning_objectives}
                  />
                ) : null}

                {data.notes?.summary ? (
                  <Card padding="md" className="space-y-2">
                    <h2 className="text-sm font-semibold">Your summary</h2>
                    <p className="text-[13px] leading-relaxed whitespace-pre-wrap text-muted-foreground">
                      {data.notes.summary}
                    </p>
                  </Card>
                ) : null}
              </div>

              <div className="space-y-4">
                {data.key_concepts.length > 0 ? (
                  <Card padding="md" className="space-y-2">
                    <h2 className="text-[13px] font-semibold">Key concepts</h2>
                    <div className="flex flex-wrap gap-1.5">
                      {data.key_concepts.map((concept) => (
                        <Badge key={concept} tone="outline" size="sm" className="font-normal">
                          {concept}
                        </Badge>
                      ))}
                    </div>
                  </Card>
                ) : null}

                {data.notes?.patterns_used && data.notes.patterns_used.length > 0 ? (
                  <Card padding="md" className="space-y-2">
                    <h2 className="text-[13px] font-semibold">Patterns used</h2>
                    <div className="flex flex-wrap gap-1.5">
                      {data.notes.patterns_used.map((pattern) => (
                        <Badge key={pattern} tone="primary" size="sm" className="font-normal">
                          {pattern}
                        </Badge>
                      ))}
                    </div>
                  </Card>
                ) : null}

                <Card padding="md" className="space-y-2">
                  <h2 className="flex items-center gap-1.5 text-[13px] font-semibold">
                    <Lightbulb className="size-3.5" />
                    Interview approach
                  </h2>
                  <ol className="space-y-1.5 text-[12px] text-muted-foreground">
                    <li>1. Restate the requirements and name the inputs and outputs.</li>
                    <li>2. List the entities, then assign one responsibility to each.</li>
                    <li>3. Define the relationships between them.</li>
                    <li>4. Extend it — what would change if a new requirement arrived?</li>
                  </ol>
                </Card>
              </div>
            </div>
          ) : null}

          {tab === 'notes' ? (
            <div className="p-4 sm:p-5">
              <TopicNotesEditor
                entityId={data.id}
                title="Design document"
                description="Autosaves as you type. Mistakes and revision notes are what the revision screen reads."
                sections={LLD_SECTIONS}
                values={noteValues}
                onSave={(payload) => saveNotes.mutateAsync(payload)}
              />
            </div>
          ) : null}

          {tab === 'implementation' ? (
            <div className="flex h-full min-h-[30rem] flex-col">
              {activeSnippet ? (
                <ImplementationEditor
                  key={activeSnippet.id}
                  topicId={data.id}
                  snippetId={activeSnippet.id}
                  initialCode={activeSnippet.code}
                  language={activeSnippet.language}
                  onSelectionChange={setSelectedCode}
                />
              ) : (
                <EmptyState
                  className="m-4"
                  icon={<FileCode2 className="size-4" />}
                  title="No implementation yet"
                  description="Write the class skeleton once the design is settled — the code is the least important part of an LLD answer, but having it proves the design compiles."
                  action={
                    <div className="flex flex-wrap items-center justify-center gap-2">
                      <select
                        value={language}
                        onChange={(event) => setLanguage(event.target.value as Language)}
                        aria-label="Language"
                        className="h-8 rounded-[var(--radius-control)] border border-border bg-surface px-2 text-[13px]"
                      >
                        {LANGUAGE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <Button
                        variant="primary"
                        size="sm"
                        loading={createSnippet.isPending}
                        onClick={() =>
                          createSnippet.mutate({
                            code: STARTER[language] ?? '// Design skeleton\n',
                            language,
                            title: `${languageLabel(language)} implementation`,
                          })
                        }
                      >
                        <Plus />
                        Start implementation
                      </Button>
                    </div>
                  }
                />
              )}
            </div>
          ) : null}
        </div>

        {snippets.length > 1 ? (
          <div className="shrink-0 border-t border-border px-4 py-2 sm:px-5">
            <div className="flex flex-wrap items-center gap-1.5">
              {snippets.map((snippet) => (
                <button
                  key={snippet.id}
                  type="button"
                  onClick={() => setActiveSnippetId(snippet.id)}
                  className={`rounded-[var(--radius-control)] px-2 py-1 text-[12px] transition-colors ${
                    snippet.id === activeSnippet?.id
                      ? 'bg-primary-soft text-primary'
                      : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                  }`}
                >
                  {snippet.title ?? languageLabel(snippet.language)}
                </button>
              ))}
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Add another implementation"
                loading={createSnippet.isPending}
                onClick={() =>
                  createSnippet.mutate({
                    code: STARTER[language] ?? '// Design skeleton\n',
                    language,
                    title: `${languageLabel(language)} implementation`,
                  })
                }
              >
                <Plus />
              </Button>
            </div>
          </div>
        ) : null}
      </DesignWorkspaceShell>
    </WorkspaceLayout>
  );
}

/**
 * Monaco plus autosave for one saved implementation.
 *
 * Mounted with a `key` on the snippet id, so switching snippets re-baselines the autosave
 * buffer rather than carrying one snippet's draft into another.
 */
function ImplementationEditor({
  topicId,
  snippetId,  initialCode,
  language,
  onSelectionChange,
}: {
  topicId: string;
  snippetId: string;
  initialCode: string;
  language: string;
  onSelectionChange: (selected: string) => void;
}) {
  const updateSnippet = useUpdateLldSnippet(topicId);

  const autosave = useAutosave(initialCode, async (code) => {
    await updateSnippet.mutateAsync({ snippetId, payload: { code } });
  });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <CodeEditor
        value={autosave.value}
        onChange={autosave.setValue}
        language={language}
        saveState={autosave.status}
        lastSavedAt={autosave.lastSavedAt}
        onSelectionChange={onSelectionChange}
        className="min-h-0 flex-1"
      />
    </div>
  );
}

