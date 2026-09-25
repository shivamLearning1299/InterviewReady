import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Editor, { type OnMount } from '@monaco-editor/react';
import type { editor } from 'monaco-editor';
import { Check, Loader2 } from 'lucide-react';

import { cn } from '@/lib/utils';
import { monacoLanguage } from '@/lib/constants';
import { useTheme } from '@/providers/theme-provider';
import { formatRelativeTime } from '@/lib/format';

export interface CodeEditorProps {
  value: string;
  onChange: (value: string) => void;
  /** Raw `Language` value from the API; mapped to a Monaco id internally. */
  language: string;
  height?: string | number;
  readOnly?: boolean;
  className?: string;
  /** Autosave feedback surfaced in the status bar. */
  saveState?: 'idle' | 'saving' | 'saved' | 'error';
  lastSavedAt?: string | null;
  /** Called with the highlighted text, so the AI panel can explain a selection. */
  onSelectionChange?: (selected: string) => void;
}

/** Monaco's own themes, mapped onto the app's light/dark tokens. */
const MONACO_LIGHT = 'vs';
const MONACO_DARK = 'vs-dark';

/**
 * Monaco wrapper used for DSA solutions, LLD implementations and HLD diagrams.
 *
 * Code is stored as raw text and never executed — there is no compiler or sandbox here, and
 * that is deliberate. The editor only ever reports text upward; persistence is the
 * caller's responsibility (via the autosave hook).
 */
export function CodeEditor({
  value,
  onChange,
  language,
  height = '100%',
  readOnly = false,
  className,
  saveState = 'idle',
  lastSavedAt,
  onSelectionChange,
}: CodeEditorProps) {
  const { theme } = useTheme();
  const editorRef = useRef<editor.IStandaloneCodeEditor | null>(null);

  const options = useMemo<editor.IStandaloneEditorConstructionOptions>(
    () => ({
      readOnly,
      // A study tool, not a toy: keep the editor quiet and readable.
      minimap: { enabled: false },
      lineNumbers: 'on',
      lineNumbersMinChars: 3,
      glyphMargin: false,
      folding: true,
      fontSize: 13,
      lineHeight: 21,
      fontFamily:
        'ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, "Liberation Mono", monospace',
      fontLigatures: true,
      scrollBeyondLastLine: false,
      renderLineHighlight: 'line',
      smoothScrolling: true,
      cursorBlinking: 'smooth',
      padding: { top: 10, bottom: 10 },
      tabSize: 4,
      insertSpaces: true,
      detectIndentation: false,
      wordWrap: 'on',
      wrappingIndent: 'indent',
      automaticLayout: true,
      scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10 },
      overviewRulerLanes: 0,
      hideCursorInOverviewRuler: true,
      overviewRulerBorder: false,
      bracketPairColorization: { enabled: true },
      contextmenu: true,
      quickSuggestions: false,
      // No language server is attached, so these would only ever produce noise.
      suggestOnTriggerCharacters: false,
      parameterHints: { enabled: false },
      unicodeHighlight: { ambiguousCharacters: false },
    }),
    [readOnly],
  );

  const handleMount: OnMount = useCallback(
    (instance) => {
      editorRef.current = instance;

      // Report the initial selection (usually empty) so the panel can disable
      // "Explain Selected Code" until something is highlighted.
      onSelectionChange?.(instance.getModel()?.getValueInRange(instance.getSelection()!) ?? '');

      instance.onDidChangeCursorSelection(() => {
        const selection = instance.getSelection();
        const model = instance.getModel();
        if (!selection || !model) return;
        const selected = model.getValueInRange(selection);
        // Ignore the trivial one-character selection that a plain click produces.
        onSelectionChange?.(selected.trim().length > 3 ? selected : '');
      });
    },
    [onSelectionChange],
  );

  // Keep the model in sync when the caller switches snippets or languages.
  useEffect(() => {
    const instance = editorRef.current;
    if (!instance) return;
    if (instance.getValue() !== value) {
      instance.setValue(value);
    }
    // Only re-sync on an external change, not on every keystroke.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  return (
    <div className={cn('flex min-h-0 flex-col overflow-hidden rounded-[var(--radius-card)] border border-border', className)}>
      <div className="min-h-0 flex-1" style={{ height }}>
        <Editor
          height="100%"
          language={monacoLanguage(language)}
          value={value}
          onChange={(next) => onChange(next ?? '')}
          onMount={handleMount}
          theme={theme === 'dark' ? MONACO_DARK : MONACO_LIGHT}
          options={options}
          loading={<EditorPlaceholder />}
        />
      </div>

      <div className="flex shrink-0 items-center justify-between gap-3 border-t border-border bg-muted/50 px-3 py-1.5 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1.5">
          {saveState === 'saving' ? (
            <>
              <Loader2 className="size-3 animate-spin" />
              Saving…
            </>
          ) : saveState === 'saved' ? (
            <>
              <Check className="size-3 text-success" />
              Saved
            </>
          ) : saveState === 'error' ? (
            <span className="text-danger">Could not save — will retry on next edit</span>
          ) : readOnly ? (
            'Read only'
          ) : (
            'Autosaves as you type'
          )}
        </span>
        <span className="tabular">{lastSavedAt ? `Updated ${formatRelativeTime(lastSavedAt)}` : null}</span>
      </div>
    </div>
  );
}

/** Shown while the Monaco bundle is loading, sized to avoid a layout jump. */
export function EditorPlaceholder() {
  return (
    <div className="flex h-full w-full items-center justify-center bg-surface">
      <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" />
        Loading editor…
      </div>
    </div>
  );
}

/** Simple monospace block for read-only code display (e.g. previous solutions in revision). */
export function CodeBlock({
  code,
  language,
  className,
  maxHeight = '20rem',
}: {
  code: string;
  language?: string;
  className?: string;
  maxHeight?: string;
}) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable — the user can still select the text */
    }
  };

  return (
    <div className={cn('relative overflow-hidden rounded-[var(--radius-card)] border border-border bg-muted', className)}>
      <button
        type="button"
        onClick={copy}
        className="absolute top-2 right-2 z-10 rounded border border-border bg-surface px-1.5 py-0.5 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
      >
        {copied ? 'Copied' : 'Copy'}
      </button>
      <pre
        className="overflow-auto p-3 text-[12px] leading-relaxed"
        style={{ maxHeight }}
        data-language={language}
      >
        <code className="font-mono">{code}</code>
      </pre>
    </div>
  );
}
