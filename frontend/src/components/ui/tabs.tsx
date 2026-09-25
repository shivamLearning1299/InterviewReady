import type { KeyboardEvent, ReactNode } from 'react';

import { cn } from '@/lib/utils';

export interface TabItem<T extends string = string> {
  value: T;
  label: string;
  /** Optional trailing count or short status. */
  hint?: ReactNode;
  disabled?: boolean;
}

/**
 * Controlled, horizontal tab strip built on the ARIA tabs pattern.
 *
 * Implemented directly rather than pulling in a headless dependency: the app needs one
 * compact variant, keyboard support and nothing else.
 */
export function Tabs<T extends string>({
  items,
  value,
  onChange,
  className,
  size = 'md',
}: {
  items: readonly TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
  size?: 'sm' | 'md';
}) {
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const enabled = items.filter((item) => !item.disabled);
    const index = enabled.findIndex((item) => item.value === value);
    if (index === -1) return;

    const focus = (nextIndex: number) => {
      const target = enabled[(nextIndex + enabled.length) % enabled.length];
      if (target) onChange(target.value);
    };

    if (event.key === 'ArrowRight') {
      event.preventDefault();
      focus(index + 1);
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      focus(index - 1);
    } else if (event.key === 'Home') {
      event.preventDefault();
      focus(0);
    } else if (event.key === 'End') {
      event.preventDefault();
      focus(enabled.length - 1);
    }
  };

  return (
    <div
      role="tablist"
      onKeyDown={handleKeyDown}
      className={cn('flex items-center gap-0.5 border-b border-border', className)}
    >
      {items.map((item) => {
        const selected = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            disabled={item.disabled}
            onClick={() => onChange(item.value)}
            className={cn(
              'relative -mb-px flex items-center gap-1.5 border-b-2 font-medium transition-colors disabled:opacity-40',
              size === 'sm' ? 'px-2.5 py-1.5 text-[13px]' : 'px-3 py-2 text-sm',
              selected
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted-foreground hover:border-border-strong hover:text-foreground',
            )}
          >
            {item.label}
            {item.hint !== undefined && item.hint !== null ? (
              <span className="tabular rounded bg-muted px-1 text-[11px] leading-4 text-muted-foreground">
                {item.hint}
              </span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

/** Vertical variant used inside the settings and topic workspaces. */
export function VerticalTabs<T extends string>({
  items,
  value,
  onChange,
  className,
}: {
  items: readonly TabItem<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div role="tablist" aria-orientation="vertical" className={cn('flex flex-col gap-0.5', className)}>
      {items.map((item) => {
        const selected = item.value === value;
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={selected}
            disabled={item.disabled}
            onClick={() => onChange(item.value)}
            className={cn(
              'flex items-center justify-between gap-2 rounded-[var(--radius-control)] px-2.5 py-1.5 text-left text-[13px] transition-colors',
              selected
                ? 'bg-primary-soft font-medium text-primary'
                : 'text-muted-foreground hover:bg-accent hover:text-foreground',
            )}
          >
            <span className="truncate">{item.label}</span>
            {item.hint !== undefined && item.hint !== null ? (
              <span className="tabular shrink-0 text-[11px] text-subtle-foreground">{item.hint}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
