import { useMemo, useRef } from 'react';

import type { PageContext } from '@/features/ai/page-context';

/** Stable identity used when a caller supplies no `deps`: recompute on every render. */
const ALWAYS: readonly unknown[] = [];

/**
 * Memoises a `PageContext` for the current render.
 *
 * This is a pure derivation: it never touches the network, never reads a query cache, and
 * never reads server state — it only assembles what the caller passes in from props/state.
 *
 * `deps` lists the inputs the builder closes over — the unsaved drafts (typed-but-unsubmitted
 * note fields, the live editor buffer, the current selection). Getting it wrong is a silent
 * correctness bug in both directions, so `usePageContext` treats a missing list as "always
 * recompute" rather than trusting the caller to remember:
 *
 * - **Omitting `deps` is safe.** The context is rebuilt on every render. That costs one cheap
 *   pure function call per render, but it can never serve a stale context — which is what the
 *   contract's `draft_fields` / `code` slots exist to prevent. A stale context would let the
 *   tutor answer against saved-but-outdated content.
 * - **`deps: []` is a footgun and must not be read as the "skip `deps`" spelling.** React
 *   treats a frozen empty list as "this never changes", so the builder runs once and the
 *   context is then permanently stale. It was previously accepted silently; it is now the one
 *   remaining way to get a stale context, and it should only be used when the builder truly
 *   reads nothing reactive (it should then be hoisted to a module constant instead).
 * - **An inline array literal (`deps: [note, code]`) defeats memoisation** — a new array each
 *   render makes `useMemo` recompute unconditionally, so it is equivalent to omitting `deps`
 *   while *looking* like it was tuned. Prefer omitting `deps` when unsure: the failure mode
 *   is wasted work, not a wrong answer.
 *
 * @param builder Called when `deps` change, or on every render when `deps` is omitted; must
 *   be cheap and side-effect free.
 * @param deps Inputs the builder closes over, or omitted/nullish to recompute every render.
 */
export function usePageContext(
  builder: () => PageContext,
  deps?: readonly unknown[] | null,
): PageContext {
  // `undefined` and `null` both mean "recompute every render". `ALWAYS` is a module-level
  // constant, not a fresh literal, so the fallback is referentially stable across renders —
  // an inline `[]` here would make the fallback itself inconsistent.
  const resolvedDeps = deps ?? ALWAYS;

  // Kept in a ref so `builder` can stay out of the dependency list: callers routinely pass an
  // inline arrow, and including it would recompute on every render even when `deps` is stable.
  const builderRef = useRef(builder);
  builderRef.current = builder;

  // eslint-disable-next-line react-hooks/exhaustive-deps -- `resolvedDeps` is the caller's
  // explicit dependency list; `builder` is read through a ref so an inline arrow stays cheap.
  return useMemo(() => builderRef.current(), resolvedDeps);
}
