/**
 * In-memory implementation of {@link ApiClient}.
 *
 * This is not a stub that returns fixed strings — it maintains the same state transitions
 * the backend does. Solving a problem updates the catalog row, the revision ladder and the
 * statistics together, which is what makes the UI verifiable before the backend is wired up.
 */

import { ApiError } from '@/api/errors';
import type {
  ApiClient,
  ConversationListParams,
  DsaListParams,
  PageParams,
  PlanListParams,
  RevisionListParams,
  TopicListParams,
} from '@/api/contract';
import { generateReply } from '@/mocks/ai-responder';
import {
  addDays,
  dayKey,
  isoAtOffsetDays,
  isoNow,
  seededInt,
  startOfDay,
  todayKey,
} from '@/mocks/deterministic';
import {
  DEMO_USER_ID,
  DONE_STATUSES,
  SOLVED_STATUSES,
  TOPIC_DONE,
  buildActivitySeries,
  buildDifficultyBreakdowns,
  buildDsaTopicOptions,
  buildStreak,
  buildToday,
  buildTopicBreakdowns,
  resetStore,
  simulateLatency,
  store,
  type Store,
} from '@/mocks/store';
import type {
  AIContextType,
  DeletedResponse,
  Difficulty,
  Page,
  ProblemStatus,
  TopicStatus,
} from '@/types/common';
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
  RevisionCompleteRequest,
  RevisionCompleteResponse,
  RevisionCreateRequest,
} from '@/types/dsa';
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
import type {
  StudySession,
  StudySessionStartRequest,
  StudySessionStopRequest,
  UserDevice,
  UserSettings,
  UserSettingsUpdate,
} from '@/types/settings';
import type { AIActionsResponse, AIChatRequest, AIChatResponse, AIMessage } from '@/types/ai';
import type { DailyPlanDetail, PlanGenerationDebug, TodayResponse } from '@/types/today';
import type {
  ActivityRange,
  ActivityResponse,
  MasteryResponse,
  StatsOverview,
  StreakResponse,
  TopicStatsResponse,
} from '@/types/stats';

// ------------------------------------------------------------------- utilities

function paginate<T>(items: T[], params: PageParams = {}): Page<T> {
  const limit = params.limit ?? 50;
  const offset = params.offset ?? 0;
  return { items: items.slice(offset, offset + limit), total: items.length, limit, offset };
}

function matches(value: string | null | undefined, term: string): boolean {
  return (value ?? '').toLowerCase().includes(term.toLowerCase());
}

function notFound(entity: string, id: string): ApiError {
  return new ApiError(`${entity} not found: ${id}`, `${entity.toUpperCase().replace(/\s+/g, '_')}_NOT_FOUND`, 404);
}

function findProblem(db: Store, problemId: string): DSAProblemSummary {
  const problem = db.problems.find((candidate) => candidate.id === problemId);
  if (!problem) throw notFound('Problem', problemId);
  return problem;
}

function touch<T extends { updated_at: string; version: number }>(record: T): T {
  record.updated_at = isoNow();
  record.version += 1;
  return record;
}

/** Status transitions the server derives dates from — mirrored here. */
function nextRevisionDate(status: ProblemStatus, confidence: number | null): string | null {
  if (status === 'needs_revision') return isoAtOffsetDays(1, 9);
  if (status === 'not_started') return null;
  const ladder = [1, 2, 4, 7, 14, 30];
  const index = Math.max(0, Math.min(ladder.length - 1, (confidence ?? 1) - 1));
  return isoAtOffsetDays(ladder[index] ?? 1, 9);
}

function progressResponseFor(problem: DSAProblemSummary): ProgressResponse {
  const progress = problem.progress;
  return {
    id: `progress-${problem.id}`,
    created_at: problem.created_at,
    updated_at: problem.updated_at,
    version: problem.version,
    user_id: DEMO_USER_ID,
    problem_id: problem.id,
    status: progress.status,
    attempts: progress.attempts,
    confidence: progress.confidence,
    revision_count: [...store.revisions.values()].filter((revision) => revision.problem_id === problem.id).length,
    first_attempt_at: progress.attempts > 0 ? problem.created_at : null,
    solved_at: progress.solved_at,
    last_reviewed_at: progress.status === 'mastered' ? isoAtOffsetDays(-6, 20) : null,
    next_revision_at: progress.next_revision_at,
    total_time_spent_minutes: progress.total_time_spent_minutes,
    is_favorite: progress.is_favorite,
  };
}

/** Applies a status change, scheduling or clearing the revision queue exactly as the API does. */
function applyStatusChange(db: Store, problem: DSAProblemSummary, status: ProblemStatus, confidence?: number | null): void {
  const progress = problem.progress;
  progress.status = status;
  if (confidence !== undefined) progress.confidence = confidence;
  if (status === 'solved' || status === 'mastered') {
    progress.solved_at = progress.solved_at ?? isoNow();
  }
  if (status === 'not_started') {
    progress.solved_at = null;
  }
  progress.next_revision_at = nextRevisionDate(status, progress.confidence);

  // Only one open revision per problem: reschedule rather than stack.
  const existing = [...db.revisions.values()].find(
    (revision) => revision.problem_id === problem.id && !revision.completed,
  );
  if (existing) {
    if (status === 'needs_revision') {
      existing.due_at = isoAtOffsetDays(1, 9);
      existing.priority = 1;
      existing.reason = 'failed_attempt';
      touch(existing);
    } else if (progress.next_revision_at) {
      existing.due_at = progress.next_revision_at;
      existing.priority = 3;
      existing.reason = 'scheduled_revision';
      touch(existing);
    } else {
      existing.completed = true;
      existing.completed_at = isoNow();
      existing.result = 'success';
      touch(existing);
    }
    problem.progress = progress;
    return;
  }

  if (status === 'needs_revision' || (status !== 'not_started' && progress.next_revision_at)) {
    const id = db.seq();
    db.revisions.set(id, {
      id,
      created_at: isoNow(),
      updated_at: isoNow(),
      version: 1,
      user_id: DEMO_USER_ID,
      problem_id: problem.id,
      due_at: progress.next_revision_at ?? isoAtOffsetDays(1, 9),
      reason: status === 'needs_revision' ? 'failed_attempt' : 'scheduled_revision',
      priority: status === 'needs_revision' ? 1 : 3,
      completed: false,
      completed_at: null,
      result: null,
      confidence_before: progress.confidence,
      interval_days: 1,
      notes: null,
      problem_title: problem.title,
      problem_slug: problem.slug,
      problem_difficulty: problem.difficulty,
      problem_topic: problem.primary_topic,
    });
  }
  problem.progress = progress;
}

function buildProblemDetail(db: Store, problem: DSAProblemSummary): DSAProblemDetail {
  const notes = db.notes.get(problem.id) ?? null;
  return {
    ...problem,
    hints: null,
    progress: problem.progress,
    notes,
    code_snippets: db.snippets.get(problem.id) ?? [],
    attempts: db.attempts.get(problem.id) ?? [],
    revisions: [...db.revisions.values()].filter((revision) => revision.problem_id === problem.id),
  };
}

