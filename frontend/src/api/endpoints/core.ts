import { http } from '@/api/http';
import type { Page, UserResponse } from '@/types/common';
import type { DailyPlanDetail, PlanGenerationDebug, TodayResponse } from '@/types/today';
import type { PlanListParams } from '@/api/contract';

export const usersEndpoints = {
  me: () => http.get<UserResponse>('/users/me'),

  async exportData(includeConversations = true): Promise<Blob> {
    const response = await http.get<Response>('/users/export', {
      query: { include_conversations: includeConversations },
      raw: true,
    });
    return response.blob();
  },
};

export const todayEndpoints = {
  get: () => http.get<TodayResponse>('/today'),

  explain: () => http.get<PlanGenerationDebug>('/today/explain'),

  listPlans: (params: PlanListParams = {}) =>
    http.get<Page<DailyPlanDetail>>('/daily-plans', {
      query: {
        limit: params.limit,
        offset: params.offset,
        start_date: params.start_date,
        end_date: params.end_date,
      },
    }),

  getPlan: (planDate: string) => http.get<TodayResponse>(`/daily-plans/${planDate}`),

  setItemCompletion: (itemId: string, isCompleted: boolean) =>
    http.patch<DailyPlanDetail>(`/daily-plans/items/${itemId}`, { is_completed: isCompleted }),

  removeItem: (itemId: string) =>
    http.delete<{ id: string; message: string }>(`/daily-plans/items/${itemId}`),
};
