import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { api } from '@/api/client';
import { messageFor } from '@/api/errors';
import { queryKeys } from '@/lib/query-keys';
import { STALE_TIME_MS } from '@/api/config';
import type { DsaListParams, RevisionListParams, TopicListParams } from '@/api/contract';
import type { AIContextType } from '@/types/common';
import type {
  AttemptCreateRequest,
  ProblemNotesUpsert,
  ProgressUpdateRequest,
  RevisionCompleteRequest,
  RevisionCreateRequest,
} from '@/types/dsa';
import type { HLDNotesUpsert, HLDProgressUpdateRequest, HLDTopicFilters } from '@/types/hld';
import type { LLDNotesUpsert, LLDProgressUpdateRequest, LLDTopicFilters } from '@/types/lld';
import type { UserSettingsUpdate } from '@/types/settings';

// ------------------------------------------------------------------- today

export function useToday() {
  return useQuery({
    queryKey: queryKeys.today,
    queryFn: () => api.today.get(),
    staleTime: STALE_TIME_MS,
    refetchOnWindowFocus: true,
  });
}

export function useTodayExplain(enabled = false) {
  return useQuery({
    queryKey: queryKeys.todayExplain,
    queryFn: () => api.today.explain(),
    enabled,
    staleTime: 5 * 60 * 1000,
  });
}

export function useDailyPlans(params: { start_date?: string; end_date?: string } = {}) {
  return useQuery({
    queryKey: queryKeys.dailyPlans(params),
    queryFn: () => api.today.listPlans({ ...params, limit: 60 }),
    staleTime: 5 * 60 * 1000,
  });
}

/**
 * Toggling a plan item is optimistic: the checkbox responds immediately and rolls back if
 * the write fails. Completing an item is also what advances the streak server-side.
 */
export function useTogglePlanItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ itemId, isCompleted }: { itemId: string; isCompleted: boolean }) =>
      api.today.setItemCompletion(itemId, isCompleted),
    onMutate: async ({ itemId, isCompleted }) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.today });
      const previous = queryClient.getQueryData(queryKeys.today);

      queryClient.setQueryData(queryKeys.today, (current: Awaited<ReturnType<typeof api.today.get>> | undefined) => {
        if (!current) return current;
        const patch = <T extends { id: string; is_completed: boolean }>(items: T[]): T[] =>
          items.map((item) => (item.id === itemId ? { ...item, is_completed: isCompleted } : item));
        const recount = (section: typeof current.dsa) => ({
          ...section,
          items: patch(section.items),
          completed: patch(section.items).filter((item) => item.is_completed).length,
        });
        return { ...current, dsa: recount(current.dsa), lld: recount(current.lld), hld: recount(current.hld), revisions: recount(current.revisions) };
      });

      return { previous };
    },
    onError: (error, _variables, context) => {
      if (context?.previous) queryClient.setQueryData(queryKeys.today, context.previous);
      toast.error(messageFor(error));
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.today });
      void queryClient.invalidateQueries({ queryKey: queryKeys.stats.all });
    },
  });
}

// --------------------------------------------------------------------- dsa

export function useProblemCatalog(params: DsaListParams) {
  return useQuery({
    queryKey: queryKeys.dsa.problems(params),
    queryFn: () => api.dsa.listProblems(params),
    staleTime: STALE_TIME_MS,
    placeholderData: (previous) => previous,
  });
}

export function useProblem(problemId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.dsa.problem(problemId ?? ''),
    queryFn: () => api.dsa.getProblem(problemId!),
    enabled: Boolean(problemId),
    staleTime: STALE_TIME_MS,
  });
}

export function useDsaTopics() {
  return useQuery({
    queryKey: queryKeys.dsa.topics,
    queryFn: () => api.dsa.listTopics(),
    staleTime: 10 * 60 * 1000,
  });
}

/**
 * Progress updates touch the catalog row, Today's plan and the statistics, so all three
 * caches are invalidated together rather than leaving the dashboard stale.
 */
