import type { AIContextType, Difficulty, ProblemStatus, TopicStatus } from '@/types/common';

/** Global search results (composed client-side from the catalog + topic + notes routes). */

export type SearchResultKind = 'dsa' | 'topic' | 'lld' | 'hld' | 'note' | 'pattern';

export interface SearchResult {
  id: string;
  kind: SearchResultKind;
  title: string;
  subtitle?: string;
  href: string;
  difficulty?: Difficulty;
  status?: ProblemStatus | TopicStatus;
  meta?: string[];
}

export interface SearchGroup {
  kind: SearchResultKind;
  label: string;
  results: SearchResult[];
}

export interface SearchScopeOption {
  value: AIContextType | 'all';
  label: string;
}
