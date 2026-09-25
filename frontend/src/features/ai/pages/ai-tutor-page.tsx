import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { MessageSquarePlus, Sparkles, Trash2 } from 'lucide-react';

import { AITutorPanel } from '@/features/ai/ai-tutor-panel';
import { PageHeader } from '@/components/shared/page-header';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';
import { SegmentedControl } from '@/components/ui/switch';
import { SkeletonRow } from '@/components/ui/skeleton';
import { api } from '@/api/client';
import { messageFor } from '@/api/errors';
import { useAiConversations } from '@/hooks/use-api';
import { AI_SUGGESTIONS } from '@/lib/constants';
import { formatRelativeTime } from '@/lib/format';
import { routes } from '@/lib/query-keys';
import { cn } from '@/lib/utils';
import type { AIContextType } from '@/types/common';

const CONTEXT_OPTIONS: { value: AIContextType; label: string; description: string }[] = [
  { value: 'general', label: 'General', description: 'Interview strategy, study plans, anything' },
  { value: 'dsa', label: 'DSA', description: 'Data structures and algorithms' },
  { value: 'lld', label: 'LLD', description: 'Object design and design patterns' },
  { value: 'hld', label: 'HLD', description: 'Architecture and system design' },
];

/**
 * Standalone AI tutor.
 *
 * The same panel that lives beside the problem workspace, but with an explicit context
 * selector — this is where a question that is not attached to one problem belongs. The
 * tutor still only sees the context chosen here; that scoping is deliberate rather than a
 * limitation.
 */
export function AiTutorPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const navigate = useNavigate();

  const [contextType, setContextType] = useState<AIContextType>('general');

  const conversations = useAiConversations(contextType);

  const activeContext = useMemo(
    () => CONTEXT_OPTIONS.find((option) => option.value === contextType),
    [contextType],
  );

  /** Suggestions are filtered to the active context, always keeping the general ones. */
  const suggestions = useMemo(
    () => AI_SUGGESTIONS.filter((item) => item.context === contextType || item.context === 'general'),
    [contextType],
  );
  const items = conversations.data?.items ?? [];

  const deleteConversation = async (id: string) => {
    try {
      await api.ai.deleteConversation(id);
      toast.success('Conversation deleted');
      void conversations.refetch();
      if (conversationId === id) navigate(routes.ai, { replace: true });
    } catch (error) {
      toast.error(messageFor(error));
    }
  };

  return (
    <div className="mx-auto flex h-[calc(100dvh-3.25rem)] w-full max-w-[1600px] flex-col px-4 py-5 sm:px-6">
      <PageHeader
        title="AI Tutor"
        description="Hint-first, never solution-first. Ask for the next nudge rather than the answer and you will retain more of it."
        actions={
          conversationId ? (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => navigate(routes.ai, { replace: true })}
            >
              <MessageSquarePlus />
              New conversation
            </Button>
          ) : undefined
        }
      />

      {/* Context selector */}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <SegmentedControl
          label="Tutor context"
          value={contextType}
          onChange={(value) => {
            setContextType(value);
            navigate(routes.ai, { replace: true });
          }}
          options={CONTEXT_OPTIONS.map((option) => ({
            value: option.value,
            label: option.label,
            title: option.description,
          }))}
        />
        {activeContext ? (
          <p className="text-[12px] text-muted-foreground">{activeContext.description}</p>
        ) : null}
      </div>

      <div className="mt-4 grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,1fr)_18rem]">
        {/* Tutor */}
        <Card padding="none" className="min-h-0 overflow-hidden">
          <AITutorPanel
            variant="page"
            contextType={contextType}
            initialConversationId={conversationId ?? null}
            className="h-full"
          />
        </Card>

        {/* Sidebar: suggestions and history */}
        <div className="flex min-h-0 flex-col gap-4 overflow-y-auto">
          <Card padding="md" className="space-y-2.5">
            <h2 className="flex items-center gap-1.5 text-sm font-semibold">
              <Sparkles className="size-3.5" />
              Try asking
            </h2>
            <ul className="space-y-1.5">
              {suggestions.map((suggestion) => (
                <li key={suggestion.label}>
                  <p className="text-[13px] font-medium">{suggestion.label}</p>
                  <p className="text-[12px] text-muted-foreground">{suggestion.prompt}</p>
                </li>
              ))}
            </ul>
            <p className="pt-1 text-[11px] text-subtle-foreground">
              Open a problem or design topic to ask about something specific — the tutor reads
              that entity's notes and code when it is in focus.
            </p>
          </Card>

          <Card padding="none" className="overflow-hidden">
            <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
              <h2 className="text-sm font-semibold">Recent conversations</h2>
              <span className="tabular text-[12px] text-subtle-foreground">{items.length}</span>
            </div>

            {conversations.isLoading ? (
              <div>
                <SkeletonRow />
                <SkeletonRow />
                <SkeletonRow />
              </div>
            ) : conversations.isError ? (
              <ErrorState
                title="Could not load history"
                onRetry={() => void conversations.refetch()}
                className="px-4 py-8"
              />
            ) : items.length === 0 ? (
              <EmptyState
                compact
                title="No conversations yet"
                description="Anything you ask is saved here so you can return to it."
              />
            ) : (
              <ul className="divide-y divide-border">
                {items.map((conversation) => (
                  <li
                    key={conversation.id}
                    className={cn(
                      'group flex items-start gap-2 px-4 py-2.5 transition-colors hover:bg-surface-hover',
                      conversation.id === conversationId && 'bg-primary-soft/40',
                    )}
                  >
                    <Link
                      to={routes.aiConversation(conversation.id)}
                      className="min-w-0 flex-1"
                    >
                      <p className="truncate text-[13px] font-medium">
                        {conversation.title ?? 'Untitled conversation'}
                      </p>
                      <p className="mt-0.5 text-[11px] text-subtle-foreground">
                        {conversation.message_count} message
                        {conversation.message_count === 1 ? '' : 's'} ·{' '}
                        {formatRelativeTime(conversation.last_message_at ?? conversation.updated_at)}
                      </p>
                    </Link>
                    <button
                      type="button"
                      aria-label={`Delete ${conversation.title ?? 'conversation'}`}
                      onClick={() => void deleteConversation(conversation.id)}
                      className="shrink-0 rounded p-1 text-subtle-foreground opacity-0 transition-opacity hover:text-danger group-hover:opacity-100 focus-visible:opacity-100"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
