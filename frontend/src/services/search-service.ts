/**
 * Global search.
 *
 * The backend has no dedicated search endpoint, so this fans out across the routes that do
 * exist — DSA problems, patterns, LLD/HLD topics and the user's own notes — then ranks and
 * groups the results. Fanning out in parallel keeps the palette responsive.
 */

import type { ApiClient } from '@/api/contract';
import type { SearchGroup, SearchResult, SearchResultKind } from '@/types/search';
import type { DSAProblemSummary } from '@/types/dsa';
import type { HLDTopicSummary } from '@/types/hld';
import type { LLDTopicSummary } from '@/types/lld';

const KIND_LABEL: Record<SearchResultKind, string> = {
  dsa: 'Problems',
  pattern: 'Patterns',
  lld: 'Low-Level Design',
  hld: 'High-Level Design',
  topic: 'Topics',
  note: 'Your Notes',
};

const KIND_ORDER: SearchResultKind[] = ['dsa', 'topic', 'pattern', 'lld', 'hld', 'note'];

const MAX_PER_GROUP = 6;
const MIN_TERM_LENGTH = 2;

interface Searchable {
  kind: SearchResultKind;
  result: SearchResult;
}

function score(text: string, term: string): number {
  const haystack = text.toLowerCase();
  const needle = term.toLowerCase();

  if (haystack === needle) return 100;
  if (haystack.startsWith(needle)) return 80;
  if (haystack.includes(needle)) return 55;

  // Word-boundary partial match: "slid" should still find "Sliding Window".
  const words = haystack.split(/[^a-z0-9]+/);
  if (words.some((word) => word.startsWith(needle))) return 40;

  return 0;
}

function problemResult(problem: DSAProblemSummary, term: string): Searchable | null {
  const titleScore = score(problem.title, term);
  const topicScore = score(problem.primary_topic, term) * 0.6;
  const best = Math.max(titleScore, topicScore);
  if (best === 0) return null;

  return {
    kind: 'dsa',
    result: {
      id: problem.id,
      kind: 'dsa',
      title: problem.title,
      subtitle: `${problem.primary_topic} • ${problem.patterns.join(' • ')}`,
      href: `/dsa/${problem.id}`,
      difficulty: problem.difficulty,
      status: problem.progress.status,
      meta: problem.companies.slice(0, 3),
      // Rank boost carried on the result so sorting stays a pure comparison.
      ...({ _score: best } as object),
    },
  };
}

function topicResult(
  topic: LLDTopicSummary | HLDTopicSummary,
  kind: 'lld' | 'hld',
  term: string,
): Searchable | null {
  const titleScore = score(topic.title, term);
  const descriptionScore = score(topic.description ?? '', term) * 0.5;
  const best = Math.max(titleScore, descriptionScore);
  if (best === 0) return null;

  return {
    kind,
    result: {
      id: topic.id,
      kind,
      title: topic.title,
      subtitle: topic.description ?? topic.category.replace(/_/g, ' '),
      href: `/${kind}/${topic.id}`,
      difficulty: topic.difficulty,
      status: topic.progress.status,
      meta: topic.key_concepts.slice(0, 3),
      ...({ _score: best } as object),
    },
  };
}

function patternResults(problems: DSAProblemSummary[], term: string): Searchable[] {
  const counts = new Map<string, number>();
  problems.forEach((problem) => {
    problem.patterns.forEach((pattern) => counts.set(pattern, (counts.get(pattern) ?? 0) + 1));
  });

  return [...counts.entries()]
    .map(([pattern, count]) => ({ pattern, count, value: score(pattern, term) }))
    .filter((entry) => entry.value > 0)
    .map((entry) => ({
      kind: 'pattern' as const,
      result: {
        id: `pattern:${entry.pattern}`,
        kind: 'pattern' as const,
        title: entry.pattern,
        subtitle: `${entry.count} problem${entry.count === 1 ? '' : 's'}`,
        href: `/dsa?pattern=${encodeURIComponent(entry.pattern)}`,
        ...({ _score: entry.value } as object),
      },
    }));
}

