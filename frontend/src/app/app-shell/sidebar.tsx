import { NavLink } from 'react-router-dom';
import {
  BarChart3,
  Boxes,
  Code2,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  RotateCcw,
  Settings as SettingsIcon,
  Sparkles,
  Sun,
  X,
  type LucideIcon,
} from 'lucide-react';

import { NAV_ITEMS } from '@/lib/constants';
import { cn } from '@/lib/utils';
import { useSidebar } from '@/providers/sidebar-provider';
import { useRevisionSummary, useStreak } from '@/hooks/use-api';
import { useAuth } from '@/providers/auth-provider';
import { Tooltip } from '@/components/ui/tooltip';

const ICONS: Record<string, LucideIcon> = {
  Sun,
  Code2,
  RotateCcw,
  Boxes,
  Network,
  BarChart3,
  Sparkles,
  Settings: SettingsIcon,
};

/**
 * Permanent desktop sidebar.
 *
 * Collapses to an icon rail (state persisted) and becomes an overlay drawer below `lg`.
 * Badges are data-driven — the revision count comes from the API, not from a constant.
 */
export function Sidebar() {
  const { collapsed, toggle, mobileOpen, setMobileOpen } = useSidebar();
  const { data: revisionSummary } = useRevisionSummary();
  const { data: streak } = useStreak();
  const { user } = useAuth();

  const dueCount = (revisionSummary?.due ?? 0) + (revisionSummary?.overdue ?? 0);

  const badgeFor = (label: string): number | null => {
    if (label === 'Revisions' && dueCount > 0) return dueCount;
    return null;
  };

  const content = (
    <>
      {/* Brand */}
      <div
        className={cn(
          'flex h-14 shrink-0 items-center gap-2.5 border-b border-border px-3',
          collapsed && 'justify-center px-0',
        )}
      >
        <span
          aria-hidden
          className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary text-[13px] font-bold text-primary-foreground"
        >
          IR
        </span>
        {!collapsed ? (
          <span className="truncate text-sm font-semibold tracking-tight">InterviewReady</span>
        ) : null}
        <button
          type="button"
          onClick={() => setMobileOpen(false)}
          aria-label="Close navigation"
          className="ml-auto rounded p-1 text-muted-foreground hover:bg-accent lg:hidden"
        >
          <X className="size-4" />
        </button>
      </div>

      {/* Primary navigation */}
      <nav aria-label="Main navigation" className="flex-1 overflow-y-auto px-2 py-3">
        <ul className="space-y-0.5">
          {NAV_ITEMS.map((item) => {
            const Icon = ICONS[item.icon] ?? Sun;
            const badge = badgeFor(item.label);

            const link = (
              <NavLink
                to={item.to}
                end={item.to === '/'}
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) =>
                  cn(
                    'group flex items-center gap-2.5 rounded-[var(--radius-control)] px-2.5 py-2 text-[13px] font-medium transition-colors',
                    isActive
                      ? 'bg-primary-soft text-primary'
                      : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                    collapsed && 'justify-center px-0',
                  )
                }
              >
                <Icon className="size-4 shrink-0" aria-hidden />
                {!collapsed ? (
                  <>
                    <span className="flex-1 truncate">{item.label}</span>
                    {badge ? (
                      <span className="tabular rounded-full bg-warning-soft px-1.5 text-[11px] leading-4 font-semibold text-warning">
                        {badge > 99 ? '99+' : badge}
                      </span>
                    ) : null}
                  </>
                ) : badge ? (
                  <span
                    aria-hidden
                    className="absolute top-1.5 right-2.5 size-1.5 rounded-full bg-warning"
                  />
                ) : null}
              </NavLink>
            );

            return (
              <li key={item.to} className={collapsed ? 'relative' : undefined}>
                {collapsed ? <Tooltip content={item.label} side="right">{link}</Tooltip> : link}
              </li>
            );
          })}
        </ul>
      </nav>

      {/* Footer: streak + collapse control */}
      {!collapsed ? (
        <div className="shrink-0 space-y-2 border-t border-border p-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">
              Signed in
            </span>
          </div>
          <p className="truncate text-[13px] text-muted-foreground" title={user?.email ?? undefined}>
            {user?.email ?? 'Not signed in'}
          </p>
          <button
            type="button"
            onClick={toggle}
            className="flex w-full items-center gap-2 rounded-[var(--radius-control)] px-2 py-1.5 text-[13px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <PanelLeftClose className="size-4" />
            Collapse sidebar
          </button>
        </div>
      ) : (
        <div className="shrink-0 space-y-1 border-t border-border p-2">
          <Tooltip content="Expand sidebar" side="right">
            <button
              type="button"
              onClick={toggle}
              aria-label="Expand sidebar"
              className="flex size-9 items-center justify-center rounded-[var(--radius-control)] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <PanelLeftOpen className="size-4" />
            </button>
          </Tooltip>
          <div className="flex justify-center">
            {streak && streak.current > 0 ? (
              <Tooltip content={`${streak.current} day streak`} side="right">
                <span className="tabular flex size-6 items-center justify-center rounded-full border border-warning/30 bg-warning-soft text-[11px] font-semibold text-warning">
                  {streak.current}
                </span>
              </Tooltip>
            ) : null}
          </div>
        </div>
      )}
    </>
  );

  return (
    <>
      {/* Desktop rail */}
      <aside
        className={cn(
          'hidden shrink-0 flex-col border-r border-border bg-sidebar transition-[width] duration-200 lg:flex',
          collapsed ? 'w-14' : 'w-60',
        )}
      >
        {content}
      </aside>

      {/* Mobile drawer */}
      {mobileOpen ? (
        <div className="fixed inset-0 z-90 lg:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setMobileOpen(false)}
            className="absolute inset-0 bg-overlay"
          />
          <aside className="animate-fade-in relative flex h-full w-64 flex-col border-r border-border bg-sidebar">
            {content}
          </aside>
        </div>
      ) : null}
    </>
  );
}
