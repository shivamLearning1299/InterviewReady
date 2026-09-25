/**
 * Mutable in-memory database backing the mock client.
 *
 * It is built once from `seed.ts`, then mutated by write operations exactly as the real
 * backend would — so marking a problem solved updates the catalog, Today's plan, the
 * revision queue and the statistics together.
 */

import {
  HLD_SEED,
  LLD_SEED,
  DSA_SEED,
  type TopicSeed,
} from '@/mocks/seed';
import {
  addDays,
  createIdFactory,
  dayKey,
  isoAtOffsetDays,
  isoNow,
  seededInt,
  seededRandom,
  startOfDay,
  todayKey,
} from '@/mocks/deterministic';
import type {
  ActivityPoint,
  Difficulty,
  DifficultyBreakdown,
  HLDCategory,
  ItemType,
  LLDCategory,
  ProblemStatus,
  ProgressSummary,
  TopicBreakdown,
  TopicStatus,
  UUID,
} from '@/types/common';
import type {
  Attempt,
  CodeSnippet,
  DSAProblemSummary,
  ProblemNotes,
  Revision,
  TopicOption,
} from '@/types/dsa';
import type { HLDNotes, HLDSnippet, HLDTopicSummary } from '@/types/hld';
import type { LLDNotes, LLDSnippet, LLDTopicSummary } from '@/types/lld';
import type { StudySession, UserDevice, UserSettings } from '@/types/settings';
import type { TodayItem, TodaySection, TodayResponse } from '@/types/today';
import type { AIConversationDetail, AIMessage } from '@/types/ai';

// --------------------------------------------------------------------- constants

export const DEMO_USER_ID: UUID = '00000000-0000-4000-8000-00000000ffff';

const PROBLEM_TOPIC_SLUGS: Record<string, string> = {
  'Arrays & Hashing': 'arrays-hashing',
  'Two Pointers': 'two-pointers',
  'Sliding Window': 'sliding-window',
  Stack: 'stack',
  'Binary Search': 'binary-search',
  'Linked List': 'linked-list',
  Trees: 'trees',
  Graphs: 'graphs',
  Heap: 'heap',
  Backtracking: 'backtracking',
  'Dynamic Programming': 'dynamic-programming',
  Intervals: 'intervals',
  Greedy: 'greedy',
};

const TOPIC_ORDER: string[] = Object.keys(PROBLEM_TOPIC_SLUGS);

/** Statuses that count as "solved" for progress denominators. */
const SOLVED_STATUSES: ProblemStatus[] = ['solved', 'mastered'];
const DONE_STATUSES = new Set<ProblemStatus>(['solved', 'mastered', 'needs_revision']);
const TOPIC_DONE = new Set<TopicStatus>(['completed', 'mastered', 'needs_revision']);

function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)/g, '');
}

// ------------------------------------------------------------------- store shape

interface Store {
  problems: DSAProblemSummary[];
  progress: Map<string, ProgressSummary>;
  notes: Map<string, ProblemNotes>;
  snippets: Map<string, CodeSnippet[]>;
  attempts: Map<string, Attempt[]>;
  revisions: Map<string, Revision>;
  /** `YYYY-MM-DD` -> the set of plan item ids marked complete, keyed by plan date. */
  planCompletion: Map<string, Set<string>>;
  lldTopics: LLDTopicSummary[];
  lldNotes: Map<string, LLDNotes>;
  lldProgress: Map<string, TopicStatus>;
  lldConfidence: Map<string, number>;
  lldSnippets: Map<string, LLDSnippet[]>;
  hldTopics: HLDTopicSummary[];
  hldNotes: Map<string, HLDNotes>;
  hldProgress: Map<string, TopicStatus>;
  hldConfidence: Map<string, number>;
  hldSnippets: Map<string, HLDSnippet[]>;
  settings: UserSettings;
  devices: UserDevice[];
  sessions: StudySession[];
  runningSession: StudySession | null;
  conversations: AIConversationDetail[];
  /** Today's plan item completion, keyed by item id. */
  planItemState: Map<string, boolean>;
  seq: () => string;
  deletedSnippets: Set<string>;
  deletedConversations: Set<UUID>;
}

/**
 * Stable, reload-safe id sequence.
 *
 * The seed must NOT include a timestamp: workspace routes are `/dsa/:problemId`,
 * `/lld/:topicId` and `/hld/:topicId`, so ids that change on every page load would break
 * every bookmarked or shared link — and would make a reload look like the data vanished.
 */
function nextIdFactory(): () => string {
  return createIdFactory('ir-mock-v1');
}

// ------------------------------------------------------------------ construction