function noteResults(term: string, notes: { problemId: string; title: string; text: string }[]): Searchable[] {
  return notes
    .map((note) => ({ note, value: score(note.text, term) }))
    .filter((entry) => entry.value > 0)
    .map((entry) => ({
      kind: 'note' as const,
      result: {
        id: `note:${entry.note.problemId}`,
        kind: 'note' as const,
        title: entry.note.title,
        subtitle: entry.note.text.slice(0, 120),
        href: `/dsa/${entry.note.problemId}?tab=notes`,
        ...({ _score: entry.value } as object),
      },
    }));
}

function readScore(result: SearchResult): number {
  const value = (result as SearchResult & { _score?: number })._score;
  return typeof value === 'number' ? value : 0;
}

/**
 * Runs the fan-out and returns grouped, ranked results.
 *
 * Every branch is optional: a failing request degrades that group rather than breaking the
 * palette, which matters when the user types before the backend is reachable.
 */
export async function globalSearch(
  client: ApiClient,
  term: string,
  kinds?: SearchResultKind[],
): Promise<SearchGroup[]> {
  const trimmed = term.trim();
  if (trimmed.length < MIN_TERM_LENGTH) return [];

  const wanted = new Set<SearchResultKind>(
    kinds && kinds.length > 0 ? kinds : KIND_ORDER,
  );

  const [problemsPage, lldPage, hldPage] = await Promise.all([
    client.dsa.listProblems({ search: trimmed, limit: 40 }).catch(() => null),
    client.lld.listTopics({ search: trimmed, limit: 20 }).catch(() => null),
    client.hld.listTopics({ search: trimmed, limit: 20 }).catch(() => null),
  ]);

  const problems = problemsPage?.items ?? [];
  const found: Searchable[] = [];

  if (wanted.has('dsa')) {
    problems.forEach((problem) => {
      const result = problemResult(problem, trimmed);
      if (result) found.push(result);
    });
  }

  if (wanted.has('lld')) {
    (lldPage?.items ?? []).forEach((topic) => {
      const result = topicResult(topic, 'lld', trimmed);
      if (result) found.push(result);
    });
  }

  if (wanted.has('hld')) {
    (hldPage?.items ?? []).forEach((topic) => {
      const result = topicResult(topic, 'hld', trimmed);
      if (result) found.push(result);
    });
  }

  if (wanted.has('pattern')) {
    found.push(...patternResults(problems, trimmed));
  }

  // Notes are searched over problems the term already surfaced — the notes endpoint is
  // per-problem, so probing the whole catalog would be N round trips.
  if (wanted.has('note') && problems.length > 0 && problems.length <= 12) {
    const details = await Promise.all(
      problems.map((problem) => client.dsa.getProblem(problem.id).catch(() => null)),
    );
    const notes = details
      .filter((detail): detail is NonNullable<typeof detail> => Boolean(detail?.notes))
      .map((detail) => ({
        problemId: detail.id,
        title: detail.title,
        text: [
          detail.notes?.approach,
          detail.notes?.notes,
          detail.notes?.mistakes,
          detail.notes?.revision_notes,
        ]
          .filter(Boolean)
          .join(' '),
      }));
    found.push(...noteResults(trimmed, notes));
  }

  const groups: SearchGroup[] = [];
  for (const kind of KIND_ORDER) {
    if (!wanted.has(kind)) continue;
    const inGroup = found
      .filter((entry) => entry.kind === kind)
      .sort((a, b) => readScore(b.result) - readScore(a.result) || a.result.title.localeCompare(b.result.title))
      .slice(0, MAX_PER_GROUP);

    if (inGroup.length === 0) continue;
    groups.push({
      kind,
      label: KIND_LABEL[kind],
      results: inGroup.map((entry) => entry.result),
    });
  }

  return groups;
}

export { KIND_LABEL, KIND_ORDER };
