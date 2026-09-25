import type { ReactNode } from 'react';
import { AlertTriangle, Inbox, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/**
 * Empty state. Always explains what would appear here and, where useful, offers the single
 * action that would populate it — an empty screen should never be a dead end.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
  compact = false,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center text-center',
        compact ? 'gap-2 px-4 py-8' : 'gap-3 px-6 py-14',
        className,
      )}
    >
      <div
        aria-hidden
        className={cn(
          'flex items-center justify-center rounded-full border border-border bg-muted text-subtle-foreground',
          compact ? 'size-8' : 'size-10',
        )}
      >
        {icon ?? <Inbox className={compact ? 'size-4' : 'size-5'} />}
      </div>
      <div className="space-y-1">
        <p className={cn('font-medium text-foreground', compact ? 'text-[13px]' : 'text-sm')}>
          {title}
        </p>
        {description ? (
          <p className="mx-auto max-w-sm text-[13px] leading-relaxed text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {action ? <div className="pt-1">{action}</div> : null}
    </div>
  );
}

/** Error state with a retry affordance. Used by every data-bound section. */
export function ErrorState({
  title = 'Could not load this',
  description,
  onRetry,
  className,
}: {
  title?: string;
  description?: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div className={cn('flex flex-col items-center gap-3 px-6 py-12 text-center', className)}>
      <div
        aria-hidden
        className="flex size-10 items-center justify-center rounded-full border border-danger/25 bg-danger-soft text-danger"
      >
        <AlertTriangle className="size-5" />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium">{title}</p>
        {description ? (
          <p className="mx-auto max-w-sm text-[13px] text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          <RefreshCw />
          Try again
        </Button>
      ) : null}
    </div>
  );
}
