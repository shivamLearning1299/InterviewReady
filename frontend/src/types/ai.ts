import type { AIAction, AIContextType, Timestamped, UUID } from '@/types/common';

/** AI tutor payloads — mirrors `schemas/ai.py`. */

export interface AIChatRequest {
  context_type: AIContextType;
  context_id?: UUID | null;
  message: string;
  action?: AIAction;
  selected_code?: string | null;
  snippet_id?: UUID | null;
  conversation_id?: UUID | null;
  include_history?: boolean;
}

export interface AIMessage extends Timestamped {
  role: 'system' | 'user' | 'assistant';
  content: string;
  action: string | null;
  provider: string | null;
  model: string | null;
  usage: Record<string, unknown> | null;
  selected_code: string | null;
  error: string | null;
}

export interface AIChatResponse {
  conversation_id: UUID;
  message: AIMessage;
  context_used: Record<string, unknown>;
  is_new_conversation: boolean;
}

export interface AIConversationSummary extends Timestamped {
  title: string | null;
  context_type: AIContextType;
  context_id: UUID | null;
  context_label: string | null;
  provider: string | null;
  model: string | null;
  message_count: number;
  last_message_at: string | null;
  preview: string | null;
}

export interface AIConversationDetail extends AIConversationSummary {
  messages: AIMessage[];
}

export interface AIActionsResponse {
  actions: { action: string; label: string; description?: string }[];
  context_types: string[];
  provider: string;
  model: string;
  enabled: boolean;
}

/** Locally rendered chat turn (optimistic user message before the server replies). */
export interface ChatTurn {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  action?: AIAction;
  selectedCode?: string | null;
  createdAt: string;
  pending?: boolean;
  error?: string | null;
}