function buildProgress(seed: (typeof DSA_SEED)[number]): ProgressSummary {
  const status = seed.status;
  const solved = SOLVED_STATUSES.includes(status);
  const hasRevision = status === 'needs_revision' || status === 'solved' || status === 'mastered';
  const revisionOffset = status === 'needs_revision' ? seededInt(seed.title, -4, 0) : seededInt(seed.title, 1, 21);

  return {
    status,
    attempts: seed.attempts,
    confidence: seed.confidence || null,
    is_favorite: seededInt(`${seed.title}:fav`, 0, 20) === 0,
    next_revision_at: hasRevision ? isoAtOffsetDays(revisionOffset, 9) : null,
    solved_at: solved ? isoAtOffsetDays(-seededInt(seed.title, 3, 60), 20) : null,
    total_time_spent_minutes: solved ? seededInt(seed.title, 45, 240) : seededInt(seed.title, 10, 60),
  };
}

function buildProblems(seq: () => string): {
  problems: DSAProblemSummary[];
  progress: Map<string, ProgressSummary>;
} {
  const progress = new Map<string, ProgressSummary>();
  const problems = DSA_SEED.map((seed, index) => {
    const id = seq();
    const summary = buildProgress(seed);
    progress.set(id, summary);

    const created = isoAtOffsetDays(-120 + index, 12);
    return {
      id,
      created_at: created,
      updated_at: isoAtOffsetDays(-seededInt(seed.title, 1, 30), 18),
      version: 1 + seededInt(`${seed.title}:v`, 0, 4),
      title: seed.title,
      slug: slugify(seed.title),
      external_url: `https://leetcode.com/problems/${slugify(seed.title)}/`,
      source: 'leetcode',
      difficulty: seed.difficulty,
      primary_topic: seed.topic,
      secondary_topics: [],
      patterns: seed.patterns,
      companies: seed.companies,
      problem_type: 'algorithmic',
      order_index: index + 1,
      importance: seed.difficulty === 'hard' ? 4 : 3,
      estimated_minutes: seed.difficulty === 'easy' ? 20 : seed.difficulty === 'medium' ? 35 : 50,
      is_active: true,
      progress: summary,
    } satisfies DSAProblemSummary;
  });

  return { problems, progress };
}

function buildNotes(problems: DSAProblemSummary[], seq: () => string): Map<string, ProblemNotes> {
  const notes = new Map<string, ProblemNotes>();
  for (const problem of problems) {
    const progress = problem.progress;
    // Only problems the user has actually worked on have notes.
    if (progress.attempts === 0) continue;
    if (seededInt(`${problem.title}:notes`, 0, 2) === 0) continue;

    const approaches: Record<string, string> = {
      'Prefix Sum': 'Maintain a running sum and count how many earlier prefixes equal `sum - k`. The count of those prefixes is exactly the number of subarrays ending here.',
      'Hash Map': 'Trade space for time: remember what I have seen so far in a hash map so each element is handled once instead of scanning the rest of the array.',
      DFS: 'Recurse from the entry point, marking cells visited so the same component is never counted twice.',
      'Binary Search': 'Halve the search space each step; the tricky part is writing the boundary conditions correctly.',
    };

    const approachKey = problem.patterns[0] ?? 'Hash Map';
    const approach = approaches[approachKey] ?? `Straightforward ${approachKey} solution after reducing the problem to its core invariant.`;

    notes.set(problem.id, {
      id: seq(),
      created_at: isoAtOffsetDays(-30, 10),
      updated_at: isoAtOffsetDays(-seededInt(problem.title, 1, 12), 21),
      version: 1,
      user_id: DEMO_USER_ID,
      problem_id: problem.id,
      approach,
      notes: `Key insight: ${problem.patterns.join(' + ')}. Handled the edge cases explicitly rather than relying on defaults.`,
      mistakes:
        progress.status === 'needs_revision'
          ? 'Rushed the boundary condition and missed the empty input case. Also forgot to reset state between runs.'
          : 'Initially wrote the brute-force version. Need to state the invariant before coding.',
      revision_notes:
        progress.status === 'needs_revision'
          ? 'Re-derive the invariant from scratch before looking at the code. Do not peek at the previous solution until stuck.'
          : 'Comfortable with the core idea; just re-check the boundary handling.',
      time_complexity: 'O(n)',
      space_complexity: approachKey === 'Two Pointers' ? 'O(1)' : 'O(n)',
    });
  }
  return notes;
}

