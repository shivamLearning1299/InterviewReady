import { useState } from 'react';
import { useTheme } from '@/providers/theme-provider';
import { toast } from 'sonner';
import {
  Database,
  Download,
  Languages,
  LogOut,
  MonitorSmartphone,
  Palette,
  RefreshCw,
  Sparkles,
  Sun,
  Target,
  Trash2,
} from 'lucide-react';

import { PageHeader } from '@/components/shared/page-header';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { EmptyState, ErrorState } from '@/components/ui/empty-state';
import { Field, Input, Select } from '@/components/ui/input';
import { SkeletonCard } from '@/components/ui/skeleton';
import { SegmentedControl, Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { useAuth } from '@/providers/auth-provider';
import { useAiActions, useDevices, useRunSync, useSettings, useSyncStatus, useUpdateSettings } from '@/hooks/use-api';
import { api } from '@/api/client';
import { downloadBlob } from '@/api/http';
import { messageFor } from '@/api/errors';
import { resetStore } from '@/mocks/store';
import { LANGUAGE_OPTIONS } from '@/lib/constants';
import { formatRelativeTime } from '@/lib/format';
import { timezoneOptions } from '@/lib/timezone';
import { cn } from '@/lib/utils';
import type { Language } from '@/types/common';
import type { UserSettingsUpdate } from '@/types/settings';

type TabValue = 'account' | 'study' | 'appearance' | 'sync' | 'data';

const TABS: { value: TabValue; label: string }[] = [
  { value: 'study', label: 'Study' },
  { value: 'account', label: 'Account' },
  { value: 'appearance', label: 'Appearance' },
  { value: 'sync', label: 'Sync & Devices' },
  { value: 'data', label: 'Data' },
];

/**
 * Settings.
 *
 * Grouped by what the user came to change rather than by which API endpoint serves it.
 * Every control writes immediately — there is no page-level Save button, because a
 * settings screen that can silently lose changes is worse than one that cannot.
 */
export function SettingsPage() {
  const [tab, setTab] = useState<TabValue>('study');

  return (
    <div className="mx-auto w-full max-w-[1100px] px-4 py-5 sm:px-6">
      <PageHeader
        title="Settings"
        description="Study targets, account, appearance, sync and your data."
      />

      <div
        role="tablist"
        aria-label="Settings sections"
        className="mt-4 flex flex-wrap items-center gap-0.5 border-b border-border"
      >
        {TABS.map((entry) => {
          const selected = entry.value === tab;
          return (
            <button
              key={entry.value}
              role="tab"
              type="button"
              aria-selected={selected}
              onClick={() => setTab(entry.value)}
              className={cn(
                'relative -mb-px border-b-2 px-3 py-2 text-[13px] font-medium transition-colors',
                selected
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground',
              )}
            >
              {entry.label}
            </button>
          );
        })}
      </div>

      <div className="mt-5 space-y-4">
        {tab === 'study' ? <StudySection /> : null}
        {tab === 'account' ? <AccountSection /> : null}
        {tab === 'appearance' ? <AppearanceSection /> : null}
        {tab === 'sync' ? <SyncSection /> : null}
        {tab === 'data' ? <DataSection /> : null}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------- study

function StudySection() {
  const settings = useSettings();
  const updateSettings = useUpdateSettings();
  const aiActions = useAiActions();

  if (settings.isLoading) return <SkeletonCard lines={6} />;
  if (settings.isError || !settings.data) {
    return <ErrorState title="Could not load your settings" onRetry={() => void settings.refetch()} />;
  }

  const data = settings.data;
  const save = (payload: UserSettingsUpdate) => updateSettings.mutate(payload);

  const toggleLanguage = (language: Language) => {
    const next = data.preferred_languages.includes(language)
      ? data.preferred_languages.filter((value) => value !== language)
      : [...data.preferred_languages, language];
    // The API expects at least one language, so refuse to empty the list.
    if (next.length === 0) {
      toast.error('Keep at least one preferred language');
      return;
    }
    save({ preferred_languages: next });
  };

  return (
    <>
      <Card padding="md" className="space-y-4">
        <div className="flex items-start gap-2">
          <Target className="mt-0.5 size-4 text-subtle-foreground" />
          <div>
            <h2 className="text-sm font-semibold">Daily targets</h2>
            <p className="mt-0.5 text-[12px] text-muted-foreground">
              How much the scheduler puts in each day's plan. Lower it if you keep missing days —
              a plan you finish beats a plan you abandon.
            </p>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="DSA problems per day"
            hint="Default is 3. Realistic targets keep the streak alive."
            htmlFor="daily-dsa"
          >
            <Input
              id="daily-dsa"
              type="number"
              min={1}
              max={20}
              value={data.daily_dsa_count}
              disabled={updateSettings.isPending}
              onChange={(event) => save({ daily_dsa_count: Number(event.target.value) })}
            />
          </Field>

          <Field
            label="Revisions per day"
            hint="Spaced repetition reviews scheduled for each day."
            htmlFor="daily-revision"
          >
            <Input
              id="daily-revision"
              type="number"
              min={0}
              max={30}
              value={data.daily_revision_count}
              disabled={updateSettings.isPending}
              onChange={(event) => save({ daily_revision_count: Number(event.target.value) })}
            />
          </Field>
        </div>

        <div className="space-y-3 border-t border-border pt-3.5">
          <Switch
            checked={data.include_lld_daily}
            disabled={updateSettings.isPending}
            onChange={(checked) => save({ include_lld_daily: checked })}
            label="Include a low-level design topic each day"
            description="Adds one LLD topic to the daily plan."
          />
          <Switch
            checked={data.include_hld_daily}
            disabled={updateSettings.isPending}
            onChange={(checked) => save({ include_hld_daily: checked })}
            label="Include a high-level design topic each day"
            description="Adds one HLD topic to the daily plan."
          />
          <Switch
            checked={data.revision_enabled}
            disabled={updateSettings.isPending}
            onChange={(checked) => save({ revision_enabled: checked })}
            label="Enable spaced revision"
            description="Schedules reviews as you solve. Turning this off stops new reviews being queued — existing ones stay."
          />
        </div>
      </Card>

      <Card padding="md" className="space-y-3">
        <div className="flex items-start gap-2">
          <Languages className="mt-0.5 size-4 text-subtle-foreground" />
          <div>
            <h2 className="text-sm font-semibold">Preferred languages</h2>
            <p className="mt-0.5 text-[12px] text-muted-foreground">
              The editor opens in the first of these. All of them appear in the language picker.
            </p>
          </div>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {LANGUAGE_OPTIONS.map((option) => {
            const selected = data.preferred_languages.includes(option.value);
            return (
              <button
                key={option.value}
                type="button"
                aria-pressed={selected}
                disabled={updateSettings.isPending}
                onClick={() => toggleLanguage(option.value)}
                className={cn(
                  'rounded-full border px-2.5 py-1 text-[12px] font-medium transition-colors disabled:opacity-60',
                  selected
                    ? 'border-primary/30 bg-primary-soft text-primary'
                    : 'border-border bg-surface text-muted-foreground hover:border-border-strong hover:text-foreground',
                )}
              >
                {option.label}
              </button>
            );
          })}
        </div>
      </Card>

      <Card padding="md" className="space-y-3">
        <div className="flex items-start gap-2">
          <Sparkles className="mt-0.5 size-4 text-subtle-foreground" />
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold">AI tutor</h2>
            <p className="mt-0.5 text-[12px] text-muted-foreground">
              The tutor can read the problem or design in focus. It cannot see the rest of your
              workspace unless you paste it.
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {aiActions.isLoading ? (
            <span className="text-[12px] text-muted-foreground">Checking provider…</span>
          ) : aiActions.data ? (
            <>
              <Badge tone={aiActions.data.enabled ? 'success' : 'neutral'} size="sm" dot>
                {aiActions.data.enabled ? 'Enabled' : 'Disabled'}
              </Badge>
              <span className="text-[12px] text-muted-foreground">
                {aiActions.data.provider} · {aiActions.data.model}
              </span>
            </>
          ) : (
            <span className="text-[12px] text-muted-foreground">
              Provider status unavailable.
            </span>
          )}
        </div>

        <Switch
          checked={data.ai_auto_reveal_solution}
          disabled={updateSettings.isPending}
          onChange={(checked) => save({ ai_auto_reveal_solution: checked })}
          label="Allow the tutor to reveal a full solution"
          description="Off by default. With this off the tutor escalates hints instead of handing over the answer — which is the point."
        />
      </Card>

      <Card padding="md" className="space-y-2">
        <h2 className="text-sm font-semibold">Timezone</h2>
        <p className="text-[12px] text-muted-foreground">
          Used to decide when a day starts, which daily plans and streaks depend on.
        </p>
        <Select
          value={data.timezone}
          aria-label="Timezone"
          disabled={updateSettings.isPending}
          onChange={(event) => save({ timezone: event.target.value })}
        >
          {timezoneOptions().map((zone) => (
            <option key={zone} value={zone}>
              {zone}
            </option>
          ))}
        </Select>
      </Card>
    </>
  );
}

// ----------------------------------------------------------------- account

function AccountSection() {
  const { user, signOut, isDemo } = useAuth();

  return (
    <>
      <Card padding="md" className="space-y-3">
        <h2 className="text-sm font-semibold">Account</h2>
        <dl className="space-y-2 text-[13px]">
          <div className="flex items-center justify-between gap-4">
            <dt className="text-muted-foreground">Email</dt>
            <dd className="truncate font-medium">{user?.email ?? 'Not signed in'}</dd>
          </div>
          <div className="flex items-center justify-between gap-4">
            <dt className="text-muted-foreground">Display name</dt>
            <dd className="truncate font-medium">{user?.name ?? '—'}</dd>
          </div>
          <div className="flex items-center justify-between gap-4">
            <dt className="text-muted-foreground">Authentication</dt>
            <dd>
              <Badge tone={isDemo ? 'warning' : 'success'} size="sm">
                {isDemo ? 'Demo session' : 'Supabase'}
              </Badge>
            </dd>
          </div>
        </dl>

        {isDemo ? (
          <p className="rounded-[var(--radius-control)] border border-warning/25 bg-warning-soft px-3 py-2 text-[12px] text-foreground">
            This is a local demo session — no credentials were checked and nothing leaves this
            browser. Configure Supabase in <code className="font-mono">.env</code> to use real
            authentication.
          </p>
        ) : null}
      </Card>

      <Card padding="md" className="space-y-3">
        <div>
          <h2 className="text-sm font-semibold">Sign out</h2>
          <p className="mt-0.5 text-[12px] text-muted-foreground">
            Ends the session on this device. Your data stays on the server.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void signOut()}>
          <LogOut />
          Sign out
        </Button>
      </Card>
    </>
  );
}

// -------------------------------------------------------------- appearance

function AppearanceSection() {
  const { preference, setPreference } = useTheme();

  return (
    <Card padding="md" className="space-y-4">
      <div className="flex items-start gap-2">
        <Palette className="mt-0.5 size-4 text-subtle-foreground" />
        <div>
          <h2 className="text-sm font-semibold">Theme</h2>
          <p className="mt-0.5 text-[12px] text-muted-foreground">
            Stored on this device. "System" follows your OS setting and changes with it.
          </p>
        </div>
      </div>

      <SegmentedControl
        label="Theme preference"
        value={preference}
        onChange={setPreference}
        options={[
          { value: 'light', label: 'Light' },
          { value: 'dark', label: 'Dark' },
          { value: 'system', label: 'System' },
        ]}
      />

      <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
        <Sun className="size-3.5" />
        A light theme is easier in a bright room; dark in the evening. Both are the same layout.
      </div>
    </Card>
  );
}

// -------------------------------------------------------------------- sync

function SyncSection() {
  const devices = useDevices();
  const syncStatus = useSyncStatus();
  const runSync = useRunSync();

  return (
    <>
      <Card padding="md" className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">Sync</h2>
            <p className="mt-0.5 text-[12px] text-muted-foreground">
              Progress is written immediately, so sync only matters across devices.
            </p>
          </div>
          <Button
            variant="secondary"
            size="sm"
            loading={runSync.isPending}
            onClick={() => runSync.mutate()}
          >
            <RefreshCw />
            Sync now
          </Button>
        </div>

        {syncStatus.isLoading ? (
          <SkeletonCard lines={2} />
        ) : syncStatus.data ? (
          <dl className="grid gap-3 text-[13px] sm:grid-cols-3">
            <div>
              <dt className="text-[11px] tracking-wide text-subtle-foreground uppercase">
                Last synced
              </dt>
              <dd className="mt-0.5 font-medium">
                {syncStatus.data.last_sync_at
                  ? formatRelativeTime(syncStatus.data.last_sync_at)
                  : 'Never'}
              </dd>
            </div>
            <div>
              <dt className="text-[11px] tracking-wide text-subtle-foreground uppercase">
                Cursor
              </dt>
              <dd className="tabular mt-0.5 font-medium">{syncStatus.data.cursor}</dd>
            </div>
            <div>
              <dt className="text-[11px] tracking-wide text-subtle-foreground uppercase">
                Last change
              </dt>
              <dd className="mt-0.5 font-medium">
                {syncStatus.data.last_change_at
                  ? formatRelativeTime(syncStatus.data.last_change_at)
                  : '—'}
              </dd>
            </div>
          </dl>
        ) : (
          <ErrorState title="Could not read sync status" onRetry={() => void syncStatus.refetch()} />
        )}
      </Card>

      <Card padding="none" className="overflow-hidden">
        <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
          <h2 className="flex items-center gap-1.5 text-sm font-semibold">
            <MonitorSmartphone className="size-3.5" />
            Devices
          </h2>
          <span className="tabular text-[12px] text-subtle-foreground">
            {devices.data?.items.length ?? 0}
          </span>
        </div>

        {devices.isLoading ? (
          <div className="p-4">
            <SkeletonCard lines={2} />
          </div>
        ) : (devices.data?.items ?? []).length === 0 ? (
          <EmptyState
            compact
            title="No devices registered"
            description="Sign in on another device and it will appear here."
          />
        ) : (
          <ul className="divide-y divide-border">
            {(devices.data?.items ?? []).map((device) => (
              <li key={device.id} className="flex items-center justify-between gap-3 px-4 py-2.5">
                <div className="min-w-0">
                  <p className="truncate text-[13px] font-medium">
                    {device.display_name ?? device.device_identifier}
                  </p>
                  <p className="mt-0.5 text-[11px] text-subtle-foreground">
                    {device.device_type} ·{' '}
                    {device.last_sync_at
                      ? `synced ${formatRelativeTime(device.last_sync_at)}`
                      : 'never synced'}
                  </p>
                </div>
                <Badge tone="outline" size="sm">
                  {device.device_type}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

// -------------------------------------------------------------------- data

function DataSection() {
  const [exporting, setExporting] = useState(false);

  const exportData = async () => {
    setExporting(true);
    try {
      const blob = await api.users.exportData();
      const stamp = new Date().toISOString().slice(0, 10);
      downloadBlob(blob, `interviewready-export-${stamp}.json`);
      toast.success('Export downloaded');
    } catch (error) {
      toast.error(messageFor(error));
    } finally {
      setExporting(false);
    }
  };

  const resetDemo = () => {
    resetStore();
    toast.success('Demo data reset — reload to see the seeded state');
  };

  return (
    <>
      <Card padding="md" className="space-y-3">
        <div className="flex items-start gap-2">
          <Download className="mt-0.5 size-4 text-subtle-foreground" />
          <div>
            <h2 className="text-sm font-semibold">Export your data</h2>
            <p className="mt-0.5 text-[12px] text-muted-foreground">
              Downloads everything — problems, progress, notes, code, attempts and revision
              history — as JSON. Nothing here is a one-way door.
            </p>
          </div>
        </div>
        <Button variant="primary" size="sm" loading={exporting} onClick={() => void exportData()}>
          <Download />
          Download JSON
        </Button>
      </Card>

      <Card padding="md" className="space-y-3">
        <div className="flex items-start gap-2">
          <Database className="mt-0.5 size-4 text-subtle-foreground" />
          <div>
            <h2 className="text-sm font-semibold">Demo data</h2>
            <p className="mt-0.5 text-[12px] text-muted-foreground">
              In mock mode all state lives in memory. Resetting restores the seeded catalog and
              clears any progress you made in this session.
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={resetDemo}>
          <Trash2 />
          Reset demo data
        </Button>
      </Card>
    </>
  );
}