export function useUpdateProgress() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ problemId, payload }: { problemId: string; payload: ProgressUpdateRequest }) =>
      api.dsa.updateProgress(problemId, payload),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.dsa.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.revisions.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.today });
      void queryClient.invalidateQueries({ queryKey: queryKeys.stats.all });
      return variables;
    },
    onError: (error) => toast.error(messageFor(error)),
  });
}

export function useCreateAttempt() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ problemId, payload }: { problemId: string; payload: AttemptCreateRequest }) =>
      api.dsa.createAttempt(problemId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.dsa.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.revisions.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.today });
      void queryClient.invalidateQueries({ queryKey: queryKeys.stats.all });
    },
    onError: (error) => toast.error(messageFor(error)),
  });
}

export function useSaveNotes(problemId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: ProblemNotesUpsert) => api.dsa.upsertNotes(problemId, payload),
    onSuccess: (notes) => {
      queryClient.setQueryData(queryKeys.dsa.notes(problemId), notes);
      void queryClient.invalidateQueries({ queryKey: queryKeys.dsa.problem(problemId) });
    },
    // Autosave failures are surfaced quietly — losing focus mid-keystroke is worse than a
    // toast, so the editor keeps the local text and the user can retry.
    onError: (error) => toast.error(`Notes not saved: ${messageFor(error)}`),
  });
}

export function useScheduleRevision() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ problemId, payload }: { problemId: string; payload: RevisionCreateRequest }) =>
      api.dsa.scheduleRevision(problemId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.revisions.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dsa.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.today });
    },
    onError: (error) => toast.error(messageFor(error)),
  });
}

export function useCreateSnippet(problemId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: { code: string; language: string; title?: string; is_primary?: boolean }) =>
      api.dsa.createCode(problemId, {
        code: payload.code,
        language: payload.language as never,
        title: payload.title,
        is_primary: payload.is_primary,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.dsa.code(problemId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dsa.problem(problemId) });
    },
    onError: (error) => toast.error(messageFor(error)),
  });
}

export function useUpdateSnippet(problemId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({
      snippetId,
      payload,
    }: {
      snippetId: string;
      payload: { code?: string; language?: string; title?: string; is_primary?: boolean };
    }) =>
      api.dsa.updateCode(problemId, snippetId, {
        ...payload,
        language: payload.language as never,
      }),
    onSuccess: (snippet) => {
      // Patch the cache in place so autosave does not flash the editor.
      queryClient.setQueryData(queryKeys.dsa.code(problemId), (current: unknown) => {
        if (!Array.isArray(current)) return current;
        return current.map((item) => (item.id === snippet.id ? snippet : item));
      });
    },
    onError: (error) => toast.error(`Code not saved: ${messageFor(error)}`),
  });
}

export function useDeleteSnippet(problemId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (snippetId: string) => api.dsa.deleteCode(problemId, snippetId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.dsa.code(problemId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dsa.problem(problemId) });
      toast.success('Solution deleted');
    },
    onError: (error) => toast.error(messageFor(error)),
  });
}

// --------------------------------------------------------------- revisions

export function useRevisions(params: RevisionListParams) {
  return useQuery({
    queryKey: queryKeys.revisions.list(params),
    queryFn: () => api.revisions.list(params),
    staleTime: STALE_TIME_MS,
  });
}

export function useRevisionSummary() {
  return useQuery({
    queryKey: queryKeys.revisions.summary,
    queryFn: () => api.revisions.summary(),
    staleTime: STALE_TIME_MS,
  });
}

export function useCompleteRevision() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ revisionId, payload }: { revisionId: string; payload: RevisionCompleteRequest }) =>
      api.revisions.complete(revisionId, payload),
    onSuccess: (result) => {
      // The response carries the next scheduled revision, so the ladder is visible at once.
      if (result.next_revision?.due_at) {
        toast.success(`Next review scheduled`);
      } else {
        toast.success(result.message);
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.revisions.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.dsa.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.today });
      void queryClient.invalidateQueries({ queryKey: queryKeys.stats.all });
    },
    onError: (error) => toast.error(messageFor(error)),
  });
}

