import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Loader2, Send, Sparkles, Trash2 } from 'lucide-react';

import { api } from '@/api/client';
import { messageFor } from '@/api/errors';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Tooltip } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import { useAiActions } from '@/hooks/use-api';
import { localId } from '@/lib/helpers';
import type { AIAction, AIContextType, UUID } from '@/types/common';
import type { ChatTurn } from '@/types/ai';

/** Actions surfaced per workspace, in the order they appear in the quick-action row. */
const DSA_ACTIONS: AIAction[] = [
  'give_hint',
  'explain_concept',
  'explain_code',
  'find_bug',
  'complexity',
  'alternative_approach',
  'interview_me',
];

const DESIGN_ACTIONS: AIAction[] = [
  'review_design',
  'solid_check',
  'missing_classes',
  'review_architecture',
  'scaling_bottlenecks',
  'database_choice',
  'api_design_review',
  'challenge_assumptions',
  'failure_scenarios',
];

export interface AITutorPanelProps {
  contextType: AIContextType;
  /**
   * Identifies the entity the tutor is scoped to. The shape depends on `contextType`:
   *
   * - `dsa`  — the DSA problem **slug** (e.g. `'two-sum'`), i.e. `DSAProblemDetail.id`
   *            or `Revision.problem_id`. The DSA catalog's primary key is its slug
   *            (`dsa_problems.id TEXT`), so it is a slug and never a UUID.
   * - `lld` / `hld` — the **topic UUID**, i.e. `LLDTopicDetail.id` / `HLDTopicDetail.id`.
   *            Those tables use UUID primary keys.
   * - `general` (or absent) — the caller omits this prop entirely; it is sent as `null`.
   *
   * The two shapes differ because `AIChatRequest.context_id` is a `str` that stores either
   * a slug or a UUID: typing it as a UUID made every DSA tutor request fail Pydantic
   * validation with a 422 before the request reached the service. Passing the wrong shape
   * is therefore a real, previously-shipped defect — not a cosmetic mismatch.
   */
  contextId?: string | null;
  /** Shown in the panel header so the user knows what the tutor can see. */
  contextLabel?: string | null;
  /** LLD/HLD workspaces pass their action set; DSA uses the default. */
  actions?: AIAction[];
  /** Currently highlighted code, forwarded so "Explain Selected Code" works. */
  selectedCode?: string | null;
  /** Called when the tutor should read the whole file rather than a selection. */
  getFullCode?: () => string | null;
  className?: string;
  /** Renders as a sidebar column (default) or a full-width page. */
  variant?: 'panel' | 'page';
  /** Optional conversation to resume (used by the AI Tutor page). */
  initialConversationId?: UUID | null;
}

/**
 * The AI tutor.
 *
 * Two behaviours matter here and are both enforced server-side as well as reflected in the
 * UI: the tutor knows only the entity in focus, and it gives progressively stronger hints
 * rather than revealing the solution outright.
 */
