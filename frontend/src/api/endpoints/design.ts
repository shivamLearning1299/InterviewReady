import { DEFAULT_PAGE_SIZE } from '@/api/config';
import { http } from '@/api/http';
import type { TopicListParams } from '@/api/contract';
import type { Page } from '@/types/common';
import type {
  HLDNotes,
  HLDNotesUpsert,
  HLDProgressUpdateRequest,
  HLDSnippet,
  HLDSnippetCreate,
  HLDSnippetUpdate,
  HLDTopicDetail,
  HLDTopicSummary,
} from '@/types/hld';
import type {
  LLDNotes,
  LLDNotesUpsert,
  LLDProgressUpdateRequest,
  LLDSnippet,
  LLDSnippetCreate,
  LLDSnippetUpdate,
  LLDTopicDetail,
  LLDTopicSummary,
} from '@/types/lld';

/** Shared query mapper for both design curricula. */
function toTopicQuery(params: TopicListParams = {}) {
  return {
    limit: params.limit ?? DEFAULT_PAGE_SIZE,
    offset: params.offset ?? 0,
    search: params.search,
    category: params.category === 'all' ? undefined : params.category,
    status: params.status === 'all' ? undefined : params.status,
    order_by: params.order_by,
  };
}

const lldPath = '/lld';
const hldPath = '/hld';

export const lldEndpoints = {
  listTopics: (params: TopicListParams = {}) =>
    http.get<Page<LLDTopicSummary>>(lldPath, { query: toTopicQuery(params) }),

  getTopic: (topicId: string) => http.get<LLDTopicDetail>(`${lldPath}/${topicId}`),

  updateProgress: (topicId: string, payload: LLDProgressUpdateRequest) =>
    http.put<{ topic_id: string; status: string; confidence: number | null }>(
      `${lldPath}/${topicId}/progress`,
      payload,
    ),

  getNotes: (topicId: string) => http.get<LLDNotes | null>(`${lldPath}/${topicId}/notes`),

  upsertNotes: (topicId: string, payload: LLDNotesUpsert) =>
    http.put<LLDNotes>(`${lldPath}/${topicId}/notes`, payload),

  listCode: (topicId: string) => http.get<LLDSnippet[]>(`${lldPath}/${topicId}/code`),

  createCode: (topicId: string, payload: LLDSnippetCreate) =>
    http.post<LLDSnippet>(`${lldPath}/${topicId}/code`, payload),

  updateCode: (topicId: string, snippetId: string, payload: LLDSnippetUpdate) =>
    http.put<LLDSnippet>(`${lldPath}/${topicId}/code/${snippetId}`, payload),

  deleteCode: (topicId: string, snippetId: string) =>
    http.delete<{ id: string; message: string }>(`${lldPath}/${topicId}/code/${snippetId}`),
};

export const hldEndpoints = {
  listTopics: (params: TopicListParams = {}) =>
    http.get<Page<HLDTopicSummary>>(hldPath, { query: toTopicQuery(params) }),

  getTopic: (topicId: string) => http.get<HLDTopicDetail>(`${hldPath}/${topicId}`),

  updateProgress: (topicId: string, payload: HLDProgressUpdateRequest) =>
    http.put<{ topic_id: string; status: string; confidence: number | null }>(
      `${hldPath}/${topicId}/progress`,
      payload,
    ),

  getNotes: (topicId: string) => http.get<HLDNotes | null>(`${hldPath}/${topicId}/notes`),

  upsertNotes: (topicId: string, payload: HLDNotesUpsert) =>
    http.put<HLDNotes>(`${hldPath}/${topicId}/notes`, payload),

  listCode: (topicId: string) => http.get<HLDSnippet[]>(`${hldPath}/${topicId}/code`),

  createCode: (topicId: string, payload: HLDSnippetCreate) =>
    http.post<HLDSnippet>(`${hldPath}/${topicId}/code`, payload),

  updateCode: (topicId: string, snippetId: string, payload: HLDSnippetUpdate) =>
    http.put<HLDSnippet>(`${hldPath}/${topicId}/code/${snippetId}`, payload),

  deleteCode: (topicId: string, snippetId: string) =>
    http.delete<{ id: string; message: string }>(`${hldPath}/${topicId}/code/${snippetId}`),
};
