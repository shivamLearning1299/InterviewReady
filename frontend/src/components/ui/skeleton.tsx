import { cn } from '@/lib/utils';

/**
 * Loading placeholder.
 *
 * Skeletons mirror the shape of the content they replace so the layout does not jump when
 * data arrives. Animation is a slow opacity pulse only — no sweeping gradients.
 */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-soft-pulse rounded-md bg-muted', className)} />;
}

/** A single content row: title line plus a line of metadata. */
export function SkeletonRow({ className }: { className?: string }) {
  return (
    <div className={cn('flex items-center gap-4 px-4 py-3', className)}>
      <Skeleton className="h-4 w-6 shrink-0" />
      <div className="min-w-0 flex-1 space-y-2">
        <Skeleton className="h-3.5 w-2/5" />
        <Skeleton className="h-3 w-1/4" />
      </div>
      <Skeleton className="h-5 w-16 shrink-0" />
      <Skeleton className="h-5 w-20 shrink-0" />
      <Skeleton className="h-7 w-20 shrink-0" />
    </div>
  );
}

export function SkeletonTable({ rows = 8, className }: { rows?: number; className?: string }) {
  return (
    <div className={cn('divide-y divide-border', className)} aria-busy="true" aria-live="polite">
      {Array.from({ length: rows }).map((_, index) => (
        <SkeletonRow key={index} />
      ))}
    </div>
  );
}

/** Card-shaped skeleton for dashboards. */
export function SkeletonCard({ className, lines = 3 }: { className?: string; lines?: number }) {
  return (
    <div className={cn('space-y-3 rounded-[var(--radius-card)] border border-border p-4', className)}>
      <Skeleton className="h-4 w-1/3" />
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton key={index} className={cn('h-3', index === lines - 1 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  );
}

/** Text-only skeleton for prose areas such as notes or AI replies. */
export function SkeletonText({ lines = 4, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn('space-y-2', className)}>
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton
          key={index}
          className={cn('h-3', index === lines - 1 ? 'w-3/5' : index % 3 === 2 ? 'w-5/6' : 'w-full')}
        />
      ))}
    </div>
  );
}

/** Centred spinner for small, self-contained areas such as the AI panel. */
export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        'inline-block size-4 animate-spin rounded-full border-2 border-border-strong border-t-primary',
        className,
      )}
    />
  );
}