export function usePromoteStale() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (limit?: number) => api.revisions.promoteStale(limit),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.revisions.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.today });
      if (result.queued === 0) {
        toast.info('Nothing is stale enough to queue right now');
      } else {
        toast.success(result.message);
      }
    },
    onError: (error) => toast.error(messageFor(error)),
  });
}

// ------------------------------------------------------------------- design

export function useLldTopics(params: TopicListParams & LLDTopicFilters) {
  return useQuery({
    queryKey: queryKeys.lld.topics(params),
    queryFn: () => api.lld.listTopics(params),
    staleTime: STALE_TIME_MS,
  });
}

export function useLldTopic(topicId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.lld.topic(topicId ?? ''),
    queryFn: () => api.lld.getTopic(topicId!),
    enabled: Boolean(topicId),
    staleTime: STALE_TIME_MS,
  });
}

export function useUpdateLldProgress() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ topicId, payload }: { topicId: string; payload: LLDProgressUpdateRequest }) =>
      api.lld.updateProgress(topicId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.lld.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.today });
      void queryClient.invalidateQueries({ queryKey: queryKeys.stats.all });
    },
    onError: (error) => toast.error(messageFor(error)),
  });
}

export function useSaveLldNotes(topicId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: LLDNotesUpsert) => api.lld.upsertNotes(topicId, payload),
    onSuccess: (notes) => {
      queryClient.setQueryData(queryKeys.lld.notes(topicId), notes);
      void queryClient.invalidateQueries({ queryKey: queryKeys.lld.topic(topicId) });
    },
    onError: (error) => toast.error(`Notes not saved: ${messageFor(error)}`),
  });
}

export function useCreateLldSnippet(topicId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { code: string; language: string; title?: string }) =>
      api.lld.createCode(topicId, { code: payload.code, language: payload.language as never, title: payload.title }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.lld.code(topicId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.lld.topic(topicId) });
    },
    onError: (error) => toast.error(messageFor(error)),
  });
}

export function useUpdateLldSnippet(topicId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ snippetId, payload }: { snippetId: string; payload: { code?: string; title?: string; language?: string } }) =>
      api.lld.updateCode(topicId, snippetId, { ...payload, language: payload.language as never }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.lld.code(topicId) });
    },
    onError: (error) => toast.error(`Code not saved: ${messageFor(error)}`),
  });
}

export function useHldTopics(params: TopicListParams & HLDTopicFilters) {
  return useQuery({
    queryKey: queryKeys.hld.topics(params),
    queryFn: () => api.hld.listTopics(params),
    staleTime: STALE_TIME_MS,
  });
}

export function useHldTopic(topicId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.hld.topic(topicId ?? ''),
    queryFn: () => api.hld.getTopic(topicId!),
    enabled: Boolean(topicId),
    staleTime: STALE_TIME_MS,
  });
}

export function useUpdateHldProgress() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ topicId, payload }: { topicId: string; payload: HLDProgressUpdateRequest }) =>
      api.hld.updateProgress(topicId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.hld.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.today });
      void queryClient.invalidateQueries({ queryKey: queryKeys.stats.all });
    },
    onError: (error) => toast.error(messageFor(error)),
  });
}

export function useSaveHldNotes(topicId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: HLDNotesUpsert) => api.hld.upsertNotes(topicId, payload),
    onSuccess: (notes) => {
      queryClient.setQueryData(queryKeys.hld.notes(topicId), notes);
      void queryClient.invalidateQueries({ queryKey: queryKeys.hld.topic(topicId) });
    },
    onError: (error) => toast.error(`Design not saved: ${messageFor(error)}`),
  });
}

