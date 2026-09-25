import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Eraser, Plus, Settings2, Trash2 } from 'lucide-react';

import { CodeEditor } from '@/features/code/code-editor';
import { useAutosave } from '@/features/code/use-autosave';
import { Button } from '@/components/ui/button';
import { Menu as MenuPrimitive, MenuItem, MenuLabel } from '@/components/ui/menu';
import { EmptyState } from '@/components/ui/empty-state';
import { LANGUAGE_OPTIONS, languageLabel } from '@/lib/constants';
import { cn } from '@/lib/utils';
import { useDeleteSnippet, useUpdateSnippet } from '@/hooks/use-api';
import type { CodeSnippet } from '@/types/dsa';
import type { Language } from '@/types/common';

/**
 * Multi-solution code workspace: tabs per saved solution, Monaco for writing, autosave to
 * the API. Code is stored as raw text — nothing here compiles or executes it.
 */
export function SolutionsWorkspace({
  problemId,
  snippets,
  activeId,
  onSelectSnippet,
  onCreateSnippet,
  creating = false,
  onSelectionChange,
  className,
}: {
  problemId: string;
  snippets: CodeSnippet[];
  activeId: string | null;
  onSelectSnippet: (snippetId: string) => void;
  onCreateSnippet: () => void;
  creating?: boolean;
  onSelectionChange?: (selected: string) => void;
  className?: string;
}) {
  const updateSnippet = useUpdateSnippet(problemId);
  const deleteSnippet = useDeleteSnippet(problemId);

  const active = useMemo(
    () => snippets.find((snippet) => snippet.id === activeId) ?? snippets[0] ?? null,
    [snippets, activeId],
  );

  if (snippets.length === 0) {
    return (
      <EmptyState
        className={className}
        icon={<Plus className="size-4" />}
        title="No solution saved yet"
        description="Save your approach for this problem. You can keep several versions — a brute force and an optimised one, for example."
        action={
          <Button variant="primary" size="sm" onClick={onCreateSnippet} loading={creating}>
            <Plus />
            New solution
          </Button>
        }
      />
    );
  }

  return (
    <div className={cn('flex min-h-0 flex-1 flex-col', className)}>
      {/* Solution tabs */}
      <div className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-border px-1 py-1.5">
        {snippets.map((snippet) => (
          <div
            key={snippet.id}
            className={cn(
              'group flex shrink-0 items-center gap-1 rounded-[var(--radius-control)] px-2 py-1 text-[13px] transition-colors',
              active?.id === snippet.id
                ? 'bg-primary-soft text-primary'
                : 'text-muted-foreground hover:bg-accent hover:text-foreground',
            )}
          >
            <button
              type="button"
              onClick={() => onSelectSnippet(snippet.id)}
              className="max-w-40 truncate font-medium"
              title={`${snippet.title ?? 'Solution'} · ${languageLabel(snippet.language)}`}
            >
              {snippet.title ?? 'Solution'}
            </button>
            <span className="text-[11px] opacity-60">{languageLabel(snippet.language)}</span>
            {snippet.is_primary ? (
              <span className="rounded bg-surface px-1 text-[10px] text-subtle-foreground">primary</span>
            ) : null}
          </div>
        ))}
        <Button
          variant="ghost"
          size="icon-sm"
          onClick={onCreateSnippet}
          loading={creating}
          aria-label="Add another solution"
          className="shrink-0"
        >
          <Plus />
        </Button>
      </div>

      {active ? (
        <SnippetEditor
          key={active.id}
          snippet={active}
          onSelectionChange={onSelectionChange}
          onMetaChange={(payload) => updateSnippet.mutate({ snippetId: active.id, payload })}
          onDelete={() => {
            deleteSnippet.mutate(active.id);
          }}
          isDeleting={deleteSnippet.isPending}
        />
      ) : null}
    </div>
  );
}

