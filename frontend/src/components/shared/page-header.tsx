import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

/**
 * Page-level heading.
 *
 * One definition keeps every screen's title, description and action row aligned — the
 * difference between a tool that feels considered and one that feels assembled.
 */
export function PageHeader({
  title,
  description,
  actions,
  meta,
  className,
  titleAddon,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  /** Small inline facts rendered under the title (counts, ranges, timestamps). */
  meta?: ReactNode;
  className?: string;
  titleAddon?: ReactNode;
}) {
  return (
    <header className={cn('flex flex-wrap items-start justify-between gap-4', className)}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {titleAddon}
        </div>
        {description ? (
          <p className="mt-1 max-w-2xl text-[13px] text-muted-foreground">{description}</p>
        ) : null}
        {meta ? (
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[13px] text-muted-foreground">
            {meta}
          </div>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

/** Sticky filter bar used by the catalogs. */
export function FilterBar({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-2 rounded-[var(--radius-card)] border border-border bg-surface px-3 py-2.5',
        className,
      )}
    >
      {children}
    </div>
  );
}

/** Two-column workspace: content plus a fixed-width side panel (AI tutor). */
export function WorkspaceLayout({
  children,
  aside,
  className,
  asideClassName,
}: {
  children: ReactNode;
  aside?: ReactNode;
  className?: string;
  asideClassName?: string;
}) {
  return (
    <div
      className={cn(
        'grid h-full min-h-0 gap-0',
        aside ? 'xl:grid-cols-[minmax(0,1fr)_22rem]' : undefined,
        className,
      )}
    >
      <div className="min-w-0 min-h-0">{children}</div>
      {aside ? (
        <aside
          className={cn(
            'hidden min-h-0 border-l border-border xl:flex xl:flex-col',
            asideClassName,
          )}
        >
          {aside}
        </aside>
      ) : null}
    </div>
  );
}
