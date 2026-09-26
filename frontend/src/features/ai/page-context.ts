/**
 * PageContext — the wire-shaped description of what the user is looking at.
 *
 * Mirrors §1 of `docs/integration/05-contract-ai.md`. The JSON produced here is byte-for-byte
 * the frozen contract, so every optional slot is normalised to an explicit `null` rather than
 * `undefined` (`JSON.stringify` drops `undefined` keys, which would silently break the shape).
 *
 * CRITICAL: for DSA, `entity_id` is the problem **slug** (e.g. `"two-sum"`), never a UUID.
 * For LLD/HLD topics it is the topic UUID.
 */

import type { Language } from '@/types/common';

// --------------------------------------------------------------------------- types

export type PageType =
  | 'today'
  | 'dsa_problem'
  | 'dsa_catalog'
  | 'lld_topic'
  | 'hld_topic'
  | 'revisions'
  | 'stats'
  | 'settings'
  | 'general';

export type EntityType = 'dsa' | 'lld' | 'hld' | 'plan' | 'revision' | 'none';

/** Unsaved code in the editor: `{language, content}`, never the saved snippet. */
export interface PageCodeContext {
  language: string;
  content: string;
}

export interface PageContext {
  page_type: PageType;
  entity_type: EntityType;
  entity_id: string | null;
  active_tab: string | null;
  selected_text: string | null;
  focused_field: string | null;
  draft_fields: Record<string, string> | null;
  code: PageCodeContext | null;
}

/** The unsaved editor state every page helper accepts. All slots are optional. */
export interface PageDraftInput {
  activeTab?: string | null;
  selectedText?: string | null;
  focusedField?: string | null;
  draftFields?: Record<string, string> | null;
  code?: PageCodeContext | null;
}

export interface BuildPageContextInput extends PageDraftInput {
  pageType: PageType;
  entityType: EntityType;
  /**
   * DSA: the problem **slug** (e.g. `'two-sum'`), never a UUID. LLD/HLD: the topic UUID.
   *
   * The DSA catalog is keyed by slug (`dsa_problems.id TEXT`), so the slug is the id —
   * it just does not look like one. Do not substitute `problem.id` in a consumer that
   * expects a UUID, or vice versa: `AIChatRequest.context_id` is a `str` that accepts
   * both shapes server-side, which is why a mismatch fails silently instead of loudly.
   */
  entityId?: string | null;
}

// ------------------------------------------------------------------------ helpers

/** `''` and whitespace-only drafts mean "nothing here", which the contract spells `null`. */
function normaliseText(value: string | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  return value.length > 0 ? value : null;
}

function normaliseCode(code: PageCodeContext | null | undefined): PageCodeContext | null {
  if (!code) return null;
  const content = normaliseText(code.content);
  if (content === null) return null;
  return { language: code.language, content };
}

function normaliseFields(
  fields: Record<string, string> | null | undefined,
): Record<string, string> | null {
  if (!fields) return null;
  const entries = Object.entries(fields).filter(([, value]) => typeof value === 'string');
  if (entries.length === 0) return null;
  return Object.fromEntries(entries) as Record<string, string>;
}

/** Normalises optional inputs into the exact wire shape. */
export function buildPageContext(input: BuildPageContextInput): PageContext {
  return {
    page_type: input.pageType,
    entity_type: input.entityType,
    entity_id: normaliseText(input.entityId),
    active_tab: normaliseText(input.activeTab),
    selected_text: normaliseText(input.selectedText),
    focused_field: normaliseText(input.focusedField),
    draft_fields: normaliseFields(input.draftFields),
    code: normaliseCode(input.code),
  };
}

// ---------------------------------------------------------------- page builders

/**
 * DSA problem workspace. `entityId` is the problem slug (`problem.slug`), not `problem.id`.
 * `draftFields` are the unsaved NotesEditor fields; `code` is the unsaved editor buffer.
 */
