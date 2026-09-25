import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';

/**
 * Resets scroll position on navigation.
 *
 * The scroll container is `<main>`, not `window`, so the usual router scroll restoration
 * does not apply. Tab switches that should keep position pass `?tab=` and are deliberately
 * still reset — landing at the top of a new problem is the expected behaviour.
 */
export function ScrollToTop() {
  const { pathname } = useLocation();

  useEffect(() => {
    const container = document.querySelector('main');
    if (container) container.scrollTop = 0;
  }, [pathname]);

  return null;
}
