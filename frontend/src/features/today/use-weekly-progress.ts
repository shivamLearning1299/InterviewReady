import { useMemo } from 'react';

import { useDailyPlans } from '@/hooks/use-api';
import { weekBounds } from '@/features/today/greeting';
import type { WeeklyProgress } from '@/types/today';

/**
 * Weekly rollup.
 *
 * Composed on the client from the daily-plan history plus today's target, because the
 * backend exposes per-day completion but no weekly aggregate endpoint. Deriving it here
 * keeps the number consistent with what the Today screen shows for today.
 */
export function useWeeklyProgress(dailyTarget: number): {
  progress: WeeklyProgress;
  isLoading: boolean;
} {
  const bounds = useMemo(() => weekBounds(7), []);
  const { data, isLoading } = useDailyPlans(bounds);

  const progress = useMemo<WeeklyProgress>(() => {
    const plans = data?.items ?? [];

    const dsaCompleted = plans.reduce((total, plan) => total + (plan.dsa?.completed ?? 0), 0);
    const revisionsCompleted = plans.reduce((total, plan) => total + (plan.revisions?.completed ?? 0), 0);
    const studyMinutes = plans.reduce(
      (total, plan) =>
        total +
        [...(plan.dsa?.items ?? []), ...(plan.lld?.items ?? []), ...(plan.hld?.items ?? [])].reduce(
          (sum, item) => sum + (item.is_completed ? (item.estimated_minutes ?? 0) : 0),
          0,
        ),
      0,
    );

    // "Lessons" = distinct topics that appeared and were completed in the week.
    const lldIds = new Set(
      plans.flatMap((plan) =>
        (plan.lld?.items ?? []).filter((item) => item.is_completed).map((item) => item.topic_id),
      ),
    );
    const hldIds = new Set(
      plans.flatMap((plan) =>
        (plan.hld?.items ?? []).filter((item) => item.is_completed).map((item) => item.topic_id),
      ),
    );

    return {
      dsaCompleted,
      dsaTarget: dailyTarget * 7,
      lldLessons: lldIds.size,
      hldLessons: hldIds.size,
      revisionsCompleted,
      studyMinutes,
    };
  }, [data, dailyTarget]);

  return { progress, isLoading };
}
