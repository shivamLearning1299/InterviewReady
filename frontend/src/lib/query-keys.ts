import type { ActivityRange, AIContextType, UUID } from '@/types/common';
import type { DsaListParams, RevisionListParams, TopicListParams } from '@/api/contract';
/**
 * Centralised TanStack Query keys.
 *
 * Defined once so invalidation is precise: updating progress can invalidate exactly the
 * catalog, that problem, Today and the stats without over-fetching or missing a cache.
 */
export const queryKeys = {
  me: ['me'] as const,

  today: ['today'] as const,
  todayExplain: ['today', 'explain'] as const,
  dailyPlans: (params?: { start_date?: string; end_date?: string }) =>
    ['today', 'daily-plans', params ?? {}] as const,

  dsa: {
    all: ['dsa'] as const,
    problems: (params: DsaListParams) => ['dsa', 'problems', params] as const,
    problem: (problemId: string) => ['dsa', 'problem', problemId] as const,
    topics: ['dsa', 'topics'] as const,
    attempts: (problemId: string) => ['dsa', 'attempts', problemId] as const,
    notes: (problemId: string) => ['dsa', 'notes', problemId] as const,
    code: (problemId: string) => ['dsa', 'code', problemId] as const,
  },

  revisions: {
    all: ['revisions'] as const,
    list: (params: RevisionListParams) => ['revisions', 'list', params] as const,
    summary: ['revisions', 'summary'] as const,
  },

  lld: {
    all: ['lld'] as const,
    topics: (params: TopicListParams) => ['lld', 'topics', params] as const,
    topic: (topicId: string) => ['lld', 'topic', topicId] as const,
    notes: (topicId: string) => ['lld', 'notes', topicId] as const,
    code: (topicId: string) => ['lld', 'code', topicId] as const,
  },

  hld: {
    all: ['hld'] as const,
    topics: (params: TopicListParams) => ['hld', 'topics', params] as const,
    topic: (topicId: string) => ['hld', 'topic', topicId] as const,
    notes: (topicId: string) => ['hld', 'notes', topicId] as const,
    code: (topicId: string) => ['hld', 'code', topicId] as const,
  },

  stats: {
    all: ['stats'] as const,
    overview: ['stats', 'overview'] as const,
    topics: ['stats', 'topics'] as const,
    difficulty: ['stats', 'difficulty'] as const,
    activity: (range: ActivityRange) => ['stats', 'activity', range] as const,
    streak: ['stats', 'streak'] as const,
    mastery: ['stats', 'mastery'] as const,
  },

  ai: {
    all: ['ai'] as const,
    actions: ['ai', 'actions'] as const,
    conversations: (contextType?: AIContextType) => ['ai', 'conversations', contextType ?? 'all'] as const,
    conversation: (conversationId: string) => ['ai', 'conversation', conversationId] as const,
  },

  settings: {
    all: ['settings'] as const,
    detail: ['settings', 'detail'] as const,
    devices: ['settings', 'devices'] as const,
  },

  sync: {
    status: ['sync', 'status'] as const,
  },

  studySessions: {
    all: ['study-sessions'] as const,
    running: ['study-sessions', 'running'] as const,
    list: ['study-sessions', 'list'] as const,
  },
} as const;

/** Route helpers keep links free of hand-written id interpolation. */
export const routes = {
  today: '/',
  dsa: '/dsa',
  dsaProblem: (problemId: string) => `/dsa/${problemId}`,
  revisions: '/revisions',
  lld: '/lld',
  lldTopic: (topicId: string) => `/lld/${topicId}`,
  hld: '/hld',
  hldTopic: (topicId: string) => `/hld/${topicId}`,
  stats: '/stats',
  ai: '/ai',
  aiConversation: (conversationId: UUID) => `/ai/${conversationId}`,
  settings: '/settings',
  login: '/login',
} as const;