/** One snippet: toolbar, Monaco and the autosave status bar. */
function SnippetEditor({
  snippet,
  onMetaChange,
  onDelete,
  isDeleting,
  onSelectionChange,
}: {
  snippet: CodeSnippet;
  onMetaChange: (payload: { code?: string; title?: string; language?: string; is_primary?: boolean }) => void;
  onDelete: () => void;
  isDeleting: boolean;
  onSelectionChange?: (selected: string) => void;
}) {
  // Persisting through the mutation keeps the cache patched in place (no refetch flash).
  const save = useStableSave(onMetaChange);

  const autosave = useAutosave(snippet.code, async (code) => {
    await save({ code });
  });

  // Renaming is a separate, explicit action — autosaving a text field the user is still
  // typing in produces nonsense titles.
  const [titleDraft, setTitleDraft] = useState(snippet.title ?? 'Solution');
  const [editingTitle, setEditingTitle] = useState(false);
  const titleInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setTitleDraft(snippet.title ?? 'Solution');
  }, [snippet.id, snippet.title]);

  useEffect(() => {
    if (editingTitle) titleInputRef.current?.select();
  }, [editingTitle]);

  const commitTitle = () => {
    setEditingTitle(false);
    const next = titleDraft.trim() || 'Solution';
    if (next !== snippet.title) onMetaChange({ title: next });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Toolbar */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-3 py-2">
        {editingTitle ? (
          <input
            ref={titleInputRef}
            value={titleDraft}
            onChange={(event) => setTitleDraft(event.target.value)}
            onBlur={commitTitle}
            onKeyDown={(event) => {
              if (event.key === 'Enter') commitTitle();
              if (event.key === 'Escape') {
                setTitleDraft(snippet.title ?? 'Solution');
                setEditingTitle(false);
              }
            }}
            aria-label="Solution name"
            className="h-7 w-48 rounded border border-border bg-surface px-2 text-[13px] outline-none focus:border-primary"
          />
        ) : (
          <button
            type="button"
            onClick={() => setEditingTitle(true)}
            className="rounded px-1.5 py-0.5 text-[13px] font-medium transition-colors hover:bg-accent"
            title="Rename this solution"
          >
            {snippet.title ?? 'Solution'}
          </button>
        )}

        <div className="ml-auto flex items-center gap-1.5">
          <MenuPrimitive
            label="Language"
            trigger={({ toggle, open }) => (
              <Button variant="ghost" size="sm" onClick={toggle} aria-expanded={open}>
                <Settings2 />
                {languageLabel(snippet.language)}
              </Button>
            )}
          >
            {({ close }) => (
              <>
                <MenuLabel>Language</MenuLabel>
                {LANGUAGE_OPTIONS.map((option) => (
                  <MenuItem
                    key={option.value}
                    selected={option.value === snippet.language}
                    onClick={() => {
                      onMetaChange({ language: option.value });
                      close();
                    }}
                  >
                    {option.label}
                  </MenuItem>
                ))}
              </>
            )}
          </MenuPrimitive>

          {!snippet.is_primary ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onMetaChange({ is_primary: true })}
              title="Mark as the primary solution for this problem"
            >
              Make primary
            </Button>
          ) : null}

          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              const starter =
                LANGUAGE_OPTIONS.find((option) => option.value === snippet.language)?.starter ?? '';
              if (!starter) {
                toast.info('No starter snippet for this language');
                return;
              }
              autosave.setValue(starter);
              void autosave.flush();
            }}
            title="Replace with a starter template"
          >
            <Eraser />
            Reset
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={onDelete}
            loading={isDeleting}
            className="text-danger hover:bg-danger-soft"
            title="Delete this solution"
          >
            <Trash2 />
          </Button>
        </div>
      </div>

      <CodeEditor
        className="min-h-0 flex-1 rounded-none border-0"
        value={autosave.value}
        onChange={autosave.setValue}
        language={snippet.language}
        saveState={autosave.status}
        lastSavedAt={autosave.lastSavedAt ?? snippet.updated_at}
        onSelectionChange={onSelectionChange}
        height="100%"
      />

      <p className="shrink-0 border-t border-border px-3 py-1 text-[11px] text-subtle-foreground">
        Stored as plain text for your own reference — InterviewReady never compiles or runs your
        code.
      </p>
    </div>
  );
}

/** Stable wrapper so the autosave callback identity does not change every render. */
function useStableSave(
  onMetaChange: (payload: { code?: string; title?: string; language?: string; is_primary?: boolean }) => void,
): (payload: { code?: string }) => Promise<void> {
  const ref = useRef(onMetaChange);
  ref.current = onMetaChange;

  return useCallback(async (payload: { code?: string }) => {
    ref.current(payload);
  }, []);
}

/** Small helper for the "new solution" starter body. */
export function starterFor(language: Language): string {
  return LANGUAGE_OPTIONS.find((option) => option.value === language)?.starter ?? '';
}