export function AITutorPanel({
  contextType,
  contextId,
  contextLabel,
  actions,
  selectedCode,
  getFullCode,
  className,
  variant = 'panel',
  initialConversationId = null,
}: AITutorPanelProps) {
  const [conversationId, setConversationId] = useState<UUID | null>(initialConversationId);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const { data: actionsMeta } = useAiActions();

  const available = useMemo(() => {
    const wanted = actions ?? (contextType === 'dsa' ? DSA_ACTIONS : contextType === 'general' ? [] : DESIGN_ACTIONS);
    // Filter against what the server advertises, but never let a missing action list
    // hide the controls entirely.
    const advertised = new Set(actionsMeta?.actions.map((entry) => entry.action) ?? []);
    if (advertised.size === 0) return wanted;
    return wanted.filter((action) => advertised.has(action));
  }, [actions, actionsMeta, contextType]);

  const labelFor = useCallback(
    (action: string) =>
      actionsMeta?.actions.find((entry) => entry.action === action)?.label ??
      action.replace(/_/g, ' ').replace(/\b\w/g, (character) => character.toUpperCase()),
    [actionsMeta],
  );

  // Load an existing thread when resuming from history.
  useEffect(() => {
    if (!initialConversationId) {
      setConversationId(null);
      setTurns([]);
      return;
    }

    let cancelled = false;
    setLoadingHistory(true);

    void (async () => {
      try {
        const conversation = await api.ai.conversation(initialConversationId);
        if (cancelled) return;
        setConversationId(conversation.id);
        setTurns(
          conversation.messages
            .filter((message) => message.role !== 'system')
            .map((message) => ({
              id: message.id,
              role: message.role === 'assistant' ? 'assistant' : 'user',
              content: message.content,
              action: (message.action ?? undefined) as AIAction | undefined,
              selectedCode: message.selected_code,
              createdAt: message.created_at,
              error: message.error,
            })),
        );
      } catch (error) {
        if (!cancelled) toast.error(messageFor(error));
      } finally {
        if (!cancelled) setLoadingHistory(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [initialConversationId]);

  // Follow the conversation as it grows, and on send.
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  }, [turns, sending]);

  const send = useCallback(
    async (message: string, action: AIAction = 'general', code?: string | null) => {
      const trimmed = message.trim();
      if (!trimmed || sending) return;

      const optimistic: ChatTurn = {
        id: localId('turn'),
        role: 'user',
        content: trimmed,
        action,
        selectedCode: code ?? null,
        createdAt: new Date().toISOString(),
      };

      setTurns((current) => [...current, optimistic]);
      setInput('');
      setSending(true);

      try {
        const response = await api.ai.chat({
          context_type: contextType,
          context_id: contextId ?? null,
          message: trimmed,
          action,
          selected_code: code ?? null,
          conversation_id: conversationId,
          include_history: true,
        });

        setConversationId(response.conversation_id);
        setTurns((current) => [
          ...current,
          {
            id: response.message.id,
            role: 'assistant',
            content: response.message.content,
            action: (response.message.action ?? undefined) as AIAction | undefined,
            selectedCode: response.message.selected_code,
            createdAt: response.message.created_at,
            error: response.message.error,
          },
        ]);
      } catch (error) {
        const apiError = messageFor(error);
        // Keep the user's message and attach the failure to it, rather than losing the text.
        setTurns((current) =>
          current.map((turn) =>
            turn.id === optimistic.id ? { ...turn, error: apiError } : turn,
          ),
        );
        toast.error(apiError);
      } finally {
        setSending(false);
        // Return focus so the next message needs no click.
        inputRef.current?.focus();
      }
    },
    [contextId, contextType, conversationId, sending],
  );

  const runAction = (action: AIAction) => {
    const needsCode = action === 'explain_code' || action === 'find_bug';
    const code = needsCode ? (selectedCode || getFullCode?.() || null) : selectedCode || null;

    if (action === 'explain_code' && !code) {
      toast.info('Highlight some code in the editor first');
      return;
    }

    const prompts: Partial<Record<AIAction, string>> = {
      give_hint: 'Give me a hint for this.',
      explain_concept: 'Explain the key concept behind this.',
      explain_code: 'Explain the code I selected.',
      find_bug: 'Look for bugs in this.',
      complexity: 'What is the time and space complexity?',
      alternative_approach: 'What alternative approaches should I consider?',
      interview_me: 'Interview me on this.',
      review_design: 'Review my design.',
      solid_check: 'Which SOLID principles am I violating?',
      missing_classes: 'Which classes am I missing?',
      review_architecture: 'Review my architecture.',
      scaling_bottlenecks: 'Where will this break under load?',
      database_choice: 'Is my database choice right?',
      api_design_review: 'Review my API design.',
      challenge_assumptions: 'Challenge my assumptions.',
      failure_scenarios: 'What failure scenarios should I plan for?',
    };

    void send(prompts[action] ?? labelFor(action), action, code);
  };

  const isPage = variant === 'page';

  return (
    <div className={cn('flex min-h-0 flex-col', className)}>
      {/* Header */}
      <div className="flex shrink-0 items-start justify-between gap-3 border-b border-border px-3.5 py-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-1.5 text-[13px] font-semibold">
            <Sparkles className="size-3.5 text-primary" />
            AI Tutor
          </h2>
          <p className="mt-0.5 truncate text-[11px] text-muted-foreground" title={contextLabel ?? undefined}>
            {contextLabel
              ? `Context: ${contextLabel}`
              : contextType === 'general'
                ? 'General tutor — no problem context'
                : 'Knows the current item'}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          {turns.length > 0 ? (
            <Tooltip content="Start a new conversation">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Start a new conversation"
                onClick={() => {
                  setConversationId(null);
                  setTurns([]);
                }}
              >
                <Trash2 />
              </Button>
            </Tooltip>
          ) : null}
        </div>
      </div>

      {/* Quick actions */}
      {available.length > 0 ? (
        <div className="flex shrink-0 flex-wrap gap-1.5 border-b border-border px-3 py-2">
          {available.map((action) => {
            const needsCode = action === 'explain_code';
            const disabled = sending || (needsCode && !selectedCode && !getFullCode);
            return (
              <button
                key={action}
                type="button"
                disabled={disabled}
                onClick={() => runAction(action)}
                title={needsCode && !selectedCode ? 'Highlight code in the editor to enable this' : undefined}
                className={cn(
                  'rounded-full border px-2.5 py-1 text-[12px] font-medium transition-colors',
                  disabled
                    ? 'cursor-not-allowed border-border text-subtle-foreground opacity-60'
                    : 'border-border text-muted-foreground hover:border-primary/40 hover:bg-primary-soft hover:text-primary',
                )}
              >
                {labelFor(action)}
              </button>
            );
          })}
        </div>
      ) : null}

      {/* Transcript */}
      <div
        ref={scrollRef}
        className={cn('min-h-0 flex-1 space-y-3 overflow-y-auto px-3.5 py-3', isPage && 'px-5')}
        aria-live="polite"
        aria-busy={sending}
      >
        {loadingHistory ? (
          <div className="flex items-center gap-2 text-[13px] text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            Loading conversation…
          </div>
        ) : turns.length === 0 ? (
          <EmptyState
            compact
            icon={<Sparkles className="size-4" />}
            title="Ask anything about this item"
            description={
              contextType === 'dsa'
                ? 'Hints get stronger each time you ask, so you can stay in the problem instead of reading the answer. Ask for the full solution explicitly when you want it.'
                : 'Use a quick action above, or ask your own question. The tutor can see this item\u2019s details, your notes and your progress.'
            }
          />
        ) : (
          turns.map((turn) => <ChatBubble key={turn.id} turn={turn} />)
        )}

        {sending ? (
          <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            Thinking…
          </div>
        ) : null}
      </div>

      {/* Composer */}
      <div className="shrink-0 border-t border-border p-3">
        {selectedCode ? (
          <p className="mb-1.5 flex items-center gap-1.5 text-[11px] text-primary">
            <span className="rounded bg-primary-soft px-1.5 py-0.5 font-medium">
              {selectedCode.split('\n').length} line selection attached
            </span>
          </p>
        ) : null}
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                void send(input);
              }
            }}
            rows={isPage ? 3 : 2}
            placeholder={
              contextType === 'dsa'
                ? 'Ask about this problem… (Shift+Enter for a new line)'
                : contextType === 'general'
                  ? 'Ask anything — DP, BFS vs DFS, consistent hashing…'
                  : 'Ask about this design…'
            }
            aria-label="Message the AI tutor"
            className="min-h-9 flex-1 resize-none rounded-[var(--radius-control)] border border-border bg-surface px-2.5 py-2 text-[13px] leading-relaxed outline-none placeholder:text-subtle-foreground focus:border-primary focus:ring-2 focus:ring-ring/40"
          />
          <Button
            variant="primary"
            size="icon"
            onClick={() => void send(input)}
            disabled={!input.trim() || sending}
            aria-label="Send message"
          >
            {sending ? <Loader2 className="animate-spin" /> : <Send />}
          </Button>
        </div>
      </div>
    </div>
  );
}

/** One transcript entry. Assistant replies keep their formatting as plain paragraphs. */
function ChatBubble({ turn }: { turn: ChatTurn }) {
  const isUser = turn.role === 'user';

  return (
    <div className={cn('flex flex-col gap-1', isUser && 'items-end')}>
      {turn.selectedCode ? (
        <pre className="max-w-full overflow-x-auto rounded-md border border-border bg-muted px-2 py-1.5 text-[11px]">
          <code className="font-mono">{turn.selectedCode}</code>
        </pre>
      ) : null}

      <div
        className={cn(
          'max-w-full rounded-[var(--radius-card)] px-3 py-2 text-[13px] leading-relaxed whitespace-pre-wrap',
          isUser
            ? 'border border-primary/25 bg-primary-soft text-foreground'
            : 'border border-border bg-muted text-foreground',
        )}
      >
        {turn.content}
      </div>

      {turn.error ? (
        <p className="text-[11px] text-danger">Not delivered — {turn.error}</p>
      ) : (
        <p className="text-[10px] text-subtle-foreground">
          {new Date(turn.createdAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </p>
      )}
    </div>
  );
}
