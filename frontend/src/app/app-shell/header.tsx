import {
  Bell,
  CalendarDays,
  Check,
  Flame,
  Keyboard,
  LogOut,
  Menu,
  Monitor,
  Moon,
  Search,
  Settings as SettingsIcon,
  Sun,
  User,
} from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';

import { Menu as MenuPrimitive, MenuItem, MenuLabel, MenuSeparator } from '@/components/ui/menu';
import { useAuth } from '@/providers/auth-provider';
import { useSidebar } from '@/providers/sidebar-provider';
import { useTheme } from '@/providers/theme-provider';
import { useStreak } from '@/hooks/use-api';
import { MOD_KEY } from '@/lib/constants';
import { initials } from '@/lib/helpers';
import { formatDate } from '@/lib/format';
import { cn } from '@/lib/utils';

/**
 * Top header: search, streak and the account menu.
 *
 * The streak is the server's value (single source of truth for both clients), and the
 * search affordance advertises the keyboard shortcut rather than hiding it in a tooltip.
 */
export function Header({ onOpenSearch }: { onOpenSearch: () => void }) {
  const { setMobileOpen } = useSidebar();
  const { user, signOut, isDemo } = useAuth();
  const { preference, setPreference } = useTheme();
  const { data: streak } = useStreak();
  const navigate = useNavigate();

  const displayName = user?.name ?? 'there';
  const email = user?.email ?? '';

  const handleSignOut = async () => {
    await signOut();
    toast.success('Signed out');
    navigate('/login');
  };

  return (
    <header className="sticky top-0 z-40 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-background/95 px-3 backdrop-blur-sm sm:px-4">
      {/* Mobile navigation trigger */}
      <button
        type="button"
        onClick={() => setMobileOpen(true)}
        aria-label="Open navigation"
        className="rounded-[var(--radius-control)] p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground lg:hidden"
      >
        <Menu className="size-4.5" />
      </button>

      <Link to="/" className="flex items-center gap-2 lg:hidden">
        <span
          aria-hidden
          className="flex size-7 items-center justify-center rounded-md bg-primary text-[13px] font-bold text-primary-foreground"
        >
          IR
        </span>
      </Link>

      {/* Search trigger — a button, because a real input would steal focus and mislead. */}
      <button
        type="button"
        onClick={onOpenSearch}
        className="group flex h-9 min-w-0 flex-1 items-center gap-2 rounded-[var(--radius-control)] border border-border bg-muted px-3 text-left text-[13px] text-muted-foreground transition-colors hover:border-border-strong hover:bg-surface sm:max-w-md"
      >
        <Search className="size-3.5 shrink-0" />
        <span className="truncate">Search problems, topics, notes…</span>
        <kbd className="ml-auto hidden shrink-0 items-center gap-0.5 rounded border border-border bg-surface px-1.5 py-0.5 font-sans text-[11px] text-subtle-foreground sm:flex">
          {MOD_KEY}
          <span>K</span>
        </kbd>
      </button>

      <div className="ml-auto flex items-center gap-1.5">
        {/* Streak */}
        <div
          className={cn(
            'hidden items-center gap-1.5 rounded-full border px-2.5 py-1 sm:flex',
            streak?.today_active
              ? 'border-warning/30 bg-warning-soft text-warning'
              : 'border-border bg-muted text-muted-foreground',
          )}
          title={
            streak?.today_active
              ? `Streak alive — ${streak.current} days, today already counts`
              : 'Study today to keep your streak alive'
          }
        >
          <Flame className="size-3.5" />
          <span className="tabular text-[13px] font-semibold">{streak?.current ?? 0}</span>
          <span className="text-[12px] opacity-80">day{(streak?.current ?? 0) === 1 ? '' : 's'}</span>
        </div>

        {/* Theme */}
        <MenuPrimitive
          label="Theme"
          trigger={({ toggle, open }) => (
            <button
              type="button"
              onClick={toggle}
              aria-label="Change theme"
              aria-expanded={open}
              className="rounded-[var(--radius-control)] p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              {preference === 'dark' ? (
                <Moon className="size-4" />
              ) : preference === 'light' ? (
                <Sun className="size-4" />
              ) : (
                <Monitor className="size-4" />
              )}
            </button>
          )}
        >
          {({ close }) => (
            <>
              <MenuLabel>Appearance</MenuLabel>
              {(
                [
                  { value: 'light', label: 'Light', icon: Sun },
                  { value: 'dark', label: 'Dark', icon: Moon },
                  { value: 'system', label: 'System', icon: Monitor },
                ] as const
              ).map((option) => (
                <MenuItem
                  key={option.value}
                  icon={<option.icon />}
                  selected={preference === option.value}
                  onClick={() => {
                    setPreference(option.value);
                    close();
                  }}
                >
                  {option.label}
                </MenuItem>
              ))}
            </>
          )}
        </MenuPrimitive>

        {/* Account */}
        <MenuPrimitive
          label="Account"
          panelClassName="min-w-56"
          trigger={({ toggle, open }) => (
            <button
              type="button"
              onClick={toggle}
              aria-label="Account menu"
              aria-expanded={open}
              className="flex size-8 items-center justify-center rounded-full border border-border bg-muted text-[11px] font-semibold text-muted-foreground transition-colors hover:border-border-strong hover:text-foreground"
            >
              {initials(email || displayName)}
            </button>
          )}
        >
          {({ close }) => (
            <>
              <div className="px-3 py-2">
                <p className="truncate text-[13px] font-medium">{displayName}</p>
                <p className="truncate text-[11px] text-muted-foreground">{email || 'No email'}</p>
                {isDemo ? (
                  <p className="mt-1.5 inline-flex items-center gap-1 rounded border border-info/25 bg-info-soft px-1.5 text-[11px] text-info">
                    Demo session
                  </p>
                ) : null}
              </div>
              <MenuSeparator />
              <MenuItem
                icon={<CalendarDays />}
                description="Today's plan"
                onClick={() => {
                  navigate('/');
                  close();
                }}
              >
                Today
              </MenuItem>
              <MenuItem
                icon={<SettingsIcon />}
                description="Preferences, sync and data"
                onClick={() => {
                  navigate('/settings');
                  close();
                }}
              >
                Settings
              </MenuItem>
              <MenuItem
                icon={<Keyboard />}
                onClick={() => {
                  onOpenSearch();
                  close();
                }}
              >
                Quick search
              </MenuItem>
              <MenuSeparator />
              <MenuItem
                icon={<User />}
                onClick={() => {
                  navigate('/settings');
                  close();
                }}
              >
                Account details
              </MenuItem>
              <MenuItem
                icon={<LogOut />}
                destructive
                onClick={() => {
                  close();
                  void handleSignOut();
                }}
              >
                Sign out
              </MenuItem>
            </>
          )}
        </MenuPrimitive>
      </div>
    </header>
  );
}

/** Small helper for date-stamped headings ("Saturday, 26 September"). */
export function useTodayLabel(): string {
  return formatDate(new Date().toISOString(), 'EEEE, d MMMM');
}

/** Re-exported so screens can render a consistent "all caught up" affordance. */
export { Check, Bell };
