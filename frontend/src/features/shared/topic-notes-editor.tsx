import { useEffect, useMemo } from 'react';

import { Field, Textarea } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { useAutosave } from '@/features/code/use-autosave';
import { cn } from '@/lib/utils';

export interface NoteSectionSpec {
  key: string;
  label: string;
  placeholder: string;
  hint?: string;
  rows: number;
  /** Renders a one-line input instead of a textarea. */
  single?: boolean;
}

/**
 * The structured notes document used by both design workspaces.
 *
 * Sections are declared as data and rendered generically, and the whole document is saved
 * as one debounced unit. A field-per-hook design would fire a request per keystroke across
 * thirteen fields; this issues exactly one save per pause.
 */
export function TopicNotesEditor({
  entityId,
  sections,
  values,
  onSave,
  title = 'Design document',
  description,
  className,
}: {
  /** Problem/topic id — a change re-baselines the draft. */
  entityId: string;
  sections: readonly NoteSectionSpec[];
  /** Current persisted values, keyed by section key. */
  values: Record<string, string | null>;
  onSave: (payload: Record<string, string>) => Promise<unknown>;
  title?: string;
  description?: string;
  className?: string;
}) {
  const baseline = useMemo(() => {
    const result: Record<string, string> = {};
    sections.forEach((section) => {
      result[section.key] = values[section.key] ?? '';
    });
    return result;
  }, [sections, values]);

  const serialised = JSON.stringify(baseline);
  const savedSerialised = serialised;

  const autosave = useAutosave(
    savedSerialised,
    async (value) => {
      await onSave(JSON.parse(value) as Record<string, string>);
    },
    { delayMs: 1100 },
  );

  // Re-baseline when a different topic is opened.
  useEffect(() => {
    autosave.setValue(serialised);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityId]);

  // Push every local change into the debounced saver.
  useEffect(() => {
    autosave.setValue(serialised);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serialised]);

  const draft = useMemo(
    () => JSON.parse(autosave.value) as Record<string, string>,
    [autosave.value],
  );

  const update = (key: string, value: string) => {
    autosave.setValue(JSON.stringify({ ...draft, [key]: value }));
  };

  const dirty = autosave.isDirty;
  const written = sections.filter((section) => (draft[section.key] ?? '').trim().length > 0).length;

  return (
    <Card padding="none" className={cn('overflow-hidden', className)}>
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">{title}</h2>
          {description ? (
            <p className="mt-0.5 text-[12px] text-muted-foreground">{description}</p>
          ) : null}
        </div>

        <div className="flex items-center gap-3">
          <span className="text-[12px] text-subtle-foreground">
            {written} / {sections.length} sections written
          </span>
          <span
            className={cn(
              'text-[12px]',
              autosave.status === 'error' ? 'text-danger' : 'text-muted-foreground',
            )}
            aria-live="polite"
          >
            {autosave.status === 'saving'
              ? 'Saving…'
              : dirty
                ? 'Unsaved changes'
                : autosave.lastSavedAt
                  ? 'Saved'
                  : 'Autosaves as you type'}
          </span>
          <Button
            variant="secondary"
            size="sm"
            disabled={!dirty || autosave.status === 'saving'}
            onClick={() => void autosave.flush()}
          >
            Save now
          </Button>
        </div>
      </header>

      <div className="divide-y divide-border">
        {sections.map((section) => (
          <Field
            key={section.key}
            label={section.label}
            hint={section.hint}
            className="px-4 py-3.5"
            htmlFor={`note-${section.key}`}
          >
            {section.single ? (
              <Textarea
                id={`note-${section.key}`}
                rows={1}
                value={draft[section.key] ?? ''}
                onChange={(event) => update(section.key, event.target.value)}
                placeholder={section.placeholder}
                className="resize-none"
              />
            ) : (
              <Textarea
                id={`note-${section.key}`}
                rows={section.rows}
                value={draft[section.key] ?? ''}
                onChange={(event) => update(section.key, event.target.value)}
                placeholder={section.placeholder}
              />
            )}
          </Field>
        ))}
      </div>
    </Card>
  );
}