export function useCreateHldSnippet(topicId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: { code: string; language: string; title?: string }) =>
      api.hld.createCode(topicId, { code: payload.code, language: payload.language as never, title: payload.title }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.hld.code(topicId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.hld.topic(topicId) });
    },
    onError: (error) => toast.error(messageFor(error)),
  });
}

export function useUpdateHldSnippet(topicId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ snippetId, payload }: { snippetId: string; payload: { code?: string; title?: string; language?: string } }) =>
      api.hld.updateCode(topicId, snippetId, { ...payload, language: payload.language as never }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.hld.code(topicId) });
    },
    onError: (error) => toast.error(`Diagram not saved: ${messageFor(error)}`),
  });
}

// -------------------------------------------------------------------- stats

export function useStatsOverview() {
  return useQuery({
    queryKey: queryKeys.stats.overview,
    queryFn: () => api.stats.overview(),
    staleTime: STALE_TIME_MS,
  });
}

export function useTopicStats() {
  return useQuery({
    queryKey: queryKeys.stats.topics,
    queryFn: () => api.stats.topics(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useDifficultyStats() {
  return useQuery({
    queryKey: queryKeys.stats.difficulty,
    queryFn: () => api.stats.difficulty(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useActivityStats(range: Parameters<typeof api.stats.activity>[0]) {
  return useQuery({
    queryKey: queryKeys.stats.activity(range),
    queryFn: () => api.stats.activity(range),
    staleTime: 5 * 60 * 1000,
  });
}

export function useStreak() {
  return useQuery({
    queryKey: queryKeys.stats.streak,
    queryFn: () => api.stats.streak(),
    staleTime: STALE_TIME_MS,
  });
}

// ----------------------------------------------------------------------- ai

export function useAiActions() {
  return useQuery({
    queryKey: queryKeys.ai.actions,
    queryFn: () => api.ai.actions(),
    staleTime: 30 * 60 * 1000,
  });
}

export function useAiConversations(contextType?: AIContextType) {
  return useQuery({
    queryKey: queryKeys.ai.conversations(contextType),
    queryFn: () => api.ai.conversations({ context_type: contextType }),
    staleTime: STALE_TIME_MS,
  });
}

export function useAiConversation(conversationId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.ai.conversation(conversationId ?? ''),
    queryFn: () => api.ai.conversation(conversationId!),
    enabled: Boolean(conversationId),
  });
}

// ----------------------------------------------------------------- settings

export function useSettings() {
  return useQuery({
    queryKey: queryKeys.settings.detail,
    queryFn: () => api.settings.get(),
    staleTime: 5 * 60 * 1000,
  });
}

export function useUpdateSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: UserSettingsUpdate) => api.settings.update(payload),
    onSuccess: (settings) => {
      queryClient.setQueryData(queryKeys.settings.detail, settings);
      void queryClient.invalidateQueries({ queryKey: queryKeys.today });
      toast.success('Settings saved');
    },
    onError: (error) => toast.error(messageFor(error)),
  });
}

export function useDevices() {
  return useQuery({
    queryKey: queryKeys.settings.devices,
    queryFn: () => api.settings.devices(),
    staleTime: 60 * 1000,
  });
}

export function useSyncStatus() {
  return useQuery({
    queryKey: queryKeys.sync.status,
    queryFn: () => api.sync.status(),
    staleTime: 60 * 1000,
  });
}

/** Manual sync trigger used by the Settings screen and the header indicator. */
export function useRunSync() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      // Push anything queued, then pull from the last known cursor, then refresh the clock.
      await api.sync.push({ device_id: 'web-this-browser', device_type: 'web', mutations: [] }).catch(() => null);
      const status = await api.sync.status();
      return status;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.sync.status });
      void queryClient.invalidateQueries({ queryKey: queryKeys.settings.devices });
      toast.success('Synced');
    },
    onError: (error) => toast.error(messageFor(error)),
  });
}
