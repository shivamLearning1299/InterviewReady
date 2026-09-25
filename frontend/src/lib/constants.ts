import type { HLDCategory, LLDCategory, Language } from '@/types/common';

/** Static configuration shared across the app. */

export interface NavItem {
  label: string;
  to: string;
  /** Lucide icon name, resolved in the sidebar so this stays framework-agnostic. */
  icon: string;
  /** Route prefixes that should keep this item highlighted. */
  matchPrefixes?: string[];
  description: string;
}

/**
 * Primary navigation. Order is deliberate: the things used most often come first.
 */
export const NAV_ITEMS: NavItem[] = [
  { label: 'Today', to: '/', icon: 'Sun', description: "Today's plan" },
  { label: 'DSA', to: '/dsa', icon: 'Code2', description: 'Problem catalog' },
  {
    label: 'Revisions',
    to: '/revisions',
    icon: 'RotateCcw',
    description: 'Spaced repetition queue',
  },
  { label: 'LLD', to: '/lld', icon: 'Boxes', description: 'Low-level design' },
  { label: 'HLD', to: '/hld', icon: 'Network', description: 'High-level design' },
  { label: 'Statistics', to: '/stats', icon: 'BarChart3', description: 'Progress analytics' },
  { label: 'AI Tutor', to: '/ai', icon: 'Sparkles', description: 'Ask questions, get tutored' },
  { label: 'Settings', to: '/settings', icon: 'Settings', description: 'Preferences and data' },
];

/** Languages offered in the code editor, with Monaco language ids. */export interface LanguageOption {
  value: Language;
  label: string;
  /** Monaco's language id. */
  monaco: string;
  extension: string;
  /** Whether the mock editor offers a starter snippet for it. */
  starter: string;
}

export const LANGUAGE_OPTIONS: LanguageOption[] = [
  {
    value: 'python',
    label: 'Python',
    monaco: 'python',
    extension: 'py',
    starter: 'class Solution:\n    def solve(self, data):\n        pass\n',
  },
  {
    value: 'java',
    label: 'Java',
    monaco: 'java',
    extension: 'java',
    starter: 'class Solution {\n    public int solve(int[] data) {\n        return 0;\n    }\n}\n',
  },
  {
    value: 'cpp',
    label: 'C++',
    monaco: 'cpp',
    extension: 'cpp',
    starter: '#include <vector>\nusing namespace std;\n\nclass Solution {\npublic:\n    int solve(vector<int>& data) {\n        return 0;\n    }\n};\n',
  },
  {
    value: 'swift',
    label: 'Swift',
    monaco: 'swift',
    extension: 'swift',
    starter: 'class Solution {\n    func solve(_ data: [Int]) -> Int {\n        return 0\n    }\n}\n',
  },
  {
    value: 'javascript',
    label: 'JavaScript',
    monaco: 'javascript',
    extension: 'js',
    starter: '/**\n * @param {number[]} data\n * @return {number}\n */\nfunction solve(data) {\n  return 0;\n}\n',
  },
  {
    value: 'typescript',
    label: 'TypeScript',
    monaco: 'typescript',
    extension: 'ts',
    starter: 'function solve(data: number[]): number {\n  return 0;\n}\n',
  },
  {
    value: 'go',
    label: 'Go',
    monaco: 'go',
    extension: 'go',
    starter: 'package main\n\nfunc solve(data []int) int {\n\treturn 0\n}\n',
  },
  {
    value: 'other',
    label: 'Other',
    monaco: 'plaintext',
    extension: 'txt',
    starter: '',
  },
];

export function languageLabel(value: string | null | undefined): string {
  return LANGUAGE_OPTIONS.find((option) => option.value === value)?.label ?? 'Plain text';
}

export function monacoLanguage(value: string | null | undefined): string {
  return LANGUAGE_OPTIONS.find((option) => option.value === value)?.monaco ?? 'plaintext';
}

/** Time-range options for the statistics charts. */
export const ACTIVITY_RANGE_OPTIONS = [
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' },
  { value: '1y', label: '1 year' },
] as const;

/** Suggested values for free-text filter inputs. */
export const COMMON_COMPANIES = [
  'Amazon',
  'Google',
  'Meta',
  'Microsoft',
  'Apple',
  'Uber',
  'Bloomberg',
  'Airbnb',
] as const;

/** Quick-prompt chips on the AI Tutor page. */
export const AI_SUGGESTIONS: { label: string; prompt: string; context: string }[] = [
  { label: 'Explain dynamic programming', prompt: 'Explain dynamic programming from first principles.', context: 'general' },
  { label: 'BFS vs DFS', prompt: 'Difference between BFS and DFS, and when to use each?', context: 'general' },
  { label: 'How does consistent hashing work?', prompt: 'How does consistent hashing work?', context: 'general' },
  { label: 'Factory vs Strategy pattern', prompt: 'Explain Factory vs Strategy Pattern with when to use each.', context: 'general' },
  { label: 'Interview me on graphs', prompt: 'Interview me on graphs. Ask one question at a time.', context: 'dsa' },
  { label: 'Give me questions around caching', prompt: 'Give me interview questions around caching.', context: 'hld' },
];

/** Keyboard shortcut label differs per platform. */
export const IS_MAC =
  typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);

export const MOD_KEY = IS_MAC ? '⌘' : 'Ctrl';

/** Study timer limits, mirroring the server's caps. */
export const TIMER = {
  /** Sessions longer than this are capped rather than rejected. */
  maxMinutes: 240,
  /** Nudge the user if a timer has clearly been left running. */
  idleWarningMinutes: 90,
} as const;

/** Catalog category labels — shared by the LLD/HLD screens and the mock seed data. */
export const LLD_CATEGORY_LABELS: Record<LLDCategory, string> = {
  fundamentals: 'Fundamentals',
  design_patterns: 'Design Patterns',
  design_exercises: 'Design Problems',
};

export const HLD_CATEGORY_LABELS: Record<HLDCategory, string> = {
  fundamentals: 'Fundamentals',
  system_design: 'System Design Problems',
};
