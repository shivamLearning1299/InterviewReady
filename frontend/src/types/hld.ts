import type {
  Difficulty,
  HLDCategory,
  Timestamped,
  TopicProgressSummary,
  TopicStatus,
  UUID,
} from '@/types/common';
import type { CodeSnippet, CodeSnippetCreate, CodeSnippetUpdate } from '@/types/dsa';

/** HLD curriculum, progress and the 13-section design document — mirrors `schemas/hld.py`. */

export interface HLDTopicSummary extends Timestamped {
  title: string;
  slug: string;
  category: HLDCategory;
  description: string | null;
  difficulty: Difficulty;
  estimated_minutes: number;
  order_index: number;
  is_active: boolean;
  key_concepts: string[];
  progress: TopicProgressSummary;
}

export interface HLDNotes extends Timestamped {
  user_id: UUID;
  hld_topic_id: UUID;
  functional_requirements: string | null;
  non_functional_requirements: string | null;
  capacity_estimation: string | null;
  apis: string | null;
  data_model: string | null;
  high_level_architecture: string | null;
  database_choice: string | null;
  caching: string | null;
  queues: string | null;
  scaling: string | null;
  failure_handling: string | null;
  tradeoffs: string | null;
  final_notes: string | null;
  interview_notes: string | null;
  mistakes: string | null;
}

export interface HLDNotesUpsert {
  functional_requirements?: string;
  non_functional_requirements?: string;
  capacity_estimation?: string;
  apis?: string;
  data_model?: string;
  high_level_architecture?: string;
  database_choice?: string;
  caching?: string;
  queues?: string;
  scaling?: string;
  failure_handling?: string;
  tradeoffs?: string;
  final_notes?: string;
  interview_notes?: string;
  mistakes?: string;
}

export interface HLDTopicDetail extends Omit<HLDTopicSummary, 'progress'> {
  learning_objectives: string[];
  external_url: string | null;
  progress: TopicProgressSummary | null;
  notes: HLDNotes | null;
  code_snippets: HLDSnippet[];
}

export type HLDSnippet = Omit<CodeSnippet, 'problem_id'> & { context_id: UUID };
export type HLDSnippetCreate = CodeSnippetCreate;
export type HLDSnippetUpdate = CodeSnippetUpdate;

export interface HLDProgressUpdateRequest {
  status?: TopicStatus;
  confidence?: number;
  time_spent_minutes?: number;
  schedule_revision?: boolean;
}

export interface HLDTopicFilters {
  search?: string;
  category?: HLDCategory | 'all';
  status?: TopicStatus | 'all';
  order_by?: 'curriculum' | 'category' | 'title' | 'recent';
}

/** The 13 numbered design sections, in interview order. */
export const HLD_NOTE_SECTIONS = [
  { key: 'functional_requirements', label: 'Functional Requirements', index: 1 },
  { key: 'non_functional_requirements', label: 'Non-functional Requirements', index: 2 },
  { key: 'capacity_estimation', label: 'Capacity Estimation', index: 3 },
  { key: 'apis', label: 'API Design', index: 4 },
  { key: 'data_model', label: 'Data Model', index: 5 },
  { key: 'database_choice', label: 'Database Choice', index: 6 },
  { key: 'high_level_architecture', label: 'High-Level Architecture', index: 7 },
  { key: 'caching', label: 'Caching', index: 8 },
  { key: 'queues', label: 'Message Queues', index: 9 },
  { key: 'scaling', label: 'Scaling', index: 10 },
  { key: 'failure_handling', label: 'Failure Handling', index: 11 },
  { key: 'tradeoffs', label: 'Tradeoffs', index: 12 },
  { key: 'final_notes', label: 'Final Notes', index: 13 },
] as const satisfies readonly { key: keyof HLDNotesUpsert; label: string; index: number }[];

/** Supplementary sections that sit outside the numbered design narrative. */
export const HLD_EXTRA_SECTIONS = [
  { key: 'interview_notes', label: 'Interview Notes' },
  { key: 'mistakes', label: 'Mistakes' },
] as const satisfies readonly { key: keyof HLDNotesUpsert; label: string }[];