function buildSnippets(problems: DSAProblemSummary[], seq: () => string): Map<string, CodeSnippet[]> {
  const snippets = new Map<string, CodeSnippet[]>();
  for (const problem of problems) {
    if (problem.progress.attempts === 0) continue;
    if (seededInt(`${problem.title}:code`, 0, 3) === 0) continue;

    const language = 'python' as const;
    const created = isoAtOffsetDays(-seededInt(problem.title, 10, 45), 20);
    const snippet: CodeSnippet = {
      id: seq(),
      created_at: created,
      updated_at: isoAtOffsetDays(-seededInt(problem.title, 1, 8), 22),
      version: 1,
      user_id: DEMO_USER_ID,
      context_type: 'dsa',
      context_id: problem.id,
      problem_id: problem.id,
      title: 'Solution',
      language,
      code: solutionTemplate(problem),
      is_primary: true,
    };
    snippets.set(problem.id, [snippet]);
  }
  return snippets;
}

function solutionTemplate(problem: DSAProblemSummary): string {
  const header = `"""${problem.title} — ${problem.primary_topic} / ${problem.patterns.join(', ')}\n\nApproach: see notes. Complexity: O(n) time, O(n) space.\n"""\n\n`;
  return `${header}def solve(data):\n    seen = {}\n    result = 0\n\n    for index, value in enumerate(data):\n        # Replace with the real recurrence for this problem.\n        remaining = value\n        if remaining in seen:\n            result += seen[remaining]\n        seen[value] = seen.get(value, 0) + 1\n\n    return result\n`;
}

function buildAttempts(
  problems: DSAProblemSummary[],
  seq: () => string,
  outcomes: string[],
): Map<string, Attempt[]> {
  const attempts = new Map<string, Attempt[]>();
  for (const problem of problems) {
    const count = problem.progress.attempts;
    if (count === 0) continue;

    const list: Attempt[] = [];
    for (let index = 0; index < count; index += 1) {
      const offset = -seededInt(`${problem.title}:${index}`, 2, 55);
      const outcome = index === count - 1 && SOLVED_STATUSES.includes(problem.progress.status)
        ? 'solved'
        : (outcomes[seededInt(`${problem.title}:o${index}`, 0, outcomes.length - 1)] ?? 'partial');

      list.push({
        id: seq(),
        created_at: isoAtOffsetDays(offset, 20),
        updated_at: isoAtOffsetDays(offset, 20),
        version: 1,
        user_id: DEMO_USER_ID,
        problem_id: problem.id,
        started_at: isoAtOffsetDays(offset, 19),
        completed_at: isoAtOffsetDays(offset, 20),
        duration_minutes: seededInt(`${problem.title}:d${index}`, 12, 55),
        outcome: outcome as Attempt['outcome'],
        notes:
          outcome === 'solved'
            ? 'Clean run — solved without hints.'
            : outcome === 'solved_with_hint'
              ? 'Needed a hint on the boundary condition.'
              : outcome === 'gave_up'
                ? 'Could not see the reduction. Revisit the pattern.'
                : 'Got most of it; stuck on the final step.',
        confidence: problem.progress.confidence,
      });
    }
    attempts.set(problem.id, list.sort((a, b) => (a.created_at < b.created_at ? 1 : -1)));
  }
  return attempts;
}

function buildRevisions(problems: DSAProblemSummary[], seq: () => string): Map<string, Revision> {
  const revisions = new Map<string, Revision>();

  for (const problem of problems) {
    const progress = problem.progress;

    if (progress.status === 'needs_revision') {
      const dueOffset = seededInt(`${problem.title}:rev`, -5, 0);
      const id = seq();
      revisions.set(id, {
        id,
        created_at: isoAtOffsetDays(dueOffset - 4, 9),
        updated_at: isoAtOffsetDays(dueOffset - 4, 9),
        version: 1,
        user_id: DEMO_USER_ID,
        problem_id: problem.id,
        due_at: isoAtOffsetDays(dueOffset, 9),
        reason: seededInt(`${problem.title}:reason`, 0, 1) === 0 ? 'failed_attempt' : 'low_confidence',
        priority: 1,
        completed: false,
        completed_at: null,
        result: null,
        confidence_before: progress.confidence,
        interval_days: 2,
        notes: null,
        problem_title: problem.title,
        problem_slug: problem.slug,
        problem_difficulty: problem.difficulty,
        problem_topic: problem.primary_topic,
      });
      continue;
    }

    if (!SOLVED_STATUSES.includes(progress.status)) continue;
    // Not every solved problem has an open revision — the queue stays realistic.
    if (seededInt(`${problem.title}:hasrev`, 0, 3) !== 0) continue;

    const dueOffset = seededInt(`${problem.title}:upcoming`, 1, 18);
    const id = seq();
    revisions.set(id, {
      id,
      created_at: isoAtOffsetDays(-seededInt(problem.title, 3, 25), 9),
      updated_at: isoAtOffsetDays(-seededInt(problem.title, 3, 25), 9),
      version: 1,
      user_id: DEMO_USER_ID,
      problem_id: problem.id,
      due_at: isoAtOffsetDays(dueOffset, 9),
      reason: 'scheduled_revision',
      priority: dueOffset <= 3 ? 2 : 3,
      completed: false,
      completed_at: null,
      result: null,
      confidence_before: progress.confidence,
      interval_days: 7,
      notes: null,
      problem_title: problem.title,
      problem_slug: problem.slug,
      problem_difficulty: problem.difficulty,
      problem_topic: problem.primary_topic,
    });
  }

  return revisions;
}

