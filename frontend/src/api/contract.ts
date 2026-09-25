/**
 * The frontend's contract with the backend, expressed as one interface.
 *
 * Two implementations satisfy it — `realClient` (HTTP against FastAPI) and `mockClient`
 * (in-memory data with latency) — and `api` resolves to whichever `VITE_USE_MOCKS` selects.
 * UI code imports only `api`, so switching to the live backend requires no component changes.
 */

import type {
  AIChatRequest,
  AIChatResponse,
  AIActionsResponse,
  AIConversationDetail,
  AIConversationSummary,
} from '@/types/ai';
import type { AIContextType, DeletedResponse, Page, UserResponse } from '@/types/common';
import type {
  Attempt,
  AttemptCreateRequest,
  AttemptUpdateRequest,
  CodeSnippet,
  CodeSnippetCreate,
  CodeSnippetUpdate,
  DSAProblemDetail,
  DSAProblemSummary,
  DSAFilters,
  ProblemNotes,
  ProblemNotesUpsert,
  ProgressResponse,
  ProgressUpdateRequest,
  Revision,
  RevisionCompleteRequest,
  RevisionCompleteResponse,
  RevisionCreateRequest,
  RevisionSummary,
  TopicOption,
} from '@/types/dsa';
import type {
  HLDTopicDetail,
  HLDTopicSummary,
  HLDNotes,
  HLDNotesUpsert,
  HLDProgressUpdateRequest,
  HLDSnippet,
  HLDSnippetCreate,
  HLDSnippetUpdate,
  HLDTopicFilters,
} from '@/types/hld';
import type {
  LLDTopicDetail,
  LLDTopicSummary,
  LLDNotes,
  LLDNotesUpsert,
  LLDProgressUpdateRequest,
  LLDSnippet,
  LLDSnippetCreate,
  LLDSnippetUpdate,
  LLDTopicFilters,
} from '@/types/lld';
import type { SearchGroup, SearchResultKind } from '@/types/search';
import type {
  StudySession,
  StudySessionStartRequest,
  StudySessionStopRequest,
  SyncStatus,
  UserDevice,
  UserSettings,
  UserSettingsUpdate,
} from '@/types/settings';
import type {
  ActivityRange,
  ActivityResponse,
  DifficultyStatsResponse,
  MasteryResponse,
  StatsOverview,
  StreakResponse,
  TopicStatsResponse,
} from '@/types/stats';
import type {
  DailyPlanDetail,
  PlanGenerationDebug,
  TodayResponse,
} from '@/types/today';

// ------------------------------------------------------------------- parameters

export interface PageParams {
  limit?: number;
  offset?: number;
}

export interface DsaListParams extends DSAFilters, PageParams {}

export interface AttemptListParams extends PageParams {}

export interface RevisionListParams extends PageParams {
  bucket?: 'due' | 'overdue' | 'upcoming';
  completed?: boolean | null;
}

export interface TopicListParams extends PageParams {
  search?: string;
  category?: string;
  status?: string;
  order_by?: string;
}

export interface ConversationListParams extends PageParams {
  context_type?: AIContextType;
}

export interface PlanListParams extends PageParams {
  start_date?: string;
  end_date?: string;
}

export interface SyncPullParams {
  cursor?: number;
  limit?: number;
  device_id?: string;
}

export interface SyncPushPayload {
  device_id?: string;
  device_type?: string;
  mutations: {
    mutation_id: string;
    entity: string;
    operation?: string;
    record_id?: string;
    base_version?: number;
    payload?: Record<string, unknown>;
    client_timestamp?: string;
  }[];
}

// --------------------------------------------------------------------- interface

export interface ApiClient {
  readonly mode: 'mock' | 'live';

  users: {
    me(): Promise<UserResponse>;
    /** Raw JSON export of the user's own data, as a downloadable blob. */
    exportData(includeConversations?: boolean): Promise<Blob>;
  };

  today: {
    get(): Promise<TodayResponse>;
    explain(): Promise<PlanGenerationDebug>;
    listPlans(params?: PlanListParams): Promise<Page<DailyPlanDetail>>;
    getPlan(planDate: string): Promise<TodayResponse>;
    setItemCompletion(itemId: string, isCompleted: boolean): Promise<DailyPlanDetail>;
    removeItem(itemId: string): Promise<DeletedResponse>;
  };

