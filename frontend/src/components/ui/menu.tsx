import { useEffect, useRef, useState, type ReactNode } from 'react';

import { cn } from '@/lib/utils';

/**
 * Minimal anchored dropdown: closes on outside click, Escape, and route-agnostic blur.
 * Positioning is CSS-based (absolute within a relative parent) which is sufficient because
 * every menu in the app is anchored to a control on a header row.
 */
export function Menu({
  trigger,
  children,
  align = 'end',
  className,
  panelClassName,
  label,
}: {
  trigger: (props: { open: boolean; toggle: () => void }) => ReactNode;
  children: ReactNode | ((props: { close: () => void }) => ReactNode);
  align?: 'start' | 'end';
  className?: string;
  panelClassName?: string;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };

    document.addEventListener('mousedown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  return (
    <div ref={containerRef} className={cn('relative', className)}>
      {trigger({ open, toggle: () => setOpen((value) => !value) })}
      {open ? (
        <div
          role="menu"
          aria-label={label}
          className={cn(
            'animate-fade-in absolute z-50 mt-1 min-w-48 overflow-hidden rounded-[var(--radius-card)] border border-border bg-surface py-1 shadow-lg',
            align === 'end' ? 'right-0' : 'left-0',
            panelClassName,
          )}
        >
          {typeof children === 'function' ? children({ close: () => setOpen(false) }) : children}
        </div>
      ) : null}
    </div>
  );
}

export function MenuItem({
  children,
  onClick,
  icon,
  destructive = false,
  selected = false,
  disabled = false,
  description,
}: {
  children: ReactNode;
  onClick?: () => void;
  icon?: ReactNode;
  destructive?: boolean;
  selected?: boolean;
  disabled?: boolean;
  description?: string;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-[13px] transition-colors disabled:opacity-40',
        destructive
          ? 'text-danger hover:bg-danger-soft'
          : selected
            ? 'bg-primary-soft font-medium text-primary'
            : 'text-foreground hover:bg-accent',
      )}
    >
      {icon ? <span className="shrink-0 [&_svg]:size-3.5">{icon}</span> : null}
      <span className="min-w-0 flex-1">
        <span className="block truncate">{children}</span>
        {description ? (
          <span className="block truncate text-[11px] text-muted-foreground">{description}</span>
        ) : null}
      </span>
    </button>
  );
}

export function MenuLabel({ children }: { children: ReactNode }) {
  return (
    <p className="px-3 py-1.5 text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">
      {children}
    </p>
  );
}

export function MenuSeparator() {
  return <div className="my-1 h-px bg-border" />;
}
