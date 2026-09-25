import type { ReactNode } from 'react';

import { Card } from '@/components/ui/card';
import { ProgressRing } from '@/components/ui/progress';
import { cn } from '@/lib/utils';

/**
 * Compact metric tile.
 *
 * Deliberately restrained: a small label, one large figure, an optional hint line and an
 * optional progress indicator. No icon-heavy hero cards, no gradients.
 */
export function StatCard({
  label,
  value,
  unit,
  hint,
  tone = 'default',
  className,
  action,
  icon,
  children,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: ReactNode;
  tone?: 'default' | 'primary' | 'success' | 'warning' | 'danger';
  className?: string;
  action?: ReactNode;
  icon?: ReactNode;
  /** Optional progress indicator rendered under the hint. */
  children?: ReactNode;
}) {
  const valueTone =
    tone === 'primary'
      ? 'text-primary'
      : tone === 'success'
        ? 'text-success'
        : tone === 'warning'
          ? 'text-warning'
          : tone === 'danger'
            ? 'text-danger'
            : 'text-foreground';

  return (
    <Card padding="md" className={cn('flex flex-col justify-between gap-2', className)}>
      <div className="flex items-start justify-between gap-2">
        <p className="text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">
          {label}
        </p>
        {action ?? (icon ? <span className="text-subtle-foreground [&_svg]:size-4">{icon}</span> : null)}
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className={cn('tabular text-2xl leading-none font-semibold tracking-tight', valueTone)}>
          {value}
        </span>
        {unit ? <span className="text-[13px] text-muted-foreground">{unit}</span> : null}
      </div>
      {hint ? <div className="text-xs text-muted-foreground">{hint}</div> : null}
      {children}
    </Card>
  );
}

/** Stat with a numerator/denominator and a ring — used for the three curricula. */
export function ProgressStatCard({
  label,
  value,
  total,
  caption,
  tone = 'primary',
  className,
}: {
  label: string;
  value: number;
  total: number;
  caption?: string;
  tone?: 'primary' | 'success' | 'warning' | 'info';
  className?: string;
}) {
  const percentage = total > 0 ? Math.round((value / total) * 100) : 0;

  return (
    <Card padding="md" className={cn('flex items-center gap-4', className)}>
      <ProgressRing value={value} max={total} size={52} strokeWidth={4} tone={tone}>
        <span className="tabular text-[11px] font-semibold">{percentage}%</span>
      </ProgressRing>
      <div className="min-w-0">
        <p className="text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">
          {label}
        </p>
        <p className="tabular mt-0.5 text-lg leading-none font-semibold">
          {value}
          <span className="mx-1 text-muted-foreground">/</span>
          <span className="text-muted-foreground">{total}</span>
        </p>
        {caption ? <p className="mt-1 truncate text-xs text-muted-foreground">{caption}</p> : null}
      </div>
    </Card>
  );
}

/** Streak indicator that adapts to whether the day already counts. */
export function StreakBadge({
  current,
  todayActive = false,
  size = 'md',
  className,
}: {
  current: number;
  todayActive?: boolean;
  size?: 'md' | 'lg';
  className?: string;
}) {
  const label = `${current} day${current === 1 ? '' : 's'}`;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border font-medium',
        todayActive
          ? 'border-warning/30 bg-warning-soft text-warning'
          : 'border-border bg-muted text-muted-foreground',
        size === 'lg' ? 'px-3 py-1 text-sm' : 'px-2.5 py-0.5 text-[13px]',
        className,
      )}
      title={
        todayActive
          ? `Current streak: ${label}. Today already counts.`
          : `Current streak: ${label}. Study today to keep it alive.`
      }
    >
      <span aria-hidden>🔥</span>
      <span className="tabular font-semibold">{current}</span>
      <span className="font-normal opacity-80">day{current === 1 ? '' : 's'}</span>
    </span>
  );
}
