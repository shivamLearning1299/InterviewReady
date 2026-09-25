import { lazy, Suspense } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'sonner';

import { AppShell } from '@/app/app-shell/app-shell';
import { RequireAuth } from '@/app/require-auth';
import { RouteFallback } from '@/app/route-fallback';
import { AuthProvider } from '@/providers/auth-provider';
import { SidebarProvider } from '@/providers/sidebar-provider';
import { ThemeProvider, useTheme } from '@/providers/theme-provider';
import { STALE_TIME_MS } from '@/api/config';
import { ApiError } from '@/api/errors';

// Route-level code splitting: the shell and the four most-used screens load eagerly,
// everything else is fetched on demand.
import { TodayPage } from '@/features/today/pages/today-page';
import { DsaCatalogPage } from '@/features/dsa/pages/dsa-catalog-page';
import { ProblemWorkspacePage } from '@/features/dsa/pages/problem-workspace-page';
import { RevisionsPage } from '@/features/revision/pages/revisions-page';

const LldCatalogPage = lazy(() =>
  import('@/features/lld/pages/lld-catalog-page').then((module) => ({ default: module.LldCatalogPage })),
);
const LldWorkspacePage = lazy(() =>
  import('@/features/lld/pages/lld-workspace-page').then((module) => ({ default: module.LldWorkspacePage })),
);
const HldCatalogPage = lazy(() =>
  import('@/features/hld/pages/hld-catalog-page').then((module) => ({ default: module.HldCatalogPage })),
);
const HldWorkspacePage = lazy(() =>
  import('@/features/hld/pages/hld-workspace-page').then((module) => ({ default: module.HldWorkspacePage })),
);
const StatisticsPage = lazy(() =>
  import('@/features/stats/pages/statistics-page').then((module) => ({ default: module.StatisticsPage })),
);
const AiTutorPage = lazy(() =>
  import('@/features/ai/pages/ai-tutor-page').then((module) => ({ default: module.AiTutorPage })),
);
const SettingsPage = lazy(() =>
  import('@/features/settings/pages/settings-page').then((module) => ({ default: module.SettingsPage })),
);
const LoginPage = lazy(() =>
  import('@/features/auth/pages/login-page').then((module) => ({ default: module.LoginPage })),
);
const NotFoundPage = lazy(() =>
  import('@/features/auth/pages/not-found-page').then((module) => ({ default: module.NotFoundPage })),
);

function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: STALE_TIME_MS,
        gcTime: 10 * 60 * 1000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          // Never retry a request the server deliberately rejected.
          if (error instanceof ApiError && !error.isRetryable) return false;
          return failureCount < 2;
        },
      },
      mutations: {
        // Mutations are user-initiated; retrying them silently can duplicate writes.
        retry: 0,
      },
    },
  });
}

const queryClient = createQueryClient();

/** Toast styling follows the app theme rather than sonner's own defaults. */
function ThemedToaster() {
  const { theme } = useTheme();
  return (
    <Toaster
      theme={theme}
      position="bottom-right"
      closeButton
      toastOptions={{
        classNames: {
          toast:
            'rounded-[var(--radius-card)] border border-border bg-surface text-foreground text-[13px] shadow-lg',
          description: 'text-muted-foreground',
          actionButton: 'bg-primary text-primary-foreground',
          cancelButton: 'bg-muted text-muted-foreground',
        },
      }}
    />
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <BrowserRouter>
            <SidebarProvider>
              <Suspense fallback={<RouteFallback />}>
                <Routes>
                  <Route path="/login" element={<LoginPage />} />

                  {/* Every other route is behind authentication. */}
                  <Route
                    element={
                      <RequireAuth>
                        <AppShell />
                      </RequireAuth>
                    }
                  >
                    <Route index element={<TodayPage />} />

                    <Route path="dsa" element={<DsaCatalogPage />} />
                    <Route path="dsa/:problemId" element={<ProblemWorkspacePage />} />

                    <Route path="revisions" element={<RevisionsPage />} />

                    <Route path="lld" element={<LldCatalogPage />} />
                    <Route path="lld/:topicId" element={<LldWorkspacePage />} />

                    <Route path="hld" element={<HldCatalogPage />} />
                    <Route path="hld/:topicId" element={<HldWorkspacePage />} />

                    <Route path="stats" element={<StatisticsPage />} />

                    <Route path="ai" element={<AiTutorPage />} />
                    <Route path="ai/:conversationId" element={<AiTutorPage />} />

                    <Route path="settings" element={<SettingsPage />} />

                    <Route path="404" element={<NotFoundPage />} />
                    <Route path="*" element={<Navigate to="/404" replace />} />
                  </Route>
                </Routes>
              </Suspense>
              <ThemedToaster />
            </SidebarProvider>
          </BrowserRouter>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
