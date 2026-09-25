import { useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Layers, ListChecks, Plus } from 'lucide-react';

import { AITutorPanel } from '@/features/ai/ai-tutor-panel';
import { CodeEditor } from '@/features/code/code-editor';
import { useAutosave } from '@/features/code/use-autosave';
import { DesignWorkspaceShell, ReferenceCard } from '@/features/shared/design-workspace-shell';
import { TopicNotesEditor, type NoteSectionSpec } from '@/features/shared/topic-notes-editor';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';
import { Tabs } from '@/components/ui/tabs';
import { WorkspaceLayout } from '@/components/shared/page-header';
import {
  useCreateHldSnippet,
  useHldTopic,
  useSaveHldNotes,
  useUpdateHldProgress,
  useUpdateHldSnippet,
} from '@/hooks/use-api';
import { useStudyTimer } from '@/hooks/use-study-timer';
import { HLD_EXTRA_SECTIONS, HLD_NOTE_SECTIONS } from '@/types/hld';
import { languageLabel } from '@/lib/constants';
import { routes } from '@/lib/query-keys';
import type { HLDNotes } from '@/types/hld';

type TabValue = 'requirements' | 'design' | 'diagram' | 'notes';

const SECTION_PLACEHOLDERS: Record<string, { placeholder: string; rows: number; hint?: string }> = {
  functional_requirements: {
    placeholder:
      'Who uses this, and what must it do? List the behaviours as bullet points, and note what is explicitly out of scope.',
    rows: 6,
    hint: 'Naming what you will not build is as important as naming what you will.',
  },
  non_functional_requirements: {
    placeholder:
      'Availability, latency targets, consistency, durability, cost. Give numbers where you can — "p99 under 200 ms" beats "fast".',
    rows: 5,
  },
  capacity_estimation: {
    placeholder:
      'Daily active users → requests per second → storage per year → bandwidth. Show the arithmetic, even roughly.',
    rows: 5,
    hint: 'Back-of-envelope numbers drive every later decision, so write them down.',
  },
  apis: {
    placeholder:
      'The handful of endpoints that matter, with methods, paths and the fields that carry the semantics.',
    rows: 6,
  },
  data_model: {
    placeholder:
      'Entities, key fields, and the access patterns each one must serve. Call out the primary key and any hot partitions.',
    rows: 6,
  },
  database_choice: {
    placeholder:
      'SQL or NoSQL, and why. Name the specific trade-off you are accepting (joins vs. denormalised reads).',
    rows: 4,
  },
  high_level_architecture: {
    placeholder:
      'Client → gateway → services → datastore. Describe the boxes and the arrows, and what each component owns.',
    rows: 7,
  },
  caching: {
    placeholder:
      'What is cached, where (CDN, app, Redis), the eviction policy, and how invalidation works.',
    rows: 4,
  },
  queues: {
    placeholder:
      'Which work is asynchronous, the delivery guarantee, and what happens to a poison message.',
    rows: 4,
  },
  scaling: {
    placeholder:
      'How each tier grows: stateless service replicas, read replicas, sharding key, partitioning.',
    rows: 5,
  },
  failure_handling: {
    placeholder:
      'What breaks first under load, and what the system does about it — retries, circuit breakers, graceful degradation.',
    rows: 4,
  },
  tradeoffs: {
    placeholder:
      'The decisions you would revisit with more time, and what you gave up to get here.',
    rows: 4,
    hint: 'Interviewers remember candidates who can name their own weak points.',
  },
  final_notes: {
    placeholder: 'The summary you would give in the last two minutes of the interview.',
    rows: 3,
  },
  interview_notes: {
    placeholder: 'How the conversation went: what was asked, what you were pushed on.',
    rows: 4,
  },
  mistakes: {
    placeholder: 'What you missed, and what you would do differently next time.',
    rows: 3,
  },
};

const DIAGRAM_STARTER = `# Architecture sketch
#
#   Client
#     |
#   API Gateway
#     |
#   +-------------+-------------+
#   |             |             |
# Service A   Service B      Service C
#   |             |             |
#   +------- Data store --------+
#                 |
#            Cache / Queue
#
# Use plain text here. Boxes and arrows are enough — the words matter more.
`;

/** The numbered sections carry an index; the extras do not. */
const NUMBERED_SECTIONS: NoteSectionSpec[] = HLD_NOTE_SECTIONS.map((section) => ({
  key: section.key,
  label: `${section.index}. ${section.label}`,
  placeholder: SECTION_PLACEHOLDERS[section.key]?.placeholder ?? '',
  hint: SECTION_PLACEHOLDERS[section.key]?.hint,
  rows: SECTION_PLACEHOLDERS[section.key]?.rows ?? 4,
}));