function buildTopicSummary(
  seed: TopicSeed,
  category: LLDCategory | HLDCategory,
  seq: () => string,
  index: number,
): LLDTopicSummary | HLDTopicSummary {
  return {
    id: seq(),
    created_at: isoAtOffsetDays(-100 + index, 12),
    updated_at: isoAtOffsetDays(-seededInt(seed.slug, 1, 20), 15),
    version: 1 + seededInt(`${seed.slug}:v`, 0, 3),
    title: seed.title,
    slug: seed.slug,
    category,
    description: seed.description,
    difficulty: seed.difficulty,
    estimated_minutes: seed.estimatedMinutes,
    order_index: index + 1,
    is_active: true,
    key_concepts: seed.keyConcepts,
    progress: {
      status: seed.status,
      confidence: seed.confidence || null,
      completed_at: TOPIC_DONE.has(seed.status) ? isoAtOffsetDays(-seededInt(seed.slug, 3, 40), 18) : null,
      next_revision_at:
        seed.status === 'needs_revision'
          ? isoAtOffsetDays(-seededInt(seed.slug, 1, 3), 9)
          : TOPIC_DONE.has(seed.status)
            ? isoAtOffsetDays(seededInt(seed.slug, 2, 25), 9)
            : null,
      last_reviewed_at: TOPIC_DONE.has(seed.status) ? isoAtOffsetDays(-seededInt(seed.slug, 1, 20), 20) : null,
      total_time_spent_minutes: TOPIC_DONE.has(seed.status) ? seed.estimatedMinutes : Math.floor(seed.estimatedMinutes * 0.4),
    },
  };
}

function buildDsaTopicOptions(problems: DSAProblemSummary[]): TopicOption[] {
  return TOPIC_ORDER.map((topic) => {
    const inTopic = problems.filter((problem) => problem.primary_topic === topic);
    return {
      slug: PROBLEM_TOPIC_SLUGS[topic] ?? slugify(topic),
      name: topic,
      total: inTopic.length,
      solved: inTopic.filter((problem) => DONE_STATUSES.has(problem.progress.status)).length,
      mastered: inTopic.filter((problem) => problem.progress.status === 'mastered').length,
    };
  }).filter((topic) => topic.total > 0);
}

// ---------------------------------------------------------------- initial store

function createStore(): Store {
  const seq = nextIdFactory();
  const { problems, progress } = buildProblems(seq);
  const outcomes = ['partial', 'solved_with_hint', 'gave_up', 'solved'];

  const lldTopics = LLD_SEED.map(({ seed, category }, index) =>
    buildTopicSummary(seed, category as LLDCategory, seq, index),
  ) as LLDTopicSummary[];

  const hldTopics = HLD_SEED.map(({ seed, category }, index) =>
    buildTopicSummary(seed, category as HLDCategory, seq, index + LLD_SEED.length),
  ) as HLDTopicSummary[];

  return {
    problems,
    progress,
    notes: buildNotes(problems, seq),
    snippets: buildSnippets(problems, seq),
    attempts: buildAttempts(problems, seq, outcomes),
    revisions: buildRevisions(problems, seq),
    planCompletion: new Map(),
    lldTopics,
    lldNotes: new Map(),
    lldProgress: new Map(lldTopics.map((topic) => [topic.id, topic.progress.status])),
    lldConfidence: new Map(lldTopics.map((topic) => [topic.id, topic.progress.confidence ?? 0])),
    lldSnippets: new Map(),
    hldTopics,
    hldNotes: new Map(),
    hldProgress: new Map(hldTopics.map((topic) => [topic.id, topic.progress.status])),
    hldConfidence: new Map(hldTopics.map((topic) => [topic.id, topic.progress.confidence ?? 0])),
    hldSnippets: new Map(),
    settings: {
      id: seq(),
      created_at: isoAtOffsetDays(-120, 8),
      updated_at: isoAtOffsetDays(-2, 8),
      version: 3,
      user_id: DEMO_USER_ID,
      daily_dsa_count: 3,
      daily_revision_count: 8,
      include_lld_daily: true,
      include_hld_daily: true,
      daily_plan_preferences: null,
      revision_preferences: null,
      revision_enabled: true,
      ai_preferences: null,
      ai_auto_reveal_solution: false,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
      preferred_languages: ['python'],
      theme: 'system',
    },
    devices: [
      {
        id: seq(),
        created_at: isoAtOffsetDays(-60, 10),
        updated_at: isoNow(-25),
        version: 4,
        user_id: DEMO_USER_ID,
        device_identifier: 'web-this-browser',
        device_type: 'web',
        display_name: 'Chrome on macOS',
        last_sync_at: isoNow(-25),
        last_pull_cursor: 1284,
      },
      {
        id: seq(),
        created_at: isoAtOffsetDays(-45, 11),
        updated_at: isoNow(-2200),
        version: 2,
        user_id: DEMO_USER_ID,
        device_identifier: 'ios-primary',
        device_type: 'ios',
        display_name: 'iPhone 16 Pro',
        last_sync_at: isoNow(-2200),
        last_pull_cursor: 1240,
      },
    ],
    sessions: buildSessions(seq),
    runningSession: null,
    conversations: buildConversations(seq),
    planItemState: new Map(),
    seq,
    deletedSnippets: new Set(),
    deletedConversations: new Set(),
  };
}

