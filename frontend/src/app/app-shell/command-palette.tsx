import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Boxes, Code2, FileText, Layers, Loader2, Network, Search } from 'lucide-react';

import { api } from '@/api/client';
import { Dialog } from '@/components/ui/dialog';
import { DifficultyBadge, StatusBadge } from '@/components/shared/domain-badges';
import { EmptyState } from '@/components/ui/empty-state';
import { debounce } from '@/lib/helpers';
import { MOD_KEY } from '@/lib/constants';
import { cn } from '@/lib/utils';
import type { SearchResult, SearchResultKind } from '@/types/search';

const KIND_ICON: Record<SearchResultKind, typeof Code2> = {
  dsa: Code2,
  pattern: Layers,
  topic: Layers,
  lld: Boxes,
  hld: Network,
  note: FileText,
};

const SEARCH_SCOPES = [
  { value: 'all', label: 'All' },
  { value: 'dsa', label: 'Problems' },
  { value: 'lld', label: 'LLD' },
  { value: 'hld', label: 'HLD' },
] as const;

/**
 * Global search palette (`Cmd/Ctrl + K`).
 *
 * Results are grouped by kind and keyboard navigable: arrow keys move a flattened cursor
 * across groups, Enter opens, Escape closes. The list is debounced so typing does not fire
 * a request per keystroke.
 */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [term, setTerm] = useState('');
  const [debounced, setDebounced] = useState('');
  const [scope, setScope] = useState<(typeof SEARCH_SCOPES)[number]['value']>('all');
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  // Reset on open so a previous search never leaks into a fresh invocation.
  useEffect(() => {
    if (!open) return;
    setTerm('');
    setDebounced('');
    setCursor(0);
    // Focus after paint so the input exists.
    const handle = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(handle);
  }, [open]);

  useEffect(() => {
    const debouncedSet = debounce((value: string) => {
      setDebounced(value);
      setCursor(0);
    }, 180);
    debouncedSet(term);
    return () => debouncedSet.cancel();
  }, [term]);

  const kinds: SearchResultKind[] | undefined =
    scope === 'all' ? undefined : scope === 'dsa' ? ['dsa', 'pattern'] : [scope];

  const { data: groups = [], isFetching } = useQuery({
    queryKey: ['search', debounced, scope],
    queryFn: () => api.search.query(debounced, kinds),
    enabled: open && debounced.trim().length >= 2,
    staleTime: 60 * 1000,
  });

  const flat: SearchResult[] = groups.flatMap((group) => group.results);

  const go = (result: SearchResult) => {
    navigate(result.href);
    onClose();
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setCursor((current) => Math.min(current + 1, flat.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      setCursor((current) => Math.max(current - 1, 0));
    } else if (event.key === 'Enter') {
      event.preventDefault();
      const target = flat[cursor];
      if (target) go(target);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Search" size="lg">
      <div className="-mx-5 -mt-4 flex h-[26rem] flex-col">
        {/* Input row */}
        <div className="flex items-center gap-2.5 border-b border-border px-4 py-3">
          <Search className="size-4 shrink-0 text-muted-foreground" />
          <input
            ref={inputRef}
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search problems, patterns, LLD/HLD topics and your notes…"
            aria-label="Search"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-subtle-foreground"
          />
          {isFetching ? <Loader2 className="size-3.5 shrink-0 animate-spin text-subtle-foreground" /> : null}
          <kbd className="hidden shrink-0 rounded border border-border bg-muted px-1.5 py-0.5 font-sans text-[11px] text-subtle-foreground sm:block">
            Esc
          </kbd>
        </div>

        {/* Scope filter */}
        <div className="flex items-center gap-1 border-b border-border px-3 py-1.5">
          {SEARCH_SCOPES.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => setScope(option.value)}
              aria-pressed={scope === option.value}
              className={cn(
                'rounded px-2 py-1 text-[12px] font-medium transition-colors',
                scope === option.value
                  ? 'bg-primary-soft text-primary'
                  : 'text-muted-foreground hover:bg-accent hover:text-foreground',
              )}
            >
              {option.label}
            </button>
          ))}
          <span className="ml-auto hidden text-[11px] text-subtle-foreground sm:block">
            ↑↓ to navigate · ↵ to open
          </span>
        </div>

        {/* Results */}
        <div className="min-h-0 flex-1 overflow-y-auto py-1">
          {debounced.trim().length < 2 ? (
            <EmptyState
              compact
              icon={<Search className="size-4" />}
              title="Start typing to search"
              description={`Find a problem by name, a pattern like "Sliding Window", a design topic, or text inside your own notes.`}
            />
          ) : flat.length === 0 && !isFetching ? (
            <EmptyState
              compact
              title="No matches"
              description={`Nothing found for "${debounced}". Try a shorter term or a different scope.`}
            />
          ) : (
            groups.map((group) => {
              const offset = groups
                .slice(0, groups.indexOf(group))
                .reduce((total, entry) => total + entry.results.length, 0);

              return (
                <section key={group.kind} className="px-2 py-1">
                  <h3 className="px-2 py-1 text-[11px] font-medium tracking-wide text-subtle-foreground uppercase">
                    {group.label}
                  </h3>
                  <ul>
                    {group.results.map((result, index) => {
                      const position = offset + index;
                      const Icon = KIND_ICON[result.kind] ?? Code2;
                      const active = position === cursor;

                      return (
                        <li key={result.id}>
                          <button
                            type="button"
                            onMouseEnter={() => setCursor(position)}
                            onClick={() => go(result)}
                            className={cn(
                              'flex w-full items-center gap-3 rounded-[var(--radius-control)] px-2 py-2 text-left transition-colors',
                              active ? 'bg-accent' : 'hover:bg-accent/60',
                            )}
                          >
                            <Icon className="size-4 shrink-0 text-muted-foreground" />
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-[13px] font-medium">
                                {result.title}
                              </span>
                              {result.subtitle ? (
                                <span className="block truncate text-[12px] text-muted-foreground">
                                  {result.subtitle}
                                </span>
                              ) : null}
                            </span>
                            <span className="flex shrink-0 items-center gap-1.5">
                              {result.difficulty ? (
                                <DifficultyBadge difficulty={result.difficulty} size="sm" />
                              ) : null}
                              {result.status ? (
                                <StatusBadge
                                  status={result.status}
                                  size="sm"
                                  domain={result.kind === 'lld' || result.kind === 'hld' ? 'topic' : 'problem'}
                                />
                              ) : null}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              );
            })
          )}
        </div>

        <div className="flex items-center gap-3 border-t border-border px-4 py-2 text-[11px] text-subtle-foreground">
          <span>
            {MOD_KEY}
            <span className="mx-0.5">K</span> opens this palette
          </span>
          <span className="ml-auto">
            {flat.length > 0 ? `${flat.length} result${flat.length === 1 ? '' : 's'}` : ''}
          </span>
        </div>
      </div>
    </Dialog>
  );
}

/**
 * Registers the global shortcut. Kept as a hook so the shell owns the state and the
 * palette stays a pure presentational component.
 */
export function useSearchShortcut(onOpen: () => void) {
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        onOpen();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onOpen]);
}
