import { useCallback, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from '@/api/client';
import { TIMER } from '@/lib/constants';
import { elapsedSecondsFrom } from '@/lib/format';
import type { SessionType } from '@/types/common';

/**
 * Server-timed study session.
 *
 * The elapsed clock is derived from the server's `started_at`, never from a local start
 * timestamp, so a backgrounded tab (or a device clock skewed by minutes) still reports
 * honest study time. The local ticker only drives the display.
 */
export interface StudyTimer {
  sessionId: string | null;
  /** Seconds elapsed, ticking once per second while running. */
  elapsedSeconds: number;
  isRunning: boolean;
  isStarting: boolean;
  isStopping: boolean;
  /** True once the session exceeds the server's cap and will be truncated. */
  atCap: boolean;
  start: (sessionType: SessionType, contextId?: string | null) => Promise<void>;
  stop: () => Promise<void>;
}

export function useStudyTimer(): StudyTimer {
  const queryClient = useQueryClient();
  const [nowMs, setNowMs] = useState(() => Date.now());

  // Restores the timer after a reload — the server is the source of truth for whether a
  // session is still open.
  const runningQuery = useQuery({
    queryKey: ['study-sessions', 'running'],
    queryFn: () => api.studySessions.running(),
    refetchOnWindowFocus: true,
  });

  const running = runningQuery.data ?? null;

  useEffect(() => {
    if (!running) return;
    const handle = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(handle);
  }, [running]);

  const startMutation = useMutation({
    mutationFn: ({ sessionType, contextId }: { sessionType: SessionType; contextId?: string | null }) =>
      api.studySessions.start({ session_type: sessionType, context_id: contextId ?? null }),
    onSuccess: (session) => {
      queryClient.setQueryData(['study-sessions', 'running'], session);
      setNowMs(Date.now());
    },
  });

  const stopMutation = useMutation({
    mutationFn: (sessionId: string) => api.studySessions.stop(sessionId),
    onSuccess: () => {
      queryClient.setQueryData(['study-sessions', 'running'], null);
      void queryClient.invalidateQueries({ queryKey: ['study-sessions'] });
      void queryClient.invalidateQueries({ queryKey: ['stats'] });
      void queryClient.invalidateQueries({ queryKey: ['today'] });
    },
  });

  const elapsedSeconds = running
    ? Math.min(elapsedSecondsFrom(running.started_at, nowMs), TIMER.maxMinutes * 60)
    : 0;

  const start = useCallback(
    async (sessionType: SessionType, contextId?: string | null) => {
      // Starting while one is already running is a no-op server-side; skip the round trip.
      if (running) return;
      await startMutation.mutateAsync({ sessionType, contextId });
    },
    [running, startMutation],
  );

  const stop = useCallback(async () => {
    if (!running) return;
    await stopMutation.mutateAsync(running.id);
  }, [running, stopMutation]);

  return useMemo<StudyTimer>(
    () => ({
      sessionId: running?.id ?? null,
      elapsedSeconds,
      isRunning: Boolean(running),
      isStarting: startMutation.isPending,
      isStopping: stopMutation.isPending,
      atCap: elapsedSeconds >= TIMER.maxMinutes * 60,
      start,
      stop,
    }),
    [
      running,
      elapsedSeconds,
      startMutation.isPending,
      stopMutation.isPending,
      start,
      stop,
    ],
  );
}