function buildSessions(seq: () => string): StudySession[] {
  const sessions: StudySession[] = [];
  for (let dayOffset = -13; dayOffset <= 0; dayOffset += 1) {
    const count = seededInt(`sessions:${dayOffset}`, 1, 3);
    for (let index = 0; index < count; index += 1) {
      const minutes = seededInt(`duration:${dayOffset}:${index}`, 20, 80);
      const started = isoAtOffsetDays(dayOffset, 9 + index * 2, 15);
      sessions.push({
        id: seq(),
        created_at: started,
        updated_at: started,
        version: 1,
        user_id: DEMO_USER_ID,
        session_type: (['dsa', 'lld', 'hld', 'revision'] as const)[seededInt(`type:${dayOffset}:${index}`, 0, 3)]!,
        context_id: null,
        started_at: started,
        ended_at: new Date(new Date(started).getTime() + minutes * 60_000).toISOString(),
        duration_minutes: minutes,
        is_running: false,
        notes: null,
      });
    }
  }
  return sessions.sort((a, b) => (a.started_at < b.started_at ? 1 : -1));
}

function buildConversations(seq: () => string): AIConversationDetail[] {
  const makeMessage = (role: 'user' | 'assistant', content: string, action: string | null, offset: number): AIMessage => ({
    id: seq(),
    created_at: isoNow(offset),
    updated_at: isoNow(offset),
    version: 1,
    role,
    content,
    action,
    provider: 'groq',
    model: 'llama-3.3-70b-versatile',
    usage: null,
    selected_code: null,
    error: null,
  });

  const seeded: { title: string; context: string; turns: [string, string][] }[] = [
    {
      title: 'Difference between BFS and DFS',
      context: 'general',
      turns: [
        ['Difference between BFS and DFS?', 'BFS explores level by level using a queue, so it finds the shortest path in an unweighted graph. DFS goes deep first with a stack or recursion, so it uses less memory on wide graphs but gives no shortest-path guarantee.\n\nPick BFS when the question asks for a minimum number of steps; pick DFS when you need exhaustive traversal, cycle detection or topological ordering.'],
      ],
    },
    {
      title: 'How does consistent hashing work?',
      context: 'general',
      turns: [
        ['How does consistent hashing work?', 'Nodes and keys are both hashed onto a ring. A key belongs to the first node clockwise from it. Adding or removing a node only remaps the keys in the arc it owns, instead of reshuffling everything.\n\nVirtual nodes — placing each physical node at many ring positions — smooth out the imbalance that otherwise appears with a small number of servers.'],
      ],
    },
    {
      title: 'Minimum Window Substring hint',
      context: 'dsa',
      turns: [
        ['I am stuck on Minimum Window Substring. Just a hint please.', 'Think about maintaining a window that is *valid* rather than complete. Track how many distinct required characters are still missing, and only start shrinking once that count hits zero.\n\nWhat data structure lets you check validity in O(1) as the window moves?'],
      ],
    },
    {
      title: 'Strategy vs Factory pattern',
      context: 'general',
      turns: [
        ['Explain Factory vs Strategy Pattern.', 'Factory answers "how do I create this?" — it centralises object construction so callers never bind to a concrete class. Strategy answers "how do I behave right now?" — it encapsulates interchangeable algorithms behind one interface.\n\nThey often combine: a factory picks which strategy to inject.'],
      ],
    },
  ];

  return seeded.map((entry, index) => {
    const messages: AIMessage[] = [];
    entry.turns.forEach(([question, answer]) => {
      messages.push(makeMessage('user', question, null, -(index + 1) * 60));
      messages.push(makeMessage('assistant', answer, 'general', -(index + 1) * 60 + 1));
    });

    const last = messages[messages.length - 1]!;
    return {
      id: seq(),
      created_at: messages[0]!.created_at,
      updated_at: last.created_at,
      version: 1,
      title: entry.title,
      context_type: entry.context as AIConversationDetail['context_type'],
      context_id: null,
      context_label: entry.context === 'dsa' ? 'Minimum Window Substring' : null,
      provider: 'groq',
      model: 'llama-3.3-70b-versatile',
      message_count: messages.length,
      last_message_at: last.created_at,
      preview: last.content.slice(0, 140),
      messages,
    };
  });
}

