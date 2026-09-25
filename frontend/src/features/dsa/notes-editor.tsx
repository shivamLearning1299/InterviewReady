import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { useAutosave } from '@/features/code/use-autosave';
import { Button } from '@/components/ui/button';
import { Textarea, Field } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { useSaveNotes } from '@/hooks/use-api';
import type { ProblemNotes, ProblemNotesUpsert } from '@/types/dsa';

/**
 * The notes document for a problem.
 *
 * Six fields, each with a specific job — approach, complexity, mistakes, learning and
 * revision notes. Splitting them apart is what makes revision useful later: the revision
 * view can surface "Mistakes" without showing the whole write-up.
 */
const SECTIONS: {
  key: keyof ProblemNotesUpsert;
  label: string;
  placeholder: string;
  hint?: string;
  rows: number;
  single?: boolean;
}[] = [
  {
    key: 'approach',
    label: 'My Approach',
    placeholder: 'How did you reason about this? Write it as if explaining to yourself in a month.',
    hint: 'State the invariant or key idea first, then the steps.',
    rows: 6,
  },
  {
    key: 'time_complexity',
    label: 'Time Complexity',
    placeholder: 'O(n)',
    rows: 1,
    single: true,
  },
  {
    key: 'space_complexity',
    label: 'Space Complexity',
    placeholder: 'O(1)',
    rows: 1,
    single: true,
  },
  {
    key: 'mistakes',
    label: 'Mistakes',
    placeholder: 'What went wrong on the first attempt? Which edge case bit you?',
    hint: 'This field is what the revision screen shows first.',
    rows: 4,
  },
  {
    key: 'notes',
    label: 'What I Learned',
    placeholder: 'The transferable lesson — a pattern, a trick, a gotcha.',
    rows: 4,
  },
  {
    key: 'revision_notes',
    label: 'Revision Notes',
    placeholder: 'What to re-derive from scratch next time, and what to check.',
    rows: 3,
  },
];

export function NotesEditor({
  problemId,
  notes,
  className,
}: {
  problemId: string;
  notes: ProblemNotes | null;
  className?: string;
}) {
  const saveNotes = useSaveNotes(problemId);

  const [draft, setDraft] = useState<ProblemNotesUpsert>(() => ({
    approach: notes?.approach ?? '',
    notes: notes?.notes ?? '',
    mistakes: notes?.mistakes ?? '',
    revision_notes: notes?.revision_notes ?? '',
    time_complexity: notes?.time_complexity ?? '',
    space_complexity: notes?.space_complexity ?? '',
  }));

  // Re-baseline when a different problem's notes arrive.
  useEffect(() => {
    setDraft({
      approach: notes?.approach ?? '',
      notes: notes?.notes ?? '',
      mistakes: notes?.mistakes ?? '',
      revision_notes: notes?.revision_notes ?? '',
      time_complexity: notes?.time_complexity ?? '',
      space_complexity: notes?.space_complexity ?? '',
    });
  }, [problemId, notes]);

  // One debounced save for the whole document rather than a hook per field.
  const serialised = useMemo(() => JSON.stringify(draft), [draft]);
  const savedSerialised = useMemo(
    () =>
      JSON.stringify({
        approach: notes?.approach ?? '',
        notes: notes?.notes ?? '',
        mistakes: notes?.mistakes ?? '',
        revision_notes: notes?.revision_notes ?? '',
        time_complexity: notes?.time_complexity ?? '',
        space_complexity: notes?.space_complexity ?? '',
      }),
    [notes],
  );

  const autosave = useAutosave(
    savedSerialised,
    async (value) => {
      const parsed = JSON.parse(value) as ProblemNotesUpsert;
      await saveNotes.mutateAsync(parsed);
    },
    { delayMs: 1100 },
  );

  // Dirty is measured against the last *persisted* document, not against the autosave
  // hook's buffer, so the "Save now" button reflects reality.
  const isDirty = serialised !== savedSerialised;

  // Push the local draft into the autosave hook on every keystroke.
  useEffect(() => {
    autosave.setValue(serialised);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serialised]);

  const update = (key: keyof ProblemNotesUpsert, value: string) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const hasContent = Object.values(draft).some((value) => (value ?? '').trim().length > 0);

  return (
    <div className={cn('space-y-4', className)}>
      <div className="flex items-center justify-between gap-3 rounded-[var(--radius-card)] border border-border bg-muted px-3 py-2">
        <p className="text-[12px] text-muted-foreground">
          {autosave.status === 'saving'
            ? 'Saving…'
            : autosave.status === 'saved'
              ? 'Saved'
              : autosave.status === 'error'
                ? 'Could not save — check your connection'
                : hasContent
                  ? 'Your notes autosave as you type'
                  : 'Nothing written yet'}
        </p>
        <Button
          variant="ghost"
          size="sm"
          disabled={!isDirty}
          onClick={async () => {
            await autosave.flush();
            toast.success('Notes saved');
          }}
        >
          Save now
        </Button>
      </div>

      {SECTIONS.map((section) => (
        <Field
          key={section.key}
          label={section.label}
          hint={section.hint}
          htmlFor={`notes-${section.key}`}
        >
          <Textarea
            id={`notes-${section.key}`}
            value={(draft[section.key] as string | undefined) ?? ''}
            onChange={(event) => update(section.key, event.target.value)}
            placeholder={section.placeholder}
            rows={section.rows}
            className={section.single ? 'h-9 min-h-9 font-mono text-[13px]' : undefined}
          />
        </Field>
      ))}
    </div>
  );
}