function emptyNotesFor(problemId: string, seq: () => string): ProblemNotes {
  return {
    id: seq(),
    created_at: isoNow(),
    updated_at: isoNow(),
    version: 1,
    user_id: DEMO_USER_ID,
    problem_id: problemId,
    approach: null,
    notes: null,
    mistakes: null,
    revision_notes: null,
    time_complexity: null,
    space_complexity: null,
  };
}

function planDetailFor(db: Store, planDate: string): DailyPlanDetail {
  const today = buildToday(db);
  const isToday = planDate === todayKey();
  const completed = db.planCompletion.get(planDate) ?? new Set<string>();

  const scale = (section: typeof today.dsa) => ({
    completed: isToday ? section.completed : Math.max(0, section.total - seededInt(`${planDate}:${section.total}`, 0, section.total)),
    total: section.total,
    items: section.items.map((item) => ({
      ...item,
      is_completed: isToday ? item.is_completed : completed.has(item.id),
    })),
  });

  const dsa = scale(today.dsa);
  const lld = scale(today.lld);
  const hld = scale(today.hld);
  const revisions = scale(today.revisions);

  return {
    id: `00000000-0000-4000-8000-00000000d${planDate.replace(/-/g, '').slice(2)}`,
    created_at: `${planDate}T06:00:00.000Z`,
    updated_at: isoNow(),
    version: 1,
    user_id: DEMO_USER_ID,
    plan_date: planDate,
    timezone: db.settings.timezone,
    status: 'active',
    generated_by: 'scheduler_v1',
    total_items: dsa.total + lld.total + hld.total,
    completed_items: dsa.completed + lld.completed + hld.completed,
    dsa,
    lld,
    hld,
    revisions,
  };
}

function topicProgressResponse(
  topicId: string,
  status: TopicStatus,
  confidence: number | null,
): { topic_id: string; status: string; confidence: number | null } {
  return { topic_id: topicId, status, confidence };
}

function applyTopicStatus(db: Store, kind: 'lld' | 'hld', topicId: string, status: TopicStatus, confidence?: number | null): void {
  const progressMap = kind === 'lld' ? db.lldProgress : db.hldProgress;
  const confidenceMap = kind === 'lld' ? db.lldConfidence : db.hldConfidence;
  const topics = kind === 'lld' ? db.lldTopics : db.hldTopics;

  progressMap.set(topicId, status);
  if (confidence !== undefined && confidence !== null) confidenceMap.set(topicId, confidence);

  const topic = topics.find((candidate) => candidate.id === topicId);
  if (!topic) return;

  const value = confidenceMap.get(topicId) ?? 0;
  topic.progress = {
    status,
    confidence: value || null,
    completed_at: TOPIC_DONE.has(status) ? (topic.progress.completed_at ?? isoNow()) : null,
    next_revision_at:
      status === 'needs_revision'
        ? isoAtOffsetDays(1, 9)
        : TOPIC_DONE.has(status)
          ? isoAtOffsetDays([1, 2, 4, 7, 14, 30][Math.max(0, Math.min(5, value - 1))] ?? 7, 9)
          : null,
    last_reviewed_at: TOPIC_DONE.has(status) ? isoNow() : topic.progress.last_reviewed_at,
    total_time_spent_minutes: TOPIC_DONE.has(status)
      ? Math.max(topic.progress.total_time_spent_minutes, topic.estimated_minutes)
      : topic.progress.total_time_spent_minutes,
  };
}

// ------------------------------------------------------------------- the client