// ------------------------------------------------------------------ plan + today

/** Today's three DSA questions, mirroring the design reference. */
function todaysProblemIds(store: Store): string[] {
  const byTitle = new Map(store.problems.map((problem) => [problem.title, problem]));
  const preferred = ['Subarray Sum Equals K', 'Number of Islands', 'Merge Intervals'];
  const chosen = preferred
    .map((title) => byTitle.get(title))
    .filter((problem): problem is DSAProblemSummary => Boolean(problem));

  // Backfill with the next unworked problems if the catalog ever changes.
  if (chosen.length < store.settings.daily_dsa_count) {
    const extras = store.problems.filter(
      (problem) => !chosen.includes(problem) && !DONE_STATUSES.has(problem.progress.status),
    );
    chosen.push(...extras.slice(0, store.settings.daily_dsa_count - chosen.length));
  }
  return chosen.slice(0, store.settings.daily_dsa_count).map((problem) => problem.id);
}

function todaysTopicIds(store: Store, kind: 'lld' | 'hld'): string[] {
  const topics = kind === 'lld' ? store.lldTopics : store.hldTopics;
  const statuses = kind === 'lld' ? store.lldProgress : store.hldProgress;
  const active = topics.filter((topic) => {
    const status = statuses.get(topic.id) ?? 'not_started';
    return status === 'learning' || status === 'needs_revision';
  });
  const fallback = topics.filter((topic) => !TOPIC_DONE.has(statuses.get(topic.id) ?? 'not_started'));
  return (active.length ? active : fallback).slice(0, 1).map((topic) => topic.id);
}

function dueRevisionIds(store: Store): string[] {
  return [...store.revisions.values()]
    .filter((revision) => !revision.completed)
    .sort((a, b) => (a.due_at < b.due_at ? -1 : 1))
    .slice(0, store.settings.daily_revision_count)
    .map((revision) => revision.id);
}

function planItemId(date: string, itemType: ItemType, refId: string): string {
  return `${date}:${itemType}:${refId}`;
}

export function buildTodayItems(store: Store): {
  dsa: TodayItem[];
  lld: TodayItem[];
  hld: TodayItem[];
  revisions: TodayItem[];
} {
  const date = todayKey();
  const completedToday = store.planCompletion.get(date) ?? new Set<string>();

  const dsa: TodayItem[] = todaysProblemIds(store).map((problemId, index) => {
    const problem = store.problems.find((candidate) => candidate.id === problemId)!;
    const id = planItemId(date, 'dsa_new', problemId);
    return {
      id,
      item_type: 'dsa_new',
      position: index + 1,
      problem_id: problemId,
      topic_id: null,
      title: problem.title,
      slug: problem.slug,
      difficulty: problem.difficulty,
      primary_topic: problem.primary_topic,
      patterns: problem.patterns,
      external_url: problem.external_url,
      estimated_minutes: problem.estimated_minutes,
      reason: index === 0 ? 'Weak topic: prefix sums' : index === 1 ? 'Pattern variety' : 'Interview frequency',
      is_completed: store.planItemState.get(id) ?? completedToday.has(id),
      completed_at: null,
      progress: store.progress.get(problemId) ?? null,
    };
  });

  const buildTopicItems = (kind: 'lld' | 'hld'): TodayItem[] => {
    const topics = kind === 'lld' ? store.lldTopics : store.hldTopics;
    const itemType: ItemType = kind;
    return todaysTopicIds(store, kind).map((topicId, index) => {
      const topic = topics.find((candidate) => candidate.id === topicId)!;
      const id = planItemId(date, itemType, topicId);
      return {
        id,
        item_type: itemType,
        position: index + 1,
        problem_id: null,
        topic_id: topicId,
        title: topic.title,
        slug: topic.slug,
        difficulty: topic.difficulty,
        primary_topic: null,
        patterns: topic.key_concepts.slice(0, 2),
        external_url: null,
        estimated_minutes: topic.estimated_minutes,
        reason: kind === 'lld' ? 'Current pattern focus' : 'Core system design concept',
        is_completed: store.planItemState.get(id) ?? completedToday.has(id),
        completed_at: null,
        progress: null,
      };
    });
  };

  const revisions: TodayItem[] = dueRevisionIds(store).map((revisionId, index) => {
    const revision = store.revisions.get(revisionId)!;
    const problem = store.problems.find((candidate) => candidate.id === revision.problem_id);
    const id = planItemId(date, 'dsa_revision', revisionId);
    return {
      id,
      item_type: 'dsa_revision',
      position: index + 1,
      problem_id: revision.problem_id,
      topic_id: null,
      title: revision.problem_title ?? problem?.title ?? 'Revision',
      slug: revision.problem_slug ?? problem?.slug ?? null,
      difficulty: revision.problem_difficulty ?? problem?.difficulty ?? null,
      primary_topic: revision.problem_topic ?? problem?.primary_topic ?? null,
      patterns: problem?.patterns ?? [],
      external_url: problem?.external_url ?? null,
      estimated_minutes: 20,
      reason: revision.reason.replace(/_/g, ' '),
      is_completed: store.planItemState.get(id) ?? completedToday.has(id),
      completed_at: null,
      progress: problem ? store.progress.get(problem.id) ?? null : null,
    };
  });

  return { dsa, lld: buildTopicItems('lld'), hld: buildTopicItems('hld'), revisions };
}