  dsa: {
    listProblems(params?: DsaListParams): Promise<Page<DSAProblemSummary>>;
    getProblem(problemId: string): Promise<DSAProblemDetail>;
    listTopics(): Promise<{ items: TopicOption[] }>;
    updateProgress(problemId: string, payload: ProgressUpdateRequest): Promise<ProgressResponse>;
    listAttempts(problemId: string, params?: AttemptListParams): Promise<Page<Attempt>>;
    createAttempt(problemId: string, payload: AttemptCreateRequest): Promise<Attempt>;
    updateAttempt(
      problemId: string,
      attemptId: string,
      payload: AttemptUpdateRequest,
    ): Promise<Attempt>;
    getNotes(problemId: string): Promise<ProblemNotes | null>;
    upsertNotes(problemId: string, payload: ProblemNotesUpsert): Promise<ProblemNotes>;
    listCode(problemId: string): Promise<CodeSnippet[]>;
    createCode(problemId: string, payload: CodeSnippetCreate): Promise<CodeSnippet>;
    updateCode(
      problemId: string,
      snippetId: string,
      payload: CodeSnippetUpdate,
    ): Promise<CodeSnippet>;
    deleteCode(problemId: string, snippetId: string): Promise<DeletedResponse>;
    scheduleRevision(problemId: string, payload: RevisionCreateRequest): Promise<Revision>;
  };

  revisions: {
    list(params?: RevisionListParams): Promise<Page<Revision>>;
    summary(): Promise<RevisionSummary>;
    complete(revisionId: string, payload: RevisionCompleteRequest): Promise<RevisionCompleteResponse>;
    promoteStale(limit?: number): Promise<{ queued: number; message: string }>;
  };

  lld: {
    listTopics(params?: TopicListParams & LLDTopicFilters): Promise<Page<LLDTopicSummary>>;
    getTopic(topicId: string): Promise<LLDTopicDetail>;
    updateProgress(
      topicId: string,
      payload: LLDProgressUpdateRequest,
    ): Promise<{ topic_id: string; status: string; confidence: number | null }>;
    getNotes(topicId: string): Promise<LLDNotes | null>;
    upsertNotes(topicId: string, payload: LLDNotesUpsert): Promise<LLDNotes>;
    listCode(topicId: string): Promise<LLDSnippet[]>;
    createCode(topicId: string, payload: LLDSnippetCreate): Promise<LLDSnippet>;
    updateCode(topicId: string, snippetId: string, payload: LLDSnippetUpdate): Promise<LLDSnippet>;
    deleteCode(topicId: string, snippetId: string): Promise<DeletedResponse>;
  };

  hld: {
    listTopics(params?: TopicListParams & HLDTopicFilters): Promise<Page<HLDTopicSummary>>;
    getTopic(topicId: string): Promise<HLDTopicDetail>;
    updateProgress(
      topicId: string,
      payload: HLDProgressUpdateRequest,
    ): Promise<{ topic_id: string; status: string; confidence: number | null }>;
    getNotes(topicId: string): Promise<HLDNotes | null>;
    upsertNotes(topicId: string, payload: HLDNotesUpsert): Promise<HLDNotes>;
    listCode(topicId: string): Promise<HLDSnippet[]>;
    createCode(topicId: string, payload: HLDSnippetCreate): Promise<HLDSnippet>;
    updateCode(topicId: string, snippetId: string, payload: HLDSnippetUpdate): Promise<HLDSnippet>;
    deleteCode(topicId: string, snippetId: string): Promise<DeletedResponse>;
  };

  stats: {
    overview(): Promise<StatsOverview>;
    topics(limit?: number): Promise<TopicStatsResponse>;
    difficulty(): Promise<DifficultyStatsResponse>;
    activity(range: ActivityRange): Promise<ActivityResponse>;
    streak(): Promise<StreakResponse>;
    mastery(): Promise<MasteryResponse>;
  };

  ai: {
    chat(payload: AIChatRequest): Promise<AIChatResponse>;
    actions(): Promise<AIActionsResponse>;
    conversations(params?: ConversationListParams): Promise<Page<AIConversationSummary>>;
    conversation(conversationId: string): Promise<AIConversationDetail>;
    deleteConversation(conversationId: string): Promise<DeletedResponse>;
  };

  settings: {
    get(): Promise<UserSettings>;
    update(payload: UserSettingsUpdate): Promise<UserSettings>;
    devices(): Promise<{ items: UserDevice[] }>;
    upsertDevice(payload: {
      device_identifier: string;
      device_type: string;
      display_name?: string;
    }): Promise<UserDevice>;
  };

  sync: {
    status(deviceId?: string): Promise<SyncStatus>;
    push(payload: SyncPushPayload): Promise<{ results: unknown[]; cursor?: number }>;
    pull(params?: SyncPullParams): Promise<{ changes: unknown[]; next_cursor: number; has_more: boolean }>;
  };

  studySessions: {
    start(payload: StudySessionStartRequest): Promise<StudySession>;
    stop(sessionId: string, payload?: StudySessionStopRequest): Promise<StudySession>;
    list(params?: PageParams): Promise<Page<StudySession>>;
    running(): Promise<StudySession | null>;
  };

  search: {
    /**
     * Global search. There is no dedicated endpoint on the server, so the client fans out
     * across the catalogs and notes, then ranks and groups locally.
     */
    query(term: string, kinds?: SearchResultKind[]): Promise<SearchGroup[]>;
  };
}
