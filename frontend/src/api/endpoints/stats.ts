import { http } from '@/api/http';
import type {
  ActivityRange,
  ActivityResponse,
  DifficultyStatsResponse,
  MasteryResponse,
  StatsOverview,
  StreakResponse,
  TopicStatsResponse,
} from '@/types/stats';

export const statsEndpoints = {
  overview: () => http.get<StatsOverview>('/stats/overview'),

  topics: (limit?: number) =>
    http.get<TopicStatsResponse>('/stats/dsa/topics', { query: { limit } }),

  difficulty: () => http.get<DifficultyStatsResponse>('/stats/dsa/difficulty'),

  activity: (range: ActivityRange) =>
    http.get<ActivityResponse>('/stats/activity', { query: { range } }),

  streak: () => http.get<StreakResponse>('/stats/streak'),

  mastery: () => http.get<MasteryResponse>('/stats/mastery'),
};