export const mockClient: ApiClient = {
  mode: 'mock',

  users: {
    async me() {
      await simulateLatency();
      return { id: DEMO_USER_ID, email: 'shivam@interviewready.dev' };
    },

    async exportData() {
      await simulateLatency(400);
      const payload = {
        exported_at: isoNow(),
        user_id: DEMO_USER_ID,
        schema_version: 1,
        problem_progress: [...store.progress.entries()].map(([problemId, progress]) => ({ problem_id: problemId, ...progress })),
        attempt_history: [...store.attempts.values()].flat(),
        notes: [...store.notes.values()],
        code_snippets: [...store.snippets.values()].flat(),
        revisions: [...store.revisions.values()],
        study_sessions: store.sessions,
        daily_plans: [planDetailFor(store, todayKey())],
        settings: store.settings,
      };
      return new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    },
  },

  today: {
    async get(): Promise<TodayResponse> {
      await simulateLatency();
      return buildToday(store);
    },

    async explain(): Promise<PlanGenerationDebug> {
      await simulateLatency();
      const weak = buildTopicBreakdowns(store)
        .filter((topic) => topic.completion_percentage < 60)
        .slice(0, 3)
        .map((topic) => topic.topic);
      return {
        candidate_count: store.problems.length,
        new_problem_count: buildToday(store).dsa.total,
        revision_count: [...store.revisions.values()].filter((revision) => !revision.completed).length,
        weak_topics: weak,
        covered_topics: buildToday(store).dsa.items.map((item) => item.primary_topic ?? ''),
        scoring_version: 'scheduler_v1',
        explanation: {
          strategy: 'weak-topic first, then pattern variety, then revision pressure',
          daily_dsa_count: store.settings.daily_dsa_count,
        },
      };
    },

    async listPlans(params: PlanListParams = {}): Promise<Page<DailyPlanDetail>> {
      await simulateLatency();
      const plans: DailyPlanDetail[] = [];
      for (let offset = 0; offset < 30; offset += 1) {
        const date = dayKey(addDays(new Date(), -offset));
        if (params.start_date && date < params.start_date) continue;
        if (params.end_date && date > params.end_date) continue;
        plans.push(planDetailFor(store, date));
      }
      return paginate(plans, params);
    },

    async getPlan(planDate: string): Promise<TodayResponse> {
      await simulateLatency();
      const today = buildToday(store);
      if (planDate === todayKey()) return today;
      const detail = planDetailFor(store, planDate);
      return {
        ...today,
        date: planDate,
        dsa: detail.dsa,
        lld: detail.lld,
        hld: detail.hld,
        revisions: detail.revisions,
        plan_id: detail.id,
      };
    },

    async setItemCompletion(itemId: string, isCompleted: boolean): Promise<DailyPlanDetail> {
      await simulateLatency();
      store.planItemState.set(itemId, isCompleted);
      const date = itemId.split(':')[0] ?? todayKey();
      const completion = store.planCompletion.get(date) ?? new Set<string>();
      if (isCompleted) completion.add(itemId);
      else completion.delete(itemId);
      store.planCompletion.set(date, completion);
      return planDetailFor(store, date);
    },

    async removeItem(itemId: string): Promise<DeletedResponse> {
      await simulateLatency();
      const date = itemId.split(':')[0] ?? todayKey();
      store.planCompletion.get(date)?.delete(itemId);
      store.planItemState.set(itemId, false);
      return { id: itemId, message: 'Plan item removed' };
    },
  },

  dsa: {
    async listProblems(params: DsaListParams = {}): Promise<Page<DSAProblemSummary>> {
      await simulateLatency();
      let items = [...store.problems];

      if (params.search) {
        const term = params.search;
        items = items.filter(
          (problem) =>
            matches(problem.title, term) ||
            matches(problem.slug, term) ||
            matches(problem.primary_topic, term),
        );
      }
      if (params.topic) items = items.filter((problem) => problem.primary_topic === params.topic);
      if (params.pattern) items = items.filter((problem) => problem.patterns.includes(params.pattern!));
      if (params.difficulty && params.difficulty !== 'all') {
        items = items.filter((problem) => problem.difficulty === params.difficulty);
      }
      if (params.status && params.status !== 'all') {
        items = items.filter((problem) => problem.progress.status === params.status);
      }
      if (params.company) items = items.filter((problem) => problem.companies.includes(params.company!));
      if (params.source) items = items.filter((problem) => problem.source === params.source);
      if (params.favorites_only) items = items.filter((problem) => problem.progress.is_favorite);
      if (params.revision_due) {
        const now = Date.now();
        items = items.filter(
          (problem) =>
            problem.progress.next_revision_at !== null &&
            new Date(problem.progress.next_revision_at).getTime() <= now,
        );
      }

      const difficultyRank: Record<Difficulty, number> = { easy: 0, medium: 1, hard: 2 };
      switch (params.order_by) {
        case 'title':
          items.sort((a, b) => a.title.localeCompare(b.title));
          break;
        case 'difficulty':
          items.sort((a, b) => difficultyRank[a.difficulty] - difficultyRank[b.difficulty]);
          break;
        case 'importance':
          items.sort((a, b) => b.importance - a.importance);
          break;
        case 'recent':
          items.sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
          break;
        default:
          items.sort((a, b) => a.order_index - b.order_index);
      }

      return paginate(items, params);
    },

    async getProblem(problemId: string): Promise<DSAProblemDetail> {
      await simulateLatency();
      return buildProblemDetail(store, findProblem(store, problemId));
    },

    async listTopics() {
      await simulateLatency();
      return { items: buildDsaTopicOptions(store.problems) };
    },

    async updateProgress(problemId: string, payload: ProgressUpdateRequest): Promise<ProgressResponse> {
      await simulateLatency();
      const problem = findProblem(store, problemId);
      const progress = problem.progress;

      if (payload.attempts !== undefined) progress.attempts = payload.attempts;
      if (payload.confidence !== undefined) progress.confidence = payload.confidence;
      if (payload.is_favorite !== undefined) progress.is_favorite = payload.is_favorite;
      if (payload.time_spent_minutes) {
        progress.total_time_spent_minutes += payload.time_spent_minutes;
      }

      const status = payload.status;
      if (status) {
        applyStatusChange(store, problem, status, payload.confidence);
      } else if (payload.schedule_revision) {
        progress.next_revision_at = nextRevisionDate(progress.status, progress.confidence);
      }

      if (payload.notes !== undefined) {
        const notes = store.notes.get(problemId) ?? emptyNotesFor(problemId, store.seq);
        notes.notes = payload.notes;
        store.notes.set(problemId, touch(notes));
      }

      touch(problem);
      return progressResponseFor(problem);
    },

    async listAttempts(problemId: string, params: PageParams = {}): Promise<Page<Attempt>> {
      await simulateLatency();
      findProblem(store, problemId);
      return paginate(store.attempts.get(problemId) ?? [], params);
    },

    async createAttempt(problemId: string, payload: AttemptCreateRequest): Promise<Attempt> {
      await simulateLatency();
      const problem = findProblem(store, problemId);
      const attempt: Attempt = {
        id: store.seq(),
        created_at: isoNow(),
        updated_at: isoNow(),
        version: 1,
        user_id: DEMO_USER_ID,
        problem_id: problemId,
        started_at: payload.started_at ?? isoNow(-(payload.duration_minutes ?? 25)),
        completed_at: payload.completed_at ?? isoNow(),
        duration_minutes: payload.duration_minutes ?? 25,
        outcome: payload.outcome ?? null,
        notes: payload.notes ?? null,
        confidence: payload.confidence ?? problem.progress.confidence,
      };

      const list = store.attempts.get(problemId) ?? [];
      store.attempts.set(problemId, [attempt, ...list]);

      if (payload.update_progress !== false) {
        problem.progress.attempts += 1;
        problem.progress.total_time_spent_minutes += attempt.duration_minutes ?? 0;
        if (payload.confidence !== undefined) problem.progress.confidence = payload.confidence;

        switch (payload.outcome) {
          case 'solved':
            applyStatusChange(store, problem, 'solved', payload.confidence ?? problem.progress.confidence);
            break;
          case 'solved_with_hint':
            applyStatusChange(store, problem, 'attempted', payload.confidence ?? problem.progress.confidence);
            break;
          case 'gave_up':
          case 'revision_failed':
            applyStatusChange(store, problem, 'needs_revision', payload.confidence ?? problem.progress.confidence);
            break;
          case 'revision_success':
            applyStatusChange(store, problem, 'mastered', payload.confidence ?? problem.progress.confidence);
            break;
          case 'partial':
            applyStatusChange(store, problem, 'attempted', payload.confidence ?? problem.progress.confidence);
            break;
          default:
            break;
        }
        touch(problem);
      }

      return attempt;
    },

    async updateAttempt(problemId: string, attemptId: string, payload: AttemptUpdateRequest): Promise<Attempt> {
      await simulateLatency();
      const list = store.attempts.get(problemId) ?? [];
      const attempt = list.find((candidate) => candidate.id === attemptId);
      if (!attempt) throw notFound('Attempt', attemptId);
      Object.assign(attempt, {
        outcome: payload.outcome ?? attempt.outcome,
        duration_minutes: payload.duration_minutes ?? attempt.duration_minutes,
        notes: payload.notes ?? attempt.notes,
        confidence: payload.confidence ?? attempt.confidence,
      });
      return touch(attempt);
    },

    async getNotes(problemId: string): Promise<ProblemNotes | null> {
      await simulateLatency();
      findProblem(store, problemId);
      return store.notes.get(problemId) ?? null;
    },

    async upsertNotes(problemId: string, payload: ProblemNotesUpsert): Promise<ProblemNotes> {
      await simulateLatency();
      findProblem(store, problemId);
      const existing = store.notes.get(problemId) ?? emptyNotesFor(problemId, store.seq);
      const merged: ProblemNotes = {
        ...existing,
        ...Object.fromEntries(Object.entries(payload).filter(([, value]) => value !== undefined)),
      };
      store.notes.set(problemId, touch(merged));
      return store.notes.get(problemId)!;
    },

    async listCode(problemId: string): Promise<CodeSnippet[]> {
      await simulateLatency();
      findProblem(store, problemId);
      return (store.snippets.get(problemId) ?? []).filter((snippet) => !store.deletedSnippets.has(snippet.id));
    },

    async createCode(problemId: string, payload: CodeSnippetCreate): Promise<CodeSnippet> {
      await simulateLatency();
      findProblem(store, problemId);
      const snippet: CodeSnippet = {
        id: store.seq(),
        created_at: isoNow(),
        updated_at: isoNow(),
        version: 1,
        user_id: DEMO_USER_ID,
        context_type: 'dsa',
        context_id: problemId,
        problem_id: problemId,
        title: payload.title ?? 'Solution',
        language: payload.language,
        code: payload.code,
        is_primary: payload.is_primary ?? false,
      };
      const list = store.snippets.get(problemId) ?? [];
      if (snippet.is_primary) list.forEach((item) => (item.is_primary = false));
      store.snippets.set(problemId, [...list, snippet]);
      return snippet;
    },

    async updateCode(problemId: string, snippetId: string, payload: CodeSnippetUpdate): Promise<CodeSnippet> {
      await simulateLatency();
      const list = store.snippets.get(problemId) ?? [];
      const snippet = list.find((candidate) => candidate.id === snippetId);
      if (!snippet) throw notFound('Code snippet', snippetId);

      if (payload.code !== undefined) snippet.code = payload.code;
      if (payload.language !== undefined) snippet.language = payload.language;
      if (payload.title !== undefined) snippet.title = payload.title;
      if (payload.is_primary !== undefined) {
        if (payload.is_primary) list.forEach((item) => (item.is_primary = false));
        snippet.is_primary = payload.is_primary;
      }
      return touch(snippet);
    },

    async deleteCode(problemId: string, snippetId: string): Promise<DeletedResponse> {
      await simulateLatency();
      store.deletedSnippets.add(snippetId);
      store.snippets.set(
        problemId,
        (store.snippets.get(problemId) ?? []).filter((snippet) => snippet.id !== snippetId),
      );
      return { id: snippetId, message: 'Code snippet deleted' };
    },

    async scheduleRevision(problemId: string, payload: RevisionCreateRequest): Promise<Revision> {
      await simulateLatency();
      const problem = findProblem(store, problemId);
      const existing = [...store.revisions.values()].find(
        (revision) => revision.problem_id === problemId && !revision.completed,
      );
      const dueAt = payload.due_at ?? isoAtOffsetDays(3, 9);

      if (existing) {
        existing.due_at = dueAt;
        existing.reason = payload.reason ?? existing.reason;
        existing.priority = payload.priority ?? existing.priority;
        existing.notes = payload.notes ?? existing.notes;
        return touch(existing);
      }

      const id = store.seq();
      const revision: Revision = {
        id,
        created_at: isoNow(),
        updated_at: isoNow(),
        version: 1,
        user_id: DEMO_USER_ID,
        problem_id: problemId,
        due_at: dueAt,
        reason: payload.reason ?? 'manual',
        priority: payload.priority ?? 3,
        completed: false,
        completed_at: null,
        result: null,
        confidence_before: problem.progress.confidence,
        interval_days: 3,
        notes: payload.notes ?? null,
        problem_title: problem.title,
        problem_slug: problem.slug,
        problem_difficulty: problem.difficulty,
        problem_topic: problem.primary_topic,
      };
      store.revisions.set(id, revision);
      problem.progress.next_revision_at = dueAt;
      return revision;
    },
  },

  revisions: {
    async list(params: RevisionListParams = {}): Promise<Page<Revision>> {
      await simulateLatency();
      const now = new Date();
      let items = [...store.revisions.values()].filter((revision) =>
        params.completed === null ? true : revision.completed === (params.completed ?? false),
      );

      if (params.bucket === 'due') {
        items = items.filter((revision) => new Date(revision.due_at) <= now);
      } else if (params.bucket === 'overdue') {
        items = items.filter((revision) => startOfDay(new Date(revision.due_at)) < startOfDay(now));
      } else if (params.bucket === 'upcoming') {
        items = items.filter((revision) => new Date(revision.due_at) > now);
      }

      items.sort((a, b) => {
        if (a.priority !== b.priority) return a.priority - b.priority;
        return a.due_at < b.due_at ? -1 : 1;
      });

      return paginate(items, params);
    },

    async summary() {
      await simulateLatency();
      const now = new Date();
      const open = [...store.revisions.values()].filter((revision) => !revision.completed);
      const due = open.filter((revision) => new Date(revision.due_at) <= now);
      const overdue = due.filter((revision) => startOfDay(new Date(revision.due_at)) < startOfDay(now));
      return {
        due: due.length,
        overdue: overdue.length,
        due_today: due.length - overdue.length,
        upcoming: open.length - due.length,
      };
    },

    async complete(revisionId: string, payload: RevisionCompleteRequest): Promise<RevisionCompleteResponse> {
      await simulateLatency();
      const revision = store.revisions.get(revisionId);
      if (!revision) throw notFound('Revision', revisionId);

      // Idempotent, exactly like the server: completing twice does not advance the ladder.
      if (revision.completed) {
        const problem = store.problems.find((candidate) => candidate.id === revision.problem_id);
        return {
          revision,
          progress: problem ? progressResponseFor(problem) : null,
          next_revision: null,
          interval_days: revision.interval_days,
          message: 'Revision already recorded',
        };
      }

      const problem = store.problems.find((candidate) => candidate.id === revision.problem_id);
      revision.completed = true;
      revision.completed_at = isoNow();
      revision.result = payload.result;
      revision.confidence_before = problem?.progress.confidence ?? revision.confidence_before;
      touch(revision);

      let nextRevision: Revision | null = null;
      let intervalDays: number | null = null;

      if (problem && payload.schedule_next !== false) {
        const confidence = payload.confidence ?? Math.max(1, (problem.progress.confidence ?? 2) + (payload.result === 'success' ? 1 : -1));

        if (payload.result === 'failed') {
          applyStatusChange(store, problem, 'needs_revision', Math.max(0, confidence - 1));
          intervalDays = 1;
        } else if (payload.result === 'partial') {
          applyStatusChange(store, problem, 'needs_revision', confidence);
          intervalDays = 2;
        } else {
          const ladder = [2, 4, 7, 14, 30, 60];
          intervalDays = ladder[Math.max(0, Math.min(5, confidence - 1))] ?? 4;
          const status: ProblemStatus = Math.min(5, confidence) >= 5 ? 'mastered' : 'solved';
          applyStatusChange(store, problem, status, Math.min(5, confidence));
          const created = [...store.revisions.values()].find(
            (candidate) => candidate.problem_id === problem.id && !candidate.completed,
          );
          if (created) {
            created.due_at = isoAtOffsetDays(intervalDays, 9);
            created.interval_days = intervalDays;
            created.reason = 'scheduled_revision';
            nextRevision = touch(created);
          }
        }

        problem.progress.next_revision_at = isoAtOffsetDays(intervalDays ?? 1, 9);
        touch(problem);
      }

      return {
        revision,
        progress: problem ? progressResponseFor(problem) : null,
        next_revision: nextRevision,
        interval_days: intervalDays,
        message: payload.result === 'failed' ? 'Queued for review tomorrow' : 'Revision recorded',
      };
    },

    async promoteStale(limit = 10) {
      await simulateLatency();
      const now = Date.now();
      const stale = store.problems.filter(
        (problem) =>
          SOLVED_STATUSES.includes(problem.progress.status) &&
          problem.progress.solved_at !== null &&
          now - new Date(problem.progress.solved_at).getTime() > 14 * 24 * 60 * 60 * 1000 &&
          ![...store.revisions.values()].some((revision) => revision.problem_id === problem.id && !revision.completed),
      );

      const queued = stale.slice(0, limit);
      queued.forEach((problem, index) => {
        const id = store.seq();
        const dueAt = isoAtOffsetDays(index % 3, 9);
        store.revisions.set(id, {
          id,
          created_at: isoNow(),
          updated_at: isoNow(),
          version: 1,
          user_id: DEMO_USER_ID,
          problem_id: problem.id,
          due_at: dueAt,
          reason: 'long_time_since_review',
          priority: 3,
          completed: false,
          completed_at: null,
          result: null,
          confidence_before: problem.progress.confidence,
          interval_days: 14,
          notes: null,
          problem_title: problem.title,
          problem_slug: problem.slug,
          problem_difficulty: problem.difficulty,
          problem_topic: problem.primary_topic,
        });
        problem.progress.next_revision_at = dueAt;
      });

      return { queued: queued.length, message: `Queued ${queued.length} stale problem(s) for revision` };
    },
  },

  lld: {
    async listTopics(params: TopicListParams = {}): Promise<Page<LLDTopicSummary>> {
      await simulateLatency();
      let items = [...store.lldTopics];
      if (params.search) {
        items = items.filter(
          (topic) => matches(topic.title, params.search!) || matches(topic.description, params.search!),
        );
      }
      if (params.category && params.category !== 'all') {
        items = items.filter((topic) => topic.category === params.category);
      }
      if (params.status && params.status !== 'all') {
        items = items.filter((topic) => (store.lldProgress.get(topic.id) ?? topic.progress.status) === params.status);
      }
      if (params.order_by === 'title') items.sort((a, b) => a.title.localeCompare(b.title));
      else if (params.order_by === 'recent') items.sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
      else items.sort((a, b) => a.order_index - b.order_index);
      return paginate(items, params);
    },

    async getTopic(topicId: string): Promise<LLDTopicDetail> {
      await simulateLatency();
      const topic = store.lldTopics.find((candidate) => candidate.id === topicId);
      if (!topic) throw notFound('LLD topic', topicId);
      return {
        ...topic,
        learning_objectives: [
          `Explain ${topic.title} without notes`,
          'Identify where it applies in a real design',
          'Implement a minimal working version from scratch',
        ],
        external_url: null,
        progress: {
          ...topic.progress,
          status: store.lldProgress.get(topicId) ?? topic.progress.status,
          confidence: store.lldConfidence.get(topicId) ?? topic.progress.confidence,
        },
        notes: store.lldNotes.get(topicId) ?? null,
        code_snippets: store.lldSnippets.get(topicId) ?? [],
      };
    },

    async updateProgress(topicId: string, payload: LLDProgressUpdateRequest) {
      await simulateLatency();
      const existing = store.lldProgress.get(topicId) ?? 'not_started';
      applyTopicStatus(store, 'lld', topicId, payload.status ?? existing, payload.confidence);
      return topicProgressResponse(
        topicId,
        store.lldProgress.get(topicId) ?? 'not_started',
        store.lldConfidence.get(topicId) ?? null,
      );
    },

    async getNotes(topicId: string): Promise<LLDNotes | null> {
      await simulateLatency();
      return store.lldNotes.get(topicId) ?? null;
    },

    async upsertNotes(topicId: string, payload: LLDNotesUpsert): Promise<LLDNotes> {
      await simulateLatency();
      const existing = store.lldNotes.get(topicId) ?? emptyLldNotes(topicId);
      const merged: LLDNotes = {
        ...existing,
        ...Object.fromEntries(Object.entries(payload).filter(([, value]) => value !== undefined)),
      };
      store.lldNotes.set(topicId, touch(merged));
      return store.lldNotes.get(topicId)!;
    },

    async listCode(topicId: string): Promise<LLDSnippet[]> {
      await simulateLatency();
      return (store.lldSnippets.get(topicId) ?? []).filter((snippet) => !store.deletedSnippets.has(snippet.id));
    },

    async createCode(topicId: string, payload: LLDSnippetCreate): Promise<LLDSnippet> {
      await simulateLatency();
      const snippet: LLDSnippet = {
        id: store.seq(),
        created_at: isoNow(),
        updated_at: isoNow(),
        version: 1,
        user_id: DEMO_USER_ID,
        context_type: 'lld',
        context_id: topicId,
        title: payload.title ?? 'Implementation',
        language: payload.language,
        code: payload.code,
        is_primary: payload.is_primary ?? false,
      };
      store.lldSnippets.set(topicId, [...(store.lldSnippets.get(topicId) ?? []), snippet]);
      return snippet;
    },

    async updateCode(topicId: string, snippetId: string, payload: LLDSnippetUpdate): Promise<LLDSnippet> {
      await simulateLatency();
      const list = store.lldSnippets.get(topicId) ?? [];
      const snippet = list.find((candidate) => candidate.id === snippetId);
      if (!snippet) throw notFound('Code snippet', snippetId);
      if (payload.code !== undefined) snippet.code = payload.code;
      if (payload.language !== undefined) snippet.language = payload.language;
      if (payload.title !== undefined) snippet.title = payload.title;
      if (payload.is_primary !== undefined) snippet.is_primary = payload.is_primary;
      return touch(snippet);
    },

    async deleteCode(topicId: string, snippetId: string): Promise<DeletedResponse> {
      await simulateLatency();
      store.deletedSnippets.add(snippetId);
      store.lldSnippets.set(
        topicId,
        (store.lldSnippets.get(topicId) ?? []).filter((snippet) => snippet.id !== snippetId),
      );
      return { id: snippetId, message: 'Code snippet deleted' };
    },
  },

  hld: {
    async listTopics(params: TopicListParams = {}): Promise<Page<HLDTopicSummary>> {
      await simulateLatency();
      let items = [...store.hldTopics];
      if (params.search) {
        items = items.filter(
          (topic) => matches(topic.title, params.search!) || matches(topic.description, params.search!),
        );
      }
      if (params.category && params.category !== 'all') {
        items = items.filter((topic) => topic.category === params.category);
      }
      if (params.status && params.status !== 'all') {
        items = items.filter((topic) => (store.hldProgress.get(topic.id) ?? topic.progress.status) === params.status);
      }
      if (params.order_by === 'title') items.sort((a, b) => a.title.localeCompare(b.title));
      else if (params.order_by === 'recent') items.sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
      else items.sort((a, b) => a.order_index - b.order_index);
      return paginate(items, params);
    },

    async getTopic(topicId: string): Promise<HLDTopicDetail> {
      await simulateLatency();
      const topic = store.hldTopics.find((candidate) => candidate.id === topicId);
      if (!topic) throw notFound('HLD topic', topicId);
      return {
        ...topic,
        learning_objectives: [
          `Explain ${topic.title} under interview time pressure`,
          'Estimate capacity for a realistic scale',
          'Identify the first component to break under load',
        ],
        external_url: null,
        progress: {
          ...topic.progress,
          status: store.hldProgress.get(topicId) ?? topic.progress.status,
          confidence: store.hldConfidence.get(topicId) ?? topic.progress.confidence,
        },
        notes: store.hldNotes.get(topicId) ?? null,
        code_snippets: store.hldSnippets.get(topicId) ?? [],
      };
    },

    async updateProgress(topicId: string, payload: HLDProgressUpdateRequest) {
      await simulateLatency();
      const existing = store.hldProgress.get(topicId) ?? 'not_started';
      applyTopicStatus(store, 'hld', topicId, payload.status ?? existing, payload.confidence);
      return topicProgressResponse(
        topicId,
        store.hldProgress.get(topicId) ?? 'not_started',
        store.hldConfidence.get(topicId) ?? null,
      );
    },

    async getNotes(topicId: string): Promise<HLDNotes | null> {
      await simulateLatency();
      return store.hldNotes.get(topicId) ?? null;
    },

    async upsertNotes(topicId: string, payload: HLDNotesUpsert): Promise<HLDNotes> {
      await simulateLatency();
      const existing = store.hldNotes.get(topicId) ?? emptyHldNotes(topicId);
      const merged: HLDNotes = {
        ...existing,
        ...Object.fromEntries(Object.entries(payload).filter(([, value]) => value !== undefined)),
      };
      store.hldNotes.set(topicId, touch(merged));
      return store.hldNotes.get(topicId)!;
    },

    async listCode(topicId: string): Promise<HLDSnippet[]> {
      await simulateLatency();
      return (store.hldSnippets.get(topicId) ?? []).filter((snippet) => !store.deletedSnippets.has(snippet.id));
    },

    async createCode(topicId: string, payload: HLDSnippetCreate): Promise<HLDSnippet> {
      await simulateLatency();
      const snippet: HLDSnippet = {
        id: store.seq(),
        created_at: isoNow(),
        updated_at: isoNow(),
        version: 1,
        user_id: DEMO_USER_ID,
        context_type: 'hld',
        context_id: topicId,
        title: payload.title ?? 'Diagram',
        language: payload.language,
        code: payload.code,
        is_primary: payload.is_primary ?? false,
      };
      store.hldSnippets.set(topicId, [...(store.hldSnippets.get(topicId) ?? []), snippet]);
      return snippet;
    },

    async updateCode(topicId: string, snippetId: string, payload: HLDSnippetUpdate): Promise<HLDSnippet> {
      await simulateLatency();
      const list = store.hldSnippets.get(topicId) ?? [];
      const snippet = list.find((candidate) => candidate.id === snippetId);
      if (!snippet) throw notFound('Code snippet', snippetId);
      if (payload.code !== undefined) snippet.code = payload.code;
      if (payload.language !== undefined) snippet.language = payload.language;
      if (payload.title !== undefined) snippet.title = payload.title;
      if (payload.is_primary !== undefined) snippet.is_primary = payload.is_primary;
      return touch(snippet);
    },

    async deleteCode(topicId: string, snippetId: string): Promise<DeletedResponse> {
      await simulateLatency();
      store.deletedSnippets.add(snippetId);
      store.hldSnippets.set(
        topicId,
        (store.hldSnippets.get(topicId) ?? []).filter((snippet) => snippet.id !== snippetId),
      );
      return { id: snippetId, message: 'Code snippet deleted' };
    },
  },

  stats: {
    async overview(): Promise<StatsOverview> {
      await simulateLatency();
      const problems = store.problems;
      const solved = problems.filter((problem) => SOLVED_STATUSES.includes(problem.progress.status));
      const weekMinutes = store.sessions
        .filter((session) => new Date(session.started_at).getTime() > Date.now() - 7 * 24 * 60 * 60 * 1000)
        .reduce((total, session) => total + (session.duration_minutes ?? 0), 0);
      const monthMinutes = store.sessions
        .filter((session) => new Date(session.started_at).getTime() > Date.now() - 30 * 24 * 60 * 60 * 1000)
        .reduce((total, session) => total + (session.duration_minutes ?? 0), 0);

      const lldDone = store.lldTopics.filter((topic) =>
        TOPIC_DONE.has(store.lldProgress.get(topic.id) ?? topic.progress.status),
      ).length;
      const hldDone = store.hldTopics.filter((topic) =>
        TOPIC_DONE.has(store.hldProgress.get(topic.id) ?? topic.progress.status),
      ).length;

      const due = [...store.revisions.values()].filter(
        (revision) => !revision.completed && new Date(revision.due_at) <= new Date(),
      );

      return {
        dsa: {
          total: problems.length,
          solved: solved.length,
          mastered: problems.filter((problem) => problem.progress.status === 'mastered').length,
          attempted: problems.filter((problem) => problem.progress.attempts > 0).length,
          needs_revision: problems.filter((problem) => problem.progress.status === 'needs_revision').length,
          not_started: problems.filter((problem) => problem.progress.status === 'not_started').length,
        },
        lld: {
          total: store.lldTopics.length,
          completed: lldDone,
          mastered: store.lldTopics.filter((topic) => (store.lldProgress.get(topic.id) ?? '') === 'mastered').length,
          learning: store.lldTopics.filter((topic) => (store.lldProgress.get(topic.id) ?? '') === 'learning').length,
        },
        hld: {
          total: store.hldTopics.length,
          completed: hldDone,
          mastered: store.hldTopics.filter((topic) => (store.hldProgress.get(topic.id) ?? '') === 'mastered').length,
          learning: store.hldTopics.filter((topic) => (store.hldProgress.get(topic.id) ?? '') === 'learning').length,
        },
        streak: buildStreak(store),
        study_time: {
          today_minutes: store.sessions
            .filter((session) => dayKey(new Date(session.started_at)) === todayKey())
            .reduce((total, session) => total + (session.duration_minutes ?? 0), 0),
          week_minutes: weekMinutes,
          month_minutes: monthMinutes,
          total_minutes: store.sessions.reduce((total, session) => total + (session.duration_minutes ?? 0), 0),
        },
        revision_due: due.length,
        revision_overdue: due.filter((revision) => startOfDay(new Date(revision.due_at)) < startOfDay(new Date())).length,
        problems_solved_today: problems.filter(
          (problem) => problem.progress.solved_at && dayKey(new Date(problem.progress.solved_at)) === todayKey(),
        ).length,
        days_active_last_30: new Set(
          store.sessions
            .filter((session) => new Date(session.started_at).getTime() > Date.now() - 30 * 24 * 60 * 60 * 1000)
            .map((session) => dayKey(new Date(session.started_at))),
        ).size,
      };
    },

    async topics(): Promise<TopicStatsResponse> {
      await simulateLatency();
      const items = buildTopicBreakdowns(store);
      return { items, total: items.length };
    },

    async difficulty() {
      await simulateLatency();
      return { items: buildDifficultyBreakdowns(store) };
    },

    async activity(range: ActivityRange): Promise<ActivityResponse> {
      await simulateLatency();
      const days = range === '7d' ? 7 : range === '30d' ? 30 : range === '90d' ? 90 : 365;
      const items = buildActivitySeries(store, days);
      return {
        range,
        start: items[0]?.date ?? todayKey(),
        end: items[items.length - 1]?.date ?? todayKey(),
        granularity: 'day',
        items,
        totals: {
          problems_attempted: items.reduce((total, point) => total + point.problems_attempted, 0),
          problems_solved: items.reduce((total, point) => total + point.problems_solved, 0),
          revisions_completed: items.reduce((total, point) => total + point.revisions_completed, 0),
          study_minutes: items.reduce((total, point) => total + point.study_minutes, 0),
        },
      };
    },

    async streak(): Promise<StreakResponse> {
      await simulateLatency();
      return { ...buildStreak(store), min_minutes_required: 15, timezone: store.settings.timezone };
    },

    async mastery(): Promise<MasteryResponse> {
      await simulateLatency();
      const count = (topics: LLDTopicSummary[] | HLDTopicSummary[], statuses: Map<string, TopicStatus>) =>
        topics.reduce<Record<string, number>>((accumulator, topic) => {
          const status = statuses.get(topic.id) ?? topic.progress.status;
          accumulator[status] = (accumulator[status] ?? 0) + 1;
          return accumulator;
        }, {});
      return {
        lld: count(store.lldTopics, store.lldProgress),
        hld: count(store.hldTopics, store.hldProgress),
      };
    },
  },

  ai: {
    async chat(payload: AIChatRequest): Promise<AIChatResponse> {
      await simulateLatency(650);

      const conversationId = payload.conversation_id ?? store.seq();
      let conversation = store.conversations.find((candidate) => candidate.id === conversationId);
      const isNew = !conversation;

      if (!conversation) {
        conversation = {
          id: conversationId,
          created_at: isoNow(),
          updated_at: isoNow(),
          version: 1,
          title: payload.message.slice(0, 60),
          context_type: payload.context_type,
          context_id: payload.context_id ?? null,
          context_label: contextLabel(payload.context_type, payload.context_id),
          provider: 'groq',
          model: 'llama-3.3-70b-versatile',
          message_count: 0,
          last_message_at: isoNow(),
          preview: null,
          messages: [],
        };
        store.conversations.unshift(conversation);
      }

      const userMessage = makeMessage('user', payload.message, payload.action ?? 'general', payload.selected_code ?? null);
      conversation.messages.push(userMessage);

      // Hint strength escalates with the number of prior hint replies in this thread.
      const hintLevel = conversation.messages.filter((message) => message.action === 'give_hint').length;
      const context = resolveContext(payload.context_type, payload.context_id ?? null);
      const replyText = generateReply(payload, { ...context, hintLevel });

      const assistantMessage = makeMessage(
        'assistant',
        replyText,
        payload.action ?? 'general',
        payload.selected_code ?? null,
      );
      conversation.messages.push(assistantMessage);
      conversation.message_count = conversation.messages.length;
      conversation.last_message_at = assistantMessage.created_at;
      conversation.preview = replyText.slice(0, 140);
      if (!conversation.title || conversation.title.length < 4) {
        conversation.title = payload.message.slice(0, 60);
      }
      touch(conversation);

      return {
        conversation_id: conversation.id,
        message: assistantMessage,
        context_used: {
          context_type: payload.context_type,
          context_id: payload.context_id ?? null,
          label: conversation.context_label,
          hint_level: hintLevel,
        },
        is_new_conversation: isNew,
      };
    },

    async actions(): Promise<AIActionsResponse> {
      await simulateLatency(120);
      return {
        provider: 'groq',
        model: 'llama-3.3-70b-versatile',
        enabled: true,
        context_types: ['dsa', 'lld', 'hld', 'general'],
        actions: [
          { action: 'give_hint', label: 'Give Hint', description: 'A nudge that gets stronger each time' },
          { action: 'explain_concept', label: 'Explain Concept' },
          { action: 'explain_code', label: 'Explain Selected Code' },
          { action: 'find_bug', label: 'Find Bug' },
          { action: 'complexity', label: 'Explain Complexity' },
          { action: 'alternative_approach', label: 'Alternative Approach' },
          { action: 'interview_me', label: 'Interview Me' },
          { action: 'review_design', label: 'Review My Design' },
          { action: 'solid_check', label: 'Identify SOLID Violations' },
          { action: 'missing_classes', label: 'Suggest Missing Classes' },
          { action: 'review_architecture', label: 'Review Architecture' },
          { action: 'scaling_bottlenecks', label: 'Find Scaling Bottlenecks' },
          { action: 'database_choice', label: 'Review Database Choice' },
          { action: 'api_design_review', label: 'Review API Design' },
          { action: 'challenge_assumptions', label: 'Challenge My Assumptions' },
          { action: 'failure_scenarios', label: 'Suggest Failure Scenarios' },
        ],
      };
    },

    async conversations(params: ConversationListParams = {}) {
      await simulateLatency();
      const items = store.conversations
        .filter((conversation) => !store.deletedConversations.has(conversation.id))
        .filter((conversation) => !params.context_type || conversation.context_type === params.context_type)
        .sort((a, b) => (a.last_message_at ?? '' < (b.last_message_at ?? '') ? 1 : -1));
      return paginate(items, params);
    },

    async conversation(conversationId: string) {
      await simulateLatency();
      const conversation = store.conversations.find((candidate) => candidate.id === conversationId);
      if (!conversation) throw notFound('Conversation', conversationId);
      return conversation;
    },

    async deleteConversation(conversationId: string): Promise<DeletedResponse> {
      await simulateLatency();
      store.deletedConversations.add(conversationId);
      store.conversations = store.conversations.filter((candidate) => candidate.id !== conversationId);
      return { id: conversationId, message: 'Conversation deleted' };
    },
  },

  settings: {
    async get(): Promise<UserSettings> {
      await simulateLatency();
      return store.settings;
    },

    async update(payload: UserSettingsUpdate): Promise<UserSettings> {
      await simulateLatency();
      store.settings = {
        ...store.settings,
        ...Object.fromEntries(Object.entries(payload).filter(([, value]) => value !== undefined)),
      };
      return touch(store.settings);
    },

    async devices(): Promise<{ items: UserDevice[] }> {
      await simulateLatency();
      return { items: store.devices };
    },

    async upsertDevice(payload: {
      device_identifier: string;
      device_type: string;
      display_name?: string;
    }): Promise<UserDevice> {
      await simulateLatency();
      const existing = store.devices.find(
        (device) => device.device_identifier === payload.device_identifier,
      );
      if (existing) {
        existing.last_sync_at = isoNow();
        if (payload.display_name) existing.display_name = payload.display_name;
        return touch(existing);
      }
      const device: UserDevice = {
        id: store.seq(),
        created_at: isoNow(),
        updated_at: isoNow(),
        version: 1,
        user_id: DEMO_USER_ID,
        device_identifier: payload.device_identifier,
        device_type: payload.device_type as UserDevice['device_type'],
        display_name: payload.display_name ?? null,
        last_sync_at: isoNow(),
        last_pull_cursor: 1284,
      };
      store.devices.push(device);
      return device;
    },
  },

  sync: {
    async status(deviceId?: string) {
      await simulateLatency();
      const device = store.devices.find((candidate) => candidate.device_identifier === deviceId);
      return {
        cursor: device?.last_pull_cursor ?? 1284,
        last_change_at: isoNow(-12),
        last_sync_at: device?.last_sync_at ?? isoNow(-25),
        device_id: deviceId ?? 'web-this-browser',
        device_count: store.devices.length,
        pending_changes: 0,
      };
    },

    async push(payload) {
      await simulateLatency();
      // Every mutation is acknowledged as applied — the mock layer has no conflicts to model.
      return {
        results: payload.mutations.map((mutation) => ({
          mutation_id: mutation.mutation_id,
          status: 'applied',
          entity: mutation.entity,
          record_id: mutation.record_id ?? null,
        })),
        cursor: 1285,
      };
    },

    async pull(params = {}) {
      await simulateLatency();
      return { changes: [], next_cursor: params.cursor ?? 0, has_more: false };
    },
  },

  studySessions: {
    async start(payload: StudySessionStartRequest): Promise<StudySession> {
      await simulateLatency();
      // Idempotent: an already-running session is returned rather than duplicated.
      if (store.runningSession) return store.runningSession;

      const session: StudySession = {
        id: store.seq(),
        created_at: isoNow(),
        updated_at: isoNow(),
        version: 1,
        user_id: DEMO_USER_ID,
        session_type: payload.session_type,
        context_id: payload.context_id ?? null,
        started_at: isoNow(),
        ended_at: null,
        duration_minutes: null,
        is_running: true,
        notes: null,
      };
      store.runningSession = session;
      store.sessions.unshift(session);
      return session;
    },

    async stop(sessionId: string, payload: StudySessionStopRequest = {}): Promise<StudySession> {
      await simulateLatency();
      const session =
        store.runningSession?.id === sessionId
          ? store.runningSession
          : store.sessions.find((candidate) => candidate.id === sessionId);

      if (!session) throw notFound('Study session', sessionId);

      // Duration is derived from server-side timestamps, never trusted from the client.
      if (session.is_running) {
        const elapsed = Math.max(1, Math.round((Date.now() - new Date(session.started_at).getTime()) / 60_000));
        session.duration_minutes = Math.min(elapsed, 240);
        session.ended_at = isoNow();
        session.is_running = false;
        session.notes = payload.notes ?? null;
      }
      store.runningSession = null;
      return touch(session);
    },

    async list(params: PageParams = {}) {
      await simulateLatency();
      return paginate([...store.sessions].sort((a, b) => (a.started_at < b.started_at ? 1 : -1)), params);
    },

    async running(): Promise<StudySession | null> {
      await simulateLatency(120);
      return store.runningSession;
    },
  },

  search: {
    async query(term: string, kinds) {
      const { globalSearch } = await import('@/services/search-service');
      return globalSearch(mockClient, term, kinds);
    },
  },
};