function toSection(items: TodayItem[]): TodaySection {
  return {
    completed: items.filter((item) => item.is_completed).length,
    total: items.length,
    items,
  };
}

export function buildToday(store: Store): TodayResponse {
  const items = buildTodayItems(store);
  const revisionsDue = [...store.revisions.values()].filter(
    (revision) => !revision.completed && new Date(revision.due_at) <= new Date(),
  );

  const overdue = revisionsDue.filter(
    (revision) => startOfDay(new Date(revision.due_at)) < startOfDay(new Date()),
  ).length;

  const sections = [toSection(items.dsa), toSection(items.lld), toSection(items.hld)];
  const studyMinutesToday = store.sessions
    .filter((session) => dayKey(new Date(session.started_at)) === todayKey())
    .reduce((total, session) => total + (session.duration_minutes ?? 0), 0);

  return {
    date: todayKey(),
    timezone: store.settings.timezone,
    plan_id: '00000000-0000-4000-8000-00000000f101',
    status: 'active',
    generated_at: isoAtOffsetDays(0, 6),
    is_completed: sections.every((section) => section.total > 0 && section.completed === section.total),
    streak: buildStreak(store),
    dsa: toSection(items.dsa),
    lld: toSection(items.lld),
    hld: toSection(items.hld),
    revisions: toSection(items.revisions),
    revisions_due: revisionsDue.length,
    revision_summary: {
      total: revisionsDue.length,
      overdue,
      due_today: revisionsDue.length - overdue,
      upcoming: [...store.revisions.values()].filter(
        (revision) => !revision.completed && new Date(revision.due_at) > new Date(),
      ).length,
    },
    study_minutes_today: studyMinutesToday,
    active_session_id: store.runningSession?.id ?? null,
    total_estimated_minutes: items.dsa.reduce(
      (total, item) => total + (item.estimated_minutes ?? 0),
      0,
    ),
  };
}

/** Deterministic streak derived from the study sessions that exist. */
function buildStreak(store: Store): { current: number; longest: number; last_active_date: string; today_active: boolean } {
  const active = new Set(store.sessions.map((session) => dayKey(new Date(session.started_at))));
  let current = 0;
  for (let offset = 0; offset < 60; offset += 1) {
    if (!active.has(dayKey(addDays(new Date(), -offset)))) break;
    current += 1;
  }
  return {
    current: Math.max(current, 1),
    longest: 31,
    last_active_date: todayKey(),
    today_active: store.sessions.some((session) => dayKey(new Date(session.started_at)) === todayKey()),
  };
}

// ------------------------------------------------------------------- statistics