export function dsaProblemPageContext(
  problemSlug: string,
  draft: PageDraftInput = {},
): PageContext {
  return buildPageContext({
    pageType: 'dsa_problem',
    entityType: 'dsa',
    entityId: problemSlug,
    activeTab: draft.activeTab,
    selectedText: draft.selectedText,
    focusedField: draft.focusedField,
    draftFields: draft.draftFields,
    code: draft.code,
  });
}

/** DSA catalog list. No single entity is in focus, so `entity_id` stays null. */
export function dsaCatalogPageContext(draft: PageDraftInput = {}): PageContext {
  return buildPageContext({
    pageType: 'dsa_catalog',
    entityType: 'none',
    entityId: null,
    activeTab: draft.activeTab,
    selectedText: draft.selectedText,
    focusedField: draft.focusedField,
    draftFields: draft.draftFields,
    code: draft.code,
  });
}

/** LLD design workspace. `topicId` is the topic UUID. */
export function lldTopicPageContext(topicId: string, draft: PageDraftInput = {}): PageContext {
  return buildPageContext({
    pageType: 'lld_topic',
    entityType: 'lld',
    entityId: topicId,
    activeTab: draft.activeTab,
    selectedText: draft.selectedText,
    focusedField: draft.focusedField,
    draftFields: draft.draftFields,
    code: draft.code,
  });
}

/** HLD design workspace. `topicId` is the topic UUID. */
export function hldTopicPageContext(topicId: string, draft: PageDraftInput = {}): PageContext {
  return buildPageContext({
    pageType: 'hld_topic',
    entityType: 'hld',
    entityId: topicId,
    activeTab: draft.activeTab,
    selectedText: draft.selectedText,
    focusedField: draft.focusedField,
    draftFields: draft.draftFields,
    code: draft.code,
  });
}

/** Today. The plan entity is not addressable by id client-side, so `entity_id` is null. */
export function todayPageContext(draft: PageDraftInput = {}): PageContext {
  return buildPageContext({
    pageType: 'today',
    entityType: 'plan',
    entityId: null,
    activeTab: draft.activeTab,
    selectedText: draft.selectedText,
    focusedField: draft.focusedField,
    draftFields: draft.draftFields,
    code: draft.code,
  });
}

/** Revisions list. Per-revision notes arrive as unsaved drafts keyed by revision id. */
export function revisionsPageContext(draft: PageDraftInput = {}): PageContext {
  return buildPageContext({
    pageType: 'revisions',
    entityType: 'revision',
    entityId: null,
    activeTab: draft.activeTab,
    selectedText: draft.selectedText,
    focusedField: draft.focusedField,
    draftFields: draft.draftFields,
    code: draft.code,
  });
}

/** Stats dashboard. */
export function statsPageContext(draft: PageDraftInput = {}): PageContext {
  return buildPageContext({
    pageType: 'stats',
    entityType: 'none',
    entityId: null,
    activeTab: draft.activeTab,
    selectedText: draft.selectedText,
    focusedField: draft.focusedField,
    draftFields: draft.draftFields,
    code: draft.code,
  });
}

/** Settings. Kept here so every page type has a symmetric builder. */
export function settingsPageContext(draft: PageDraftInput = {}): PageContext {
  return buildPageContext({
    pageType: 'settings',
    entityType: 'none',
    entityId: null,
    activeTab: draft.activeTab,
    selectedText: draft.selectedText,
    focusedField: draft.focusedField,
    draftFields: draft.draftFields,
    code: draft.code,
  });
}

/** Fallback for screens with no meaningful context (e.g. a 404). */
export function generalPageContext(draft: PageDraftInput = {}): PageContext {
  return buildPageContext({
    pageType: 'general',
    entityType: 'none',
    entityId: null,
    activeTab: draft.activeTab,
    selectedText: draft.selectedText,
    focusedField: draft.focusedField,
    draftFields: draft.draftFields,
    code: draft.code,
  });
}

/** Editor languages are plain strings on the wire; this narrows the app's `Language` union. */
export function codeContext(language: Language | string, content: string): PageCodeContext {
  return { language, content };
}