// -------------------------------------------------------------------- factories

function makeMessage(
  role: 'user' | 'assistant',
  content: string,
  action: string | null,
  selectedCode: string | null,
): AIMessage {
  return {
    id: store.seq(),
    created_at: isoNow(),
    updated_at: isoNow(),
    version: 1,
    role,
    content,
    action,
    provider: 'groq',
    model: 'llama-3.3-70b-versatile',
    usage: null,
    selected_code: selectedCode,
    error: null,
  };
}

function contextLabel(contextType: AIContextType, contextId?: string | null): string | null {
  if (!contextId || contextType === 'general') return null;
  if (contextType === 'dsa') {
    return store.problems.find((problem) => problem.id === contextId)?.title ?? null;
  }
  const topics = contextType === 'lld' ? store.lldTopics : store.hldTopics;
  return topics.find((topic) => topic.id === contextId)?.title ?? null;
}

/** Mirrors the server: only the entity in focus is loaded, never the whole database. */
function resolveContext(contextType: AIContextType, contextId: string | null) {
  if (!contextId || contextType === 'general') return { label: null, topic: null, patterns: [], difficulty: null };

  if (contextType === 'dsa') {
    const problem = store.problems.find((candidate) => candidate.id === contextId);
    if (!problem) return { label: null, topic: null, patterns: [], difficulty: null };
    return {
      label: problem.title,
      topic: problem.primary_topic,
      patterns: problem.patterns,
      difficulty: problem.difficulty,
    };
  }

  const topics = contextType === 'lld' ? store.lldTopics : store.hldTopics;
  const topic = topics.find((candidate) => candidate.id === contextId);
  if (!topic) return { label: null, topic: null, patterns: [], difficulty: null };
  return {
    label: topic.title,
    topic: topic.category,
    patterns: topic.key_concepts.slice(0, 2),
    difficulty: topic.difficulty,
  };
}

