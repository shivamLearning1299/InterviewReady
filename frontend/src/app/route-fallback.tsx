import { SkeletonText } from '@/components/ui/skeleton';

/**
 * Suspense fallback for lazily-loaded routes.
 *
 * A page-shaped placeholder rather than a full-screen spinner: the shell stays visible so
 * the transition does not feel like a reload.
 */
export function RouteFallback() {
  return (
    <div className="mx-auto w-full max-w-[1600px] space-y-5 px-4 py-5 sm:px-6" aria-busy="true">
      <div className="space-y-2">
        <div className="h-6 w-48 animate-soft-pulse rounded-md bg-muted" />
        <div className="h-3.5 w-72 animate-soft-pulse rounded-md bg-muted" />
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <div key={index} className="space-y-3 rounded-[var(--radius-card)] border border-border p-4">
            <div className="h-4 w-1/2 animate-soft-pulse rounded-md bg-muted" />
            <SkeletonText lines={2} />
          </div>
        ))}
      </div>
      <div className="rounded-[var(--radius-card)] border border-border">
        <SkeletonText lines={8} className="p-4" />
      </div>
      <span className="sr-only">Loading</span>
    </div>
  );
}
