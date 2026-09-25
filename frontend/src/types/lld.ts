import type {
  Difficulty,
  LLDCategory,
  Timestamped,
  TopicProgressSummary,
  TopicStatus,
  UUID,
} from '@/types/common';
import type { CodeSnippet, CodeSnippetCreate, CodeSnippetUpdate } from '@/types/dsa';

/** LLD curriculum, progress, notes and code — mirrors `schemas/lld.py`. */

export interface LLDTopicSummary extends Timestamped {
  title: string;
  slug: string;
  category: LLDCategory;
  description: string | null;
  difficulty: Difficulty;
  estimated_minutes: number;
  order_index: number;
  is_active: boolean;
  key_concepts: string[];
  progress: TopicProgressSummary;
}

export interface LLDNotes extends Timestamped {
  user_id: UUID;
  lld_topic_id: UUID;
  summary: string | null;
  design_explanation: string | null;
  class_responsibilities: string | null;
  relationships: string | null;
  design_notes: string | null;
  mistakes: string | null;
  revision_notes: string | null;
  patterns_used: string[];
  class_diagram: unknown[] | null;
}

/** The editable design-exercise sections, in the order the UI presents them. */
export interface LLDNotesUpsert {
  summary?: string;
  design_explanation?: string;
  class_responsibilities?: string;
  relationships?: string;
  design_notes?: string;
  mistakes?: string;
  revision_notes?: string;
  patterns_used?: string[];
  class_diagram?: unknown[];
}

export interface LLDTopicDetail extends Omit<LLDTopicSummary, 'progress'> {
  learning_objectives: string[];
  external_url: string | null;
  progress: TopicProgressSummary | null;
  notes: LLDNotes | null;
  code_snippets: LLDSnippet[];
}

export type LLDSnippet = Omit<CodeSnippet, 'problem_id'> & { context_id: UUID };
export type LLDSnippetCreate = CodeSnippetCreate;
export type LLDSnippetUpdate = CodeSnippetUpdate;

export interface LLDProgressUpdateRequest {
  status?: TopicStatus;
  confidence?: number;
  time_spent_minutes?: number;
  schedule_revision?: boolean;
}

export interface LLDTopicFilters {
  search?: string;
  category?: LLDCategory | 'all';
  status?: TopicStatus | 'all';
  order_by?: 'curriculum' | 'category' | 'title' | 'recent';
}

/** Section labels for the LLD design workspace. */
export const LLD_NOTE_SECTIONS = [
  { key: 'summary', label: 'Description' },
  { key: 'design_explanation', label: 'Design Explanation' },
  { key: 'class_responsibilities', label: 'Entities & Responsibilities' },
  { key: 'relationships', label: 'Relationships' },
  { key: 'design_notes', label: 'Design Notes' },
  { key: 'mistakes', label: 'Mistakes' },
  { key: 'revision_notes', label: 'Revision Notes' },
] as const satisfies readonly { key: keyof LLDNotesUpsert; label: string }[];
