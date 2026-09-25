import { useMemo } from 'react';

import type { PageContext } from '@/features/ai/page-context';

/**
 * Memoises a `PageContext` for the current render.
 *
 * This is a pure derivation: it never touches the network, never reads a query cache, and
 * never reads server state — it only assembles what the caller passes in from props/state.
 *
 * The `deps` argument is deliberately required: the context is re-computed when the unsaved
 * drafts change (typed-but-unsubmitted note fields, the live editor buffer, the current
 * selection). A stale context would let the tutor answer against saved-but-outdated content,
 * which is exactly the failure the contract's `draft_fields` / `code` slots exist to prevent.
 *
 * @param builder Called only when `deps` change; must be cheap and side-effect free.
 * @param deps Inputs the builder closes over — draft fields, code, selection, active tab.
 */
export function usePageContext(
  builder: () => PageContext,
  deps: readonly unknown[],
): PageContext {
  // eslint-disable-next-line react-hooks/exhaustive-deps -- `deps` is the caller's explicit
  // dependency list; `builder` is intentionally excluded so callers may pass an inline arrow.
  return useMemo(builder, deps);
}
