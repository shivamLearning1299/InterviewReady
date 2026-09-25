import { DEFAULT_PAGE_SIZE } from '@/api/config';
import { http } from '@/api/http';
import type { ConversationListParams } from '@/api/contract';
import type { Page } from '@/types/common';
import type {
  AIActionsResponse,
  AIChatRequest,
  AIChatResponse,
  AIConversationDetail,
  AIConversationSummary,
} from '@/types/ai';

export const aiEndpoints = {
  chat: (payload: AIChatRequest) => http.post<AIChatResponse>('/ai/chat', payload),

  actions: () => http.get<AIActionsResponse>('/ai/actions'),

  conversations: (params: ConversationListParams = {}) =>
    http.get<Page<AIConversationSummary>>('/ai/conversations', {
      query: {
        limit: params.limit ?? DEFAULT_PAGE_SIZE,
        offset: params.offset ?? 0,
        context_type: params.context_type,
      },
    }),

  conversation: (conversationId: string) =>
    http.get<AIConversationDetail>(`/ai/conversations/${conversationId}`),

  deleteConversation: (conversationId: string) =>
    http.delete<{ id: string; message: string }>(`/ai/conversations/${conversationId}`),
};