const EXTRA_SECTIONS: NoteSectionSpec[] = HLD_EXTRA_SECTIONS.map((section) => ({
  key: section.key,
  label: section.label,
  placeholder: SECTION_PLACEHOLDERS[section.key]?.placeholder ?? '',
  hint: SECTION_PLACEHOLDERS[section.key]?.hint,
  rows: SECTION_PLACEHOLDERS[section.key]?.rows ?? 4,
}));

const ALL_SECTIONS = [...NUMBERED_SECTIONS, ...EXTRA_SECTIONS];

/** Reads one section from an `HLDNotes` row, narrowing the key to a known section. */
function readNote(notes: HLDNotes | null, key: string): string | null {
  if (!notes) return null;
  return (notes as unknown as Record<string, string | null>)[key] ?? null;
}

/**
 * HLD workspace: a structured design document with a diagram canvas.
 *
 * The numbered sections exist so a half-finished design is visible as a half-finished
 * design. Free-form notes let you skip the awkward parts without noticing; a numbered list
 * with empty boxes does not.
 */
export function HldWorkspacePage() {
  const { topicId } = useParams<{ topicId: string }>();
  const topic = useHldTopic(topicId);
  const updateProgress = useUpdateHldProgress();
  const saveNotes = useSaveHldNotes(topicId ?? '');
  const createSnippet = useCreateHldSnippet(topicId ?? '');
  const timer = useStudyTimer();

  const [tab, setTab] = useState<TabValue>('design');
  const [selectedCode, setSelectedCode] = useState<string | null>(null);

  const data = topic.data;
  const diagram = useMemo(
    () => data?.code_snippets.find((snippet) => snippet.title === 'Architecture diagram') ?? data?.code_snippets[0] ?? null,
    [data],
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
        title="Could not load this system"
        description="It may have been removed from the curriculum, or the request failed."
        onRetry={() => void topic.refetch()}
        className="min-h-[60vh]"
      />
    );
  }

  /**
   * `HLDNotes` has no index signature, so the generic editor reads through this helper
   * rather than indexing the object with an arbitrary string.
   */
  const noteValues: Record<string, string | null> = Object.fromEntries(
    ALL_SECTIONS.map((section) => [section.key, readNote(data.notes, section.key)]),
  );

  const writtenSections = NUMBERED_SECTIONS.filter(
    (section) => (noteValues[section.key] ?? '').trim().length > 0,
  ).length;

  const requirementsSections = NUMBERED_SECTIONS.slice(0, 3);
  const designSections = NUMBERED_SECTIONS.slice(3);

  return (
    <WorkspaceLayout
      className="h-full"
      aside={
        <AITutorPanel
          contextType="hld"
          contextId={data.id}
          contextLabel={data.title}
          selectedCode={selectedCode}
          getFullCode={() => diagram?.code ?? null}
          className="h-full"
        />
      }
    >
      <DesignWorkspaceShell
        className="h-full"
        backHref={routes.hld}
        backLabel="HLD"
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
          start: () => void timer.start('hld', data.id),
          stop: () => void timer.stop(),
        }}
      >
        <Tabs
          className="shrink-0 px-4 sm:px-5"
          value={tab}
          onChange={setTab}
          items={[
            { value: 'requirements', label: 'Requirements', hint: 3 },
            {
              value: 'design',
              label: 'Design Document',
              hint: `${writtenSections}/${NUMBERED_SECTIONS.length}`,
            },
            { value: 'diagram', label: 'Diagram' },
            { value: 'notes', label: 'Interview Notes' },
          ]}
        />

        <div className="min-h-0 flex-1 overflow-y-auto">
          {tab === 'requirements' ? (
            <div className="grid gap-4 p-4 sm:p-5 lg:grid-cols-[minmax(0,1fr)_18rem]">
              <TopicNotesEditor
                entityId={`${data.id}-requirements`}
                title="Scope the problem first"
                description="Requirements and capacity decide the architecture. Do these before drawing anything."
                sections={requirementsSections}
                values={noteValues}
                onSave={(payload) => saveNotes.mutateAsync(payload)}
              />

              <div className="space-y-4">
                {data.key_concepts.length > 0 ? (
                  <Card padding="md" className="space-y-2">
                    <h2 className="flex items-center gap-1.5 text-[13px] font-semibold">
                      <Layers className="size-3.5" />
                      Key concepts
                    </h2>
                    <div className="flex flex-wrap gap-1.5">
                      {data.key_concepts.map((concept) => (
                        <Badge key={concept} tone="outline" size="sm" className="font-normal">
                          {concept}
                        </Badge>
                      ))}
                    </div>
                  </Card>
                ) : null}

                {data.learning_objectives.length > 0 ? (
                  <ReferenceCard title="You should be able to" items={data.learning_objectives} />
                ) : null}
              </div>
            </div>
          ) : null}

          {tab === 'design' ? (
            <div className="p-4 sm:p-5">
              <TopicNotesEditor
                entityId={data.id}
                title="Design document"
                description="Sections 4 to 13 of the design narrative. Autosaves as you type."
                sections={designSections}
                values={noteValues}
                onSave={(payload) => saveNotes.mutateAsync(payload)}
              />
            </div>
          ) : null}

          {tab === 'diagram' ? (
            <div className="flex h-full min-h-[30rem] flex-col">
              {diagram ? (
                <DiagramEditor
                  key={diagram.id}
                  topicId={data.id}
                  snippetId={diagram.id}
                  initialCode={diagram.code}
                  language={diagram.language}
                  onSelectionChange={setSelectedCode}
                />
              ) : (
                <EmptyState
                  className="m-4"
                  icon={<Layers className="size-4" />}
                  title="No diagram yet"
                  description="Sketch the boxes and arrows as plain text. The structure is what is being assessed, not the rendering."
                  action={
                    <Button
                      variant="primary"
                      size="sm"
                      loading={createSnippet.isPending}
                      onClick={() =>
                        createSnippet.mutate({
                          code: DIAGRAM_STARTER,
                          language: 'other',
                          title: 'Architecture diagram',
                        })
                      }
                    >
                      <Plus />
                      Start a diagram
                    </Button>
                  }
                />
              )}
            </div>
          ) : null}

          {tab === 'notes' ? (
            <div className="grid gap-4 p-4 sm:p-5 lg:grid-cols-[minmax(0,1fr)_18rem]">
              <TopicNotesEditor
                entityId={`${data.id}-interview`}
                title="Interview notes"
                description="How the conversation went, and what you would change."
                sections={EXTRA_SECTIONS}
                values={noteValues}
                onSave={(payload) => saveNotes.mutateAsync(payload)}
              />

              <Card padding="md" className="space-y-2 self-start">
                <h2 className="flex items-center gap-1.5 text-[13px] font-semibold">
                  <ListChecks className="size-3.5" />
                  Section checklist
                </h2>
                <ul className="space-y-1">
                  {NUMBERED_SECTIONS.map((section) => {
                    const filled = (noteValues[section.key] ?? '').trim().length > 0;
                    return (
                      <li key={section.key} className="flex items-center gap-2 text-[12px]">
                        <span
                          aria-hidden
                          className={`size-1.5 shrink-0 rounded-full ${filled ? 'bg-success' : 'bg-border'}`}
                        />
                        <span className={filled ? 'text-muted-foreground' : 'text-subtle-foreground'}>
                          {section.label}
                        </span>
                      </li>
                    );
                  })}
                </ul>
                <p className="pt-1 text-[11px] text-subtle-foreground">
                  Missing sections are what an interviewer will probe first.
                </p>
              </Card>
            </div>
          ) : null}
        </div>

        {data.code_snippets.length > 1 ? (
          <div className="shrink-0 border-t border-border px-4 py-2 sm:px-5">
            <div className="flex flex-wrap items-center gap-1.5">
              {data.code_snippets.map((snippet) => (
                <span
                  key={snippet.id}
                  className="rounded-[var(--radius-control)] px-2 py-1 text-[12px] text-muted-foreground"
                >
                  {snippet.title ?? languageLabel(snippet.language)}
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </DesignWorkspaceShell>
    </WorkspaceLayout>
  );
}

/** Monaco plus autosave for the architecture diagram. */
function DiagramEditor({
  topicId,
  snippetId,
  initialCode,
  language,
  onSelectionChange,
}: {
  topicId: string;
  snippetId: string;
  initialCode: string;
  language: string;
  onSelectionChange: (selected: string) => void;
}) {
  const updateSnippet = useUpdateHldSnippet(topicId);

  const autosave = useAutosave(initialCode, async (code) => {
    await updateSnippet.mutateAsync({ snippetId, payload: { code } });
  });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-4 py-2 sm:px-5">
        <span className="text-[12px] text-muted-foreground">
          Plain-text diagram · edits save automatically
        </span>
        <span className="tabular ml-auto text-[11px] text-subtle-foreground">
          {autosave.status === 'saving'
            ? 'Saving…'
            : autosave.isDirty
              ? 'Unsaved'
              : autosave.lastSavedAt
                ? 'Saved'
                : ''}
        </span>
      </div>
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
