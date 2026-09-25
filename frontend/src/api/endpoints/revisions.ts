import { DEFAULT_PAGE_SIZE } from '@/api/config';
import { http } from '@/api/http';
import type { RevisionListParams } from '@/api/contract';
import type { Page } from '@/types/common';
import type {
  Revision,
  RevisionCompleteRequest,
  RevisionCompleteResponse,
  RevisionSummary,
} from '@/types/dsa';

export const revisionsEndpoints = {
  list: (params: RevisionListParams = {}) =>
    http.get<Page<Revision>>('/revisions', {
      query: {
        limit: params.limit ?? DEFAULT_PAGE_SIZE,
        offset: params.offset ?? 0,
        bucket: params.bucket,
        completed: params.completed === null ? undefined : (params.completed ?? false),
      },
    }),

  summary: () => http.get<RevisionSummary>('/revisions/summary'),

  complete: (revisionId: string, payload: RevisionCompleteRequest) =>
    http.post<RevisionCompleteResponse>(`/revisions/${revisionId}/complete`, payload),

  promoteStale: (limit = 10) =>
    http.post<{ queued: number; message: string }>('/revisions/promote-stale', undefined, {
      query: { limit },
    }),
};
