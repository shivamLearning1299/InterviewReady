import type { ApiClient } from '@/api/contract';
import { aiEndpoints } from '@/api/endpoints/ai';
import { todayEndpoints, usersEndpoints } from '@/api/endpoints/core';
import { hldEndpoints, lldEndpoints } from '@/api/endpoints/design';
import { dsaEndpoints } from '@/api/endpoints/dsa';
import { revisionsEndpoints } from '@/api/endpoints/revisions';
import {
  settingsEndpoints,
  studySessionEndpoints,
  syncEndpoints,
} from '@/api/endpoints/settings';
import { statsEndpoints } from '@/api/endpoints/stats';

/**
 * HTTP implementation of {@link ApiClient}.
 *
 * Deliberately thin: every method forwards to an endpoint module, which owns the URL,
 * the query mapping and the response type. Object shorthand is used throughout so the
 * parameter types come from the endpoint functions rather than being restated here.
 */
export const realClient: ApiClient = {
  mode: 'live',

  users: {
    me: usersEndpoints.me,
    exportData: usersEndpoints.exportData,
  },

  today: {
    get: todayEndpoints.get,
    explain: todayEndpoints.explain,
    listPlans: todayEndpoints.listPlans,
    getPlan: todayEndpoints.getPlan,
    setItemCompletion: todayEndpoints.setItemCompletion,
    removeItem: todayEndpoints.removeItem,
  },

  dsa: {
    listProblems: dsaEndpoints.listProblems,
    getProblem: dsaEndpoints.getProblem,
    listTopics: dsaEndpoints.listTopics,
    updateProgress: dsaEndpoints.updateProgress,
    listAttempts: (problemId, params = {}) =>
      dsaEndpoints.listAttempts(problemId, { ...params, limit: params.limit ?? 50 }),
    createAttempt: dsaEndpoints.createAttempt,
    updateAttempt: dsaEndpoints.updateAttempt,
    getNotes: dsaEndpoints.getNotes,
    upsertNotes: dsaEndpoints.upsertNotes,
    listCode: dsaEndpoints.listCode,
    createCode: dsaEndpoints.createCode,
    updateCode: dsaEndpoints.updateCode,
    deleteCode: dsaEndpoints.deleteCode,
    scheduleRevision: dsaEndpoints.scheduleRevision,
  },

  revisions: {
    list: revisionsEndpoints.list,
    summary: revisionsEndpoints.summary,
    complete: revisionsEndpoints.complete,
    promoteStale: revisionsEndpoints.promoteStale,
  },

  lld: {
    listTopics: lldEndpoints.listTopics,
    getTopic: lldEndpoints.getTopic,
    updateProgress: lldEndpoints.updateProgress,
    getNotes: lldEndpoints.getNotes,
    upsertNotes: lldEndpoints.upsertNotes,
    listCode: lldEndpoints.listCode,
    createCode: lldEndpoints.createCode,
    updateCode: lldEndpoints.updateCode,
    deleteCode: lldEndpoints.deleteCode,
  },

  hld: {
    listTopics: hldEndpoints.listTopics,
    getTopic: hldEndpoints.getTopic,
    updateProgress: hldEndpoints.updateProgress,
    getNotes: hldEndpoints.getNotes,
    upsertNotes: hldEndpoints.upsertNotes,
    listCode: hldEndpoints.listCode,
    createCode: hldEndpoints.createCode,
    updateCode: hldEndpoints.updateCode,
    deleteCode: hldEndpoints.deleteCode,
  },

  stats: {
    overview: statsEndpoints.overview,
    topics: statsEndpoints.topics,
    difficulty: statsEndpoints.difficulty,
    activity: statsEndpoints.activity,
    streak: statsEndpoints.streak,
    mastery: statsEndpoints.mastery,
  },

  ai: {
    chat: aiEndpoints.chat,
    actions: aiEndpoints.actions,
    conversations: aiEndpoints.conversations,
    conversation: aiEndpoints.conversation,
    deleteConversation: aiEndpoints.deleteConversation,
  },

  settings: {
    get: settingsEndpoints.get,
    update: settingsEndpoints.update,
    devices: settingsEndpoints.devices,
    upsertDevice: settingsEndpoints.upsertDevice,
  },

  sync: {
    status: syncEndpoints.status,
    push: syncEndpoints.push,
    pull: syncEndpoints.pull,
  },

  studySessions: {
    start: studySessionEndpoints.start,
    stop: studySessionEndpoints.stop,
    list: studySessionEndpoints.list,
    running: studySessionEndpoints.running,
  },

  search: {
    // No server-side search endpoint exists; the catalog routes are fanned out and
    // ranked on the client. See `services/search-service.ts`.
    query: async (term, kinds) => {
      const { globalSearch } = await import('@/services/search-service');
      return globalSearch(realClient, term, kinds);
    },
  },
};
