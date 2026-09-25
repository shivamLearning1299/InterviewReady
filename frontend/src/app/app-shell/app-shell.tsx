import { useCallback, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';

import { CommandPalette, useSearchShortcut } from '@/app/app-shell/command-palette';
import { Header } from '@/app/app-shell/header';
import { Sidebar } from '@/app/app-shell/sidebar';
import { ErrorBoundary } from '@/app/error-boundary';
import { ScrollToTop } from '@/app/scroll-to-top';

/**
 * Persistent application shell.
 *
 * The sidebar and header mount once and survive navigation; only the `<Outlet />` swaps.
 * That keeps query state warm and avoids the sidebar's badges refetching on every route.
 */
export function AppShell() {
  const [searchOpen, setSearchOpen] = useState(false);
  const openSearch = useCallback(() => setSearchOpen(true), []);
  const closeSearch = useCallback(() => setSearchOpen(false), []);

  useSearchShortcut(openSearch);
  const location = useLocation();

  return (
    <div className="flex h-dvh overflow-hidden bg-background">
      <Sidebar />

      <div className="flex min-w-0 flex-1 flex-col">
        <Header onOpenSearch={openSearch} />

        <main className="min-h-0 flex-1 overflow-y-auto">
          <ErrorBoundary key={location.pathname}>
            <ScrollToTop />
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>

      <CommandPalette open={searchOpen} onClose={closeSearch} />
    </div>
  );
}
