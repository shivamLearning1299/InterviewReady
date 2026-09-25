import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

/**
 * Tooltip on hover/focus.
 *
 * Uses the native `title`-free approach with a CSS-positioned label, plus `aria-describedby`
 * so the hint is available to assistive technology.
 */
export function Tooltip({
  content,
  children,
  side = 'top',
  className,
}: {
  content: ReactNode;
  children: ReactNode;
  side?: 'top' | 'bottom' | 'right';
  className?: string;
}) {
  return (
    <span className={cn('group/tt relative inline-flex', className)}>
      {children}
      <span
        role="tooltip"
        className={cn(
          'pointer-events-none absolute z-50 hidden w-max max-w-64 rounded-md border border-border bg-surface px-2 py-1 text-[12px] leading-snug text-foreground shadow-lg group-hover/tt:block group-focus-within/tt:block',
          side === 'top' && 'bottom-full left-1/2 mb-1.5 -translate-x-1/2',
          side === 'bottom' && 'top-full left-1/2 mt-1.5 -translate-x-1/2',
          side === 'right' && 'top-1/2 left-full ml-1.5 -translate-y-1/2',
        )}
      >
        {content}
      </span>
    </span>
  );
}

/** Section heading with optional right-aligned action — the recurring page-level pattern. */
export function SectionHeader({
  title,
  count,
  description,
  action,
  className,
  as: Tag = 'h2',
}: {
  title: string;
  count?: number | string;
  description?: string;
  action?: ReactNode;
  className?: string;
  as?: 'h1' | 'h2' | 'h3';
}) {
  return (
    <div className={cn('flex items-start justify-between gap-4', className)}>
      <div className="min-w-0">
        <Tag className="flex items-center gap-2 text-base font-semibold tracking-tight">
          {title}
          {count !== undefined ? (
            <span className="tabular rounded-md border border-border bg-muted px-1.5 text-[11px] leading-5 font-medium text-muted-foreground">
              {count}
            </span>
          ) : null}
        </Tag>
        {description ? (
          <p className="mt-0.5 text-[13px] text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
    </div>
  );
}

/** Definition pair used in detail panels and metadata grids. */
export function MetaItem({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('min-w-0', className)}>
      <dt className="text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">
        {label}
      </dt>
      <dd className="mt-1 text-[13px] text-foreground">{children}</dd>
    </div>
  );
}

/** Key/value row for compact side panels. */
export function InfoRow({
  label,
  value,
  className,
}: {
  label: string;
  value: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('flex items-baseline justify-between gap-3 py-1', className)}>
      <span className="text-[13px] text-muted-foreground">{label}</span>
      <span className="text-right text-[13px] font-medium">{value}</span>
    </div>
  );
}
