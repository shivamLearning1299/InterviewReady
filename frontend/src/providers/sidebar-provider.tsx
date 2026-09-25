import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

import { STORAGE_KEYS } from '@/api/config';

interface SidebarContextValue {
  collapsed: boolean;
  toggle: () => void;
  setCollapsed: (collapsed: boolean) => void;
  /** Mobile drawer state — separate from the desktop rail. */
  mobileOpen: boolean;
  setMobileOpen: (open: boolean) => void;
}

const SidebarContext = createContext<SidebarContextValue | null>(null);

function readCollapsed(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEYS.sidebar) === 'true';
  } catch {
    return false;
  }
}

export function SidebarProvider({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsedState] = useState(() => readCollapsed());
  const [mobileOpen, setMobileOpen] = useState(false);

  const setCollapsed = useCallback((next: boolean) => {
    setCollapsedState(next);
    try {
      localStorage.setItem(STORAGE_KEYS.sidebar, String(next));
    } catch {
      /* storage unavailable */
    }
  }, []);

  const toggle = useCallback(() => setCollapsed(!collapsed), [collapsed, setCollapsed]);

  // Close the mobile drawer whenever the viewport grows past the mobile breakpoint, and
  // restore focus flow by clearing body scroll locking.
  useEffect(() => {
    const query = window.matchMedia('(min-width: 1024px)');
    const listener = (event: MediaQueryListEvent) => {
      if (event.matches) setMobileOpen(false);
    };
    query.addEventListener('change', listener);
    return () => query.removeEventListener('change', listener);
  }, []);

  useEffect(() => {
    if (!mobileOpen) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [mobileOpen]);

  const value = useMemo<SidebarContextValue>(
    () => ({ collapsed, toggle, setCollapsed, mobileOpen, setMobileOpen }),
    [collapsed, toggle, setCollapsed, mobileOpen],
  );

  return <SidebarContext.Provider value={value}>{children}</SidebarContext.Provider>;
}

export function useSidebar(): SidebarContextValue {
  const context = useContext(SidebarContext);
  if (!context) throw new Error('useSidebar must be used inside a SidebarProvider');
  return context;
}
