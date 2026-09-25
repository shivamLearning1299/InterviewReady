import { DEFAULT_PAGE_SIZE } from '@/api/config';
import { http } from '@/api/http';
import type { DsaListParams } from '@/api/contract';
import type { Page } from '@/types/common';
import type {
  Attempt,
  AttemptCreateRequest,
  AttemptUpdateRequest,
  CodeSnippet,
  CodeSnippetCreate,
  CodeSnippetUpdate,
  DSAProblemDetail,
  DSAProblemSummary,
  ProblemNotes,
  ProblemNotesUpsert,
  ProgressResponse,
  ProgressUpdateRequest,
  Revision,
  RevisionCreateRequest,
  TopicOption,
} from '@/types/dsa';

const DSA_PATH = '/dsa/problems';

/** Map the UI filter object onto the query parameter names the API expects. */
function toProblemQuery(params: DsaListParams = {}) {
  return {
    limit: params.limit ?? DEFAULT_PAGE_SIZE,
    offset: params.offset ?? 0,
    search: params.search,
    topic: params.topic,
    pattern: params.pattern,
    difficulty: params.difficulty === 'all' ? undefined : params.difficulty,
    // The backend renames `status` to `status_filter` internally but exposes it as `status`.
    status: params.status === 'all' ? undefined : params.status,
    company: params.company,
    source: params.source,
    revision_due: params.revision_due ? true : undefined,
    favorites_only: params.favorites_only ? true : undefined,
    order_by: params.order_by,
  };
}

export const dsaEndpoints = {
  listProblems: (params: DsaListParams = {}) =>
    http.get<Page<DSAProblemSummary>>(DSA_PATH, { query: toProblemQuery(params) }),

  getProblem: (problemId: string) => http.get<DSAProblemDetail>(`${DSA_PATH}/${problemId}`),

  listTopics: () => http.get<{ items: TopicOption[] }>('/dsa/topics'),

  updateProgress: (problemId: string, payload: ProgressUpdateRequest) =>
    http.put<ProgressResponse>(`${DSA_PATH}/${problemId}/progress`, payload),

  listAttempts: (problemId: string, params: DsaListParams = {}) =>
    http.get<Page<Attempt>>(`${DSA_PATH}/${problemId}/attempts`, {
      query: { limit: params.limit ?? 20, offset: params.offset ?? 0 },
    }),

  createAttempt: (problemId: string, payload: AttemptCreateRequest) =>
    http.post<Attempt>(`${DSA_PATH}/${problemId}/attempts`, payload),

  updateAttempt: (problemId: string, attemptId: string, payload: AttemptUpdateRequest) =>
    http.patch<Attempt>(`${DSA_PATH}/${problemId}/attempts/${attemptId}`, payload),

  getNotes: (problemId: string) =>
    http.get<ProblemNotes | null>(`${DSA_PATH}/${problemId}/notes`),

  upsertNotes: (problemId: string, payload: ProblemNotesUpsert) =>
    http.put<ProblemNotes>(`${DSA_PATH}/${problemId}/notes`, payload),

  listCode: (problemId: string) => http.get<CodeSnippet[]>(`${DSA_PATH}/${problemId}/code`),

  createCode: (problemId: string, payload: CodeSnippetCreate) =>
    http.post<CodeSnippet>(`${DSA_PATH}/${problemId}/code`, payload),

  updateCode: (problemId: string, snippetId: string, payload: CodeSnippetUpdate) =>
    http.put<CodeSnippet>(`${DSA_PATH}/${problemId}/code/${snippetId}`, payload),

  deleteCode: (problemId: string, snippetId: string) =>
    http.delete<{ id: string; message: string }>(`${DSA_PATH}/${problemId}/code/${snippetId}`),

  scheduleRevision: (problemId: string, payload: RevisionCreateRequest) =>
    http.post<Revision>(`${DSA_PATH}/${problemId}/revision`, payload),
};