function emptyLldNotes(topicId: string): LLDNotes {
  return {
    id: store.seq(),
    created_at: isoNow(),
    updated_at: isoNow(),
    version: 1,
    user_id: DEMO_USER_ID,
    lld_topic_id: topicId,
    summary: null,
    design_explanation: null,
    class_responsibilities: null,
    relationships: null,
    design_notes: null,
    mistakes: null,
    revision_notes: null,
    patterns_used: [],
    class_diagram: null,
  };
}

function emptyHldNotes(topicId: string): HLDNotes {
  return {
    id: store.seq(),
    created_at: isoNow(),
    updated_at: isoNow(),
    version: 1,
    user_id: DEMO_USER_ID,
    hld_topic_id: topicId,
    functional_requirements: null,
    non_functional_requirements: null,
    capacity_estimation: null,
    apis: null,
    data_model: null,
    high_level_architecture: null,
    database_choice: null,
    caching: null,
    queues: null,
    scaling: null,
    failure_handling: null,
    tradeoffs: null,
    final_notes: null,
    interview_notes: null,
    mistakes: null,
  };
}

/** Exposed so the Settings screen can restore the demo to its seeded state. */
export { resetStore };

/** `DONE_STATUSES` is re-exported for the stats helpers that need the same definition. */
export { DONE_STATUSES };

/** Convenience for the dashboard's weekly rollup. */
export function weeklyRollup(storeRef: Store = store) {
  const today = buildToday(storeRef);
  const weekDsa = storeRef.problems.filter(
    (problem) =>
      problem.progress.solved_at &&
      new Date(problem.progress.solved_at).getTime() > Date.now() - 7 * 24 * 60 * 60 * 1000,
  ).length;

  return {
    dsaCompleted: weekDsa || today.dsa.completed,
    dsaTarget: storeRef.settings.daily_dsa_count * 7,
    lldLessons: storeRef.lldTopics.filter((topic) => TOPIC_DONE.has(storeRef.lldProgress.get(topic.id) ?? 'not_started')).length,
    hldLessons: storeRef.hldTopics.filter((topic) => TOPIC_DONE.has(storeRef.hldProgress.get(topic.id) ?? 'not_started')).length,
    revisionsCompleted: [...storeRef.revisions.values()].filter((revision) => revision.completed).length,
    studyMinutes: storeRef.sessions.reduce((total, session) => total + (session.duration_minutes ?? 0), 0),
  };
}