function buildTopicBreakdowns(store: Store): TopicBreakdown[] {
  return TOPIC_ORDER.map((topic) => {
    const inTopic = store.problems.filter((problem) => problem.primary_topic === topic);
    const solved = inTopic.filter((problem) => SOLVED_STATUSES.includes(problem.progress.status)).length;
    const mastered = inTopic.filter((problem) => problem.progress.status === 'mastered').length;
    const attempted = inTopic.filter((problem) => problem.progress.attempts > 0).length;
    const needsRevision = inTopic.filter((problem) => problem.progress.status === 'needs_revision').length;
    const confidences = inTopic
      .map((problem) => problem.progress.confidence ?? 0)
      .filter((value) => value > 0);

    return {
      topic,
      total: inTopic.length,
      solved,
      mastered,
      attempted,
      needs_revision: needsRevision,
      completion_percentage: inTopic.length ? Math.round((solved / inTopic.length) * 100) : 0,
      average_confidence: confidences.length
        ? Number((confidences.reduce((sum, value) => sum + value, 0) / confidences.length).toFixed(1))
        : null,
    };
  })
    .filter((topic) => topic.total > 0)
    .sort((a, b) => b.completion_percentage - a.completion_percentage);
}

function buildDifficultyBreakdowns(store: Store): DifficultyBreakdown[] {
  const order: Difficulty[] = ['easy', 'medium', 'hard'];
  return order.map((difficulty) => {
    const inDifficulty = store.problems.filter((problem) => problem.difficulty === difficulty);
    const solved = inDifficulty.filter((problem) => SOLVED_STATUSES.includes(problem.progress.status)).length;
    const mastered = inDifficulty.filter((problem) => problem.progress.status === 'mastered').length;
    const attempted = inDifficulty.filter((problem) => problem.progress.attempts > 0).length;
    return {
      difficulty,
      total: inDifficulty.length,
      solved,
      mastered,
      attempted,
      completion_percentage: inDifficulty.length
        ? Number(((solved / inDifficulty.length) * 100).toFixed(1))
        : 0,
    };
  });
}

function buildActivitySeries(store: Store, days: number): ActivityPoint[] {
  const points: ActivityPoint[] = [];
  for (let offset = days - 1; offset >= 0; offset -= 1) {
    const date = addDays(new Date(), -offset);
    const key = dayKey(date);
    const random = seededRandom(`activity:${key}`);

    const solved = [...store.progress.values()].filter(
      (progress) => progress.solved_at && dayKey(new Date(progress.solved_at)) === key,
    ).length;

    const attempted = offset === 0 ? 2 : Math.floor(random() * 3);
    const revisions = Math.floor(random() * 4);
    const minutes = store.sessions
      .filter((session) => dayKey(new Date(session.started_at)) === key)
      .reduce((total, session) => total + (session.duration_minutes ?? 0), 0);

    points.push({
      date: key,
      problems_attempted: attempted,
      problems_solved: solved || (offset === 0 ? 1 : 0),
      revisions_completed: revisions,
      study_minutes: minutes || seededInt(`minutes:${key}`, 0, 70),
      activity_count: attempted + revisions + (minutes > 0 ? 1 : 0),
    });
  }
  return points;
}

// ------------------------------------------------------------------- export API

const store: Store = createStore();

/** Rebuild everything — used by the settings screen's "reset demo data" action. */
export function resetStore(): void {
  const fresh = createStore();
  store.problems = fresh.problems;
  store.progress = fresh.progress;
  store.notes = fresh.notes;
  store.snippets = fresh.snippets;
  store.attempts = fresh.attempts;
  store.revisions = fresh.revisions;
  store.planCompletion = fresh.planCompletion;
  store.lldTopics = fresh.lldTopics;
  store.lldNotes = fresh.lldNotes;
  store.lldProgress = fresh.lldProgress;
  store.lldConfidence = fresh.lldConfidence;
  store.lldSnippets = fresh.lldSnippets;
  store.hldTopics = fresh.hldTopics;
  store.hldNotes = fresh.hldNotes;
  store.hldProgress = fresh.hldProgress;
  store.hldConfidence = fresh.hldConfidence;
  store.hldSnippets = fresh.hldSnippets;
  store.settings = fresh.settings;
  store.devices = fresh.devices;
  store.sessions = fresh.sessions;
  store.runningSession = null;
  store.conversations = fresh.conversations;
  store.planItemState = fresh.planItemState;
  store.seq = fresh.seq;
  store.deletedSnippets = fresh.deletedSnippets;
  store.deletedConversations = fresh.deletedConversations;
}

/** A short artificial latency so loading and empty states behave like the real thing. */
export function simulateLatency(ms = 220): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export {
  store,
  buildStreak,
  buildActivitySeries,
  buildTopicBreakdowns,
  buildDifficultyBreakdowns,
  buildDsaTopicOptions,
  buildTopicSummary,
  SOLVED_STATUSES,
  DONE_STATUSES,
  TOPIC_DONE,
  PROBLEM_TOPIC_SLUGS,
  TOPIC_ORDER,
  slugify,
};

export type { Store, TopicSeed };
