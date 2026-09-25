/**
 * Seed catalogs for the mock data layer.
 *
 * Shaped to match the real API payloads (`DSAProblemSummary`, `LLDTopicSummary`,
 * `HLDTopicSummary`) so components cannot tell mock data from live data.
 */

import type { Difficulty, HLDCategory, LLDCategory, ProblemStatus, TopicStatus } from '@/types/common';

// ------------------------------------------------------------------- DSA catalog

export interface DsaSeed {
  title: string;
  difficulty: Difficulty;
  topic: string;
  patterns: string[];
  companies: string[];
  status: ProblemStatus;
  confidence: number;
  attempts: number;
}

/**
 * A 64-problem catalog spanning the standard interview curriculum. The first three
 * problems are the ones the Today screen schedules.
 */
export const DSA_SEED: DsaSeed[] = [
  // ------------------------------------------------------------ Arrays & Hashing
  { title: 'Subarray Sum Equals K', difficulty: 'medium', topic: 'Arrays & Hashing', patterns: ['Prefix Sum', 'Hash Map'], companies: ['Amazon', 'Google', 'Meta'], status: 'attempted', confidence: 2, attempts: 2 },
  { title: 'Two Sum', difficulty: 'easy', topic: 'Arrays & Hashing', patterns: ['Hash Map'], companies: ['Amazon', 'Microsoft'], status: 'mastered', confidence: 5, attempts: 4 },
  { title: 'Top K Frequent Elements', difficulty: 'medium', topic: 'Arrays & Hashing', patterns: ['Heap', 'Bucket Sort'], companies: ['Amazon', 'Meta'], status: 'solved', confidence: 3, attempts: 2 },
  { title: 'Product of Array Except Self', difficulty: 'medium', topic: 'Arrays & Hashing', patterns: ['Prefix Product'], companies: ['Meta', 'Apple'], status: 'solved', confidence: 3, attempts: 2 },
  { title: 'Longest Consecutive Sequence', difficulty: 'medium', topic: 'Arrays & Hashing', patterns: ['Hash Set'], companies: ['Google', 'Meta'], status: 'attempted', confidence: 2, attempts: 1 },
  { title: 'Group Anagrams', difficulty: 'medium', topic: 'Arrays & Hashing', patterns: ['Hash Map', 'Counting'], companies: ['Amazon', 'Uber'], status: 'mastered', confidence: 5, attempts: 3 },
  { title: 'Valid Sudoku', difficulty: 'medium', topic: 'Arrays & Hashing', patterns: ['Hash Set', 'Matrix'], companies: ['Amazon'], status: 'not_started', confidence: 0, attempts: 0 },
  { title: 'Encode and Decode Strings', difficulty: 'medium', topic: 'Arrays & Hashing', patterns: ['String Parsing'], companies: ['Google'], status: 'not_started', confidence: 0, attempts: 0 },

  // ------------------------------------------------------------------ Two Pointers
  { title: '3Sum', difficulty: 'medium', topic: 'Two Pointers', patterns: ['Two Pointers', 'Sorting'], companies: ['Meta', 'Amazon'], status: 'solved', confidence: 3, attempts: 3 },
  { title: 'Container With Most Water', difficulty: 'medium', topic: 'Two Pointers', patterns: ['Two Pointers', 'Greedy'], companies: ['Amazon', 'Google'], status: 'solved', confidence: 4, attempts: 2 },
  { title: 'Trapping Rain Water', difficulty: 'hard', topic: 'Two Pointers', patterns: ['Two Pointers', 'Monotonic Stack'], companies: ['Google', 'Amazon'], status: 'attempted', confidence: 1, attempts: 2 },
  { title: 'Valid Palindrome', difficulty: 'easy', topic: 'Two Pointers', patterns: ['Two Pointers'], companies: ['Meta'], status: 'mastered', confidence: 5, attempts: 2 },
  { title: 'Two Sum II', difficulty: 'medium', topic: 'Two Pointers', patterns: ['Two Pointers', 'Binary Search'], companies: ['Amazon'], status: 'solved', confidence: 4, attempts: 1 },

  // --------------------------------------------------------------- Sliding Window
  { title: 'Longest Substring Without Repeating Characters', difficulty: 'medium', topic: 'Sliding Window', patterns: ['Sliding Window', 'Hash Set'], companies: ['Amazon', 'Meta', 'Bloomberg'], status: 'solved', confidence: 4, attempts: 3 },
  { title: 'Minimum Window Substring', difficulty: 'hard', topic: 'Sliding Window', patterns: ['Sliding Window', 'Hash Map'], companies: ['Meta', 'Google'], status: 'needs_revision', confidence: 1, attempts: 3 },
  { title: 'Longest Repeating Character Replacement', difficulty: 'medium', topic: 'Sliding Window', patterns: ['Sliding Window'], companies: ['Meta'], status: 'solved', confidence: 3, attempts: 2 },
  { title: 'Sliding Window Maximum', difficulty: 'hard', topic: 'Sliding Window', patterns: ['Monotonic Deque'], companies: ['Amazon', 'Google'], status: 'not_started', confidence: 0, attempts: 0 },
  { title: 'Permutation in String', difficulty: 'medium', topic: 'Sliding Window', patterns: ['Sliding Window', 'Counting'], companies: ['Microsoft'], status: 'attempted', confidence: 2, attempts: 1 },

  // -------------------------------------------------------------------- Stack
  { title: 'Valid Parentheses', difficulty: 'easy', topic: 'Stack', patterns: ['Stack'], companies: ['Amazon', 'Meta'], status: 'mastered', confidence: 5, attempts: 3 },
  { title: 'Min Stack', difficulty: 'medium', topic: 'Stack', patterns: ['Stack', 'Design'], companies: ['Amazon'], status: 'solved', confidence: 4, attempts: 1 },
  { title: 'Daily Temperatures', difficulty: 'medium', topic: 'Stack', patterns: ['Monotonic Stack'], companies: ['Amazon', 'Google'], status: 'solved', confidence: 3, attempts: 2 },
  { title: 'Largest Rectangle in Histogram', difficulty: 'hard', topic: 'Stack', patterns: ['Monotonic Stack'], companies: ['Google', 'Amazon'], status: 'needs_revision', confidence: 1, attempts: 2 },
  { title: 'Evaluate Reverse Polish Notation', difficulty: 'medium', topic: 'Stack', patterns: ['Stack'], companies: ['Amazon'], status: 'not_started', confidence: 0, attempts: 0 },
  { title: 'Car Fleet', difficulty: 'medium', topic: 'Stack', patterns: ['Monotonic Stack', 'Sorting'], companies: ['Google'], status: 'not_started', confidence: 0, attempts: 0 },

  // -------------------------------------------------------------- Binary Search
  { title: 'Binary Search', difficulty: 'easy', topic: 'Binary Search', patterns: ['Binary Search'], companies: ['Amazon'], status: 'mastered', confidence: 5, attempts: 3 },
  { title: 'Search in Rotated Sorted Array', difficulty: 'medium', topic: 'Binary Search', patterns: ['Binary Search'], companies: ['Amazon', 'Microsoft'], status: 'solved', confidence: 3, attempts: 2 },
  { title: 'Koko Eating Bananas', difficulty: 'medium', topic: 'Binary Search', patterns: ['Binary Search on Answer'], companies: ['Google'], status: 'solved', confidence: 4, attempts: 1 },
  { title: 'Median of Two Sorted Arrays', difficulty: 'hard', topic: 'Binary Search', patterns: ['Binary Search', 'Partition'], companies: ['Google', 'Amazon'], status: 'needs_revision', confidence: 1, attempts: 3 },
  { title: 'Find Minimum in Rotated Sorted Array', difficulty: 'medium', topic: 'Binary Search', patterns: ['Binary Search'], companies: ['Meta'], status: 'attempted', confidence: 2, attempts: 2 },

  // ------------------------------------------------------------ Linked List
  { title: 'Reverse Linked List', difficulty: 'easy', topic: 'Linked List', patterns: ['Pointer Manipulation'], companies: ['Amazon', 'Microsoft'], status: 'mastered', confidence: 5, attempts: 4 },
  { title: 'Merge Two Sorted Lists', difficulty: 'easy', topic: 'Linked List', patterns: ['Two Pointers'], companies: ['Amazon'], status: 'mastered', confidence: 5, attempts: 2 },
  { title: 'LRU Cache', difficulty: 'medium', topic: 'Linked List', patterns: ['Hash Map', 'Doubly Linked List', 'Design'], companies: ['Amazon', 'Google', 'Meta'], status: 'solved', confidence: 3, attempts: 3 },
  { title: 'Reorder List', difficulty: 'medium', topic: 'Linked List', patterns: ['Two Pointers', 'Pointer Manipulation'], companies: ['Amazon'], status: 'attempted', confidence: 2, attempts: 1 },
  { title: 'Remove Nth Node From End of List', difficulty: 'medium', topic: 'Linked List', patterns: ['Two Pointers'], companies: ['Meta'], status: 'solved', confidence: 4, attempts: 1 },
  { title: 'Merge K Sorted Lists', difficulty: 'hard', topic: 'Linked List', patterns: ['Heap', 'Divide and Conquer'], companies: ['Amazon', 'Google'], status: 'not_started', confidence: 0, attempts: 0 },

  // ---------------------------------------------------------------------- Trees
  { title: 'Invert Binary Tree', difficulty: 'easy', topic: 'Trees', patterns: ['DFS', 'Recursion'], companies: ['Google'], status: 'mastered', confidence: 5, attempts: 2 },
  { title: 'Binary Tree Level Order Traversal', difficulty: 'medium', topic: 'Trees', patterns: ['BFS'], companies: ['Amazon', 'Meta'], status: 'solved', confidence: 4, attempts: 2 },
  { title: 'Validate Binary Search Tree', difficulty: 'medium', topic: 'Trees', patterns: ['DFS', 'BST Properties'], companies: ['Amazon', 'Bloomberg'], status: 'solved', confidence: 3, attempts: 2 },
  { title: 'Kth Smallest Element in a BST', difficulty: 'medium', topic: 'Trees', patterns: ['In-order Traversal'], companies: ['Google'], status: 'attempted', confidence: 2, attempts: 1 },
  { title: 'Lowest Common Ancestor of a BST', difficulty: 'medium', topic: 'Trees', patterns: ['DFS', 'BST Properties'], companies: ['Amazon', 'Meta'], status: 'solved', confidence: 4, attempts: 1 },
  { title: 'Serialize and Deserialize Binary Tree', difficulty: 'hard', topic: 'Trees', patterns: ['DFS', 'Design'], companies: ['Google', 'Meta'], status: 'needs_revision', confidence: 1, attempts: 2 },
  { title: 'Binary Tree Maximum Path Sum', difficulty: 'hard', topic: 'Trees', patterns: ['DFS', 'Recursion'], companies: ['Amazon', 'Google'], status: 'not_started', confidence: 0, attempts: 0 },

  // --------------------------------------------------------------------- Graphs
  { title: 'Number of Islands', difficulty: 'medium', topic: 'Graphs', patterns: ['DFS', 'BFS', 'Union Find'], companies: ['Amazon', 'Google', 'Meta'], status: 'attempted', confidence: 3, attempts: 2 },
  { title: 'Clone Graph', difficulty: 'medium', topic: 'Graphs', patterns: ['DFS', 'Hash Map'], companies: ['Meta', 'Google'], status: 'solved', confidence: 3, attempts: 2 },
  { title: 'Course Schedule', difficulty: 'medium', topic: 'Graphs', patterns: ['Topological Sort', 'Cycle Detection'], companies: ['Amazon', 'Google'], status: 'needs_revision', confidence: 1, attempts: 3 },
  { title: 'Pacific Atlantic Water Flow', difficulty: 'medium', topic: 'Graphs', patterns: ['DFS', 'Matrix'], companies: ['Amazon', 'Google'], status: 'attempted', confidence: 2, attempts: 2 },
  { title: 'Word Ladder', difficulty: 'hard', topic: 'Graphs', patterns: ['BFS', 'Shortest Path'], companies: ['Amazon', 'Meta'], status: 'not_started', confidence: 0, attempts: 0 },
  { title: 'Alien Dictionary', difficulty: 'hard', topic: 'Graphs', patterns: ['Topological Sort'], companies: ['Meta', 'Airbnb'], status: 'not_started', confidence: 0, attempts: 0 },
  { title: 'Network Delay Time', difficulty: 'medium', topic: 'Graphs', patterns: ["Dijkstra's Algorithm", 'Heap'], companies: ['Amazon'], status: 'attempted', confidence: 2, attempts: 1 },

  // ----------------------------------------------------------------------- Heap
  { title: 'Kth Largest Element in an Array', difficulty: 'medium', topic: 'Heap', patterns: ['Quickselect', 'Heap'], companies: ['Amazon', 'Meta'], status: 'solved', confidence: 4, attempts: 2 },
  { title: 'Task Scheduler', difficulty: 'medium', topic: 'Heap', patterns: ['Greedy', 'Counting'], companies: ['Amazon', 'Meta'], status: 'attempted', confidence: 2, attempts: 2 },
  { title: 'Find Median from Data Stream', difficulty: 'hard', topic: 'Heap', patterns: ['Two Heaps', 'Design'], companies: ['Amazon', 'Google'], status: 'not_started', confidence: 0, attempts: 0 },

  // --------------------------------------------------------------- Backtracking
  { title: 'Subsets', difficulty: 'medium', topic: 'Backtracking', patterns: ['Backtracking'], companies: ['Amazon', 'Meta'], status: 'solved', confidence: 4, attempts: 2 },
  { title: 'Combination Sum', difficulty: 'medium', topic: 'Backtracking', patterns: ['Backtracking'], companies: ['Amazon'], status: 'solved', confidence: 3, attempts: 2 },
  { title: 'Permutations', difficulty: 'medium', topic: 'Backtracking', patterns: ['Backtracking'], companies: ['Amazon', 'Meta'], status: 'solved', confidence: 4, attempts: 1 },
  { title: 'Word Search II', difficulty: 'hard', topic: 'Backtracking', patterns: ['Backtracking', 'Trie'], companies: ['Amazon', 'Google'], status: 'not_started', confidence: 0, attempts: 0 },
  { title: 'N-Queens', difficulty: 'hard', topic: 'Backtracking', patterns: ['Backtracking', 'Matrix'], companies: ['Google'], status: 'not_started', confidence: 0, attempts: 0 },

  // --------------------------------------------------------- Dynamic Programming
  { title: 'Climbing Stairs', difficulty: 'easy', topic: 'Dynamic Programming', patterns: ['1D DP'], companies: ['Amazon'], status: 'mastered', confidence: 5, attempts: 2 },
  { title: 'House Robber', difficulty: 'medium', topic: 'Dynamic Programming', patterns: ['1D DP'], companies: ['Amazon', 'Google'], status: 'solved', confidence: 3, attempts: 2 },
  { title: 'Longest Increasing Subsequence', difficulty: 'medium', topic: 'Dynamic Programming', patterns: ['1D DP', 'Binary Search'], companies: ['Amazon', 'Meta'], status: 'needs_revision', confidence: 1, attempts: 3 },
  { title: 'Coin Change', difficulty: 'medium', topic: 'Dynamic Programming', patterns: ['Unbounded Knapsack'], companies: ['Amazon', 'Google'], status: 'solved', confidence: 3, attempts: 3 },
  { title: 'Longest Common Subsequence', difficulty: 'medium', topic: 'Dynamic Programming', patterns: ['2D DP'], companies: ['Amazon', 'Google'], status: 'needs_revision', confidence: 2, attempts: 2 },
  { title: 'Edit Distance', difficulty: 'hard', topic: 'Dynamic Programming', patterns: ['2D DP', 'String DP'], companies: ['Amazon', 'Google'], status: 'attempted', confidence: 1, attempts: 2 },
  { title: 'Burst Balloons', difficulty: 'hard', topic: 'Dynamic Programming', patterns: ['Interval DP'], companies: ['Google'], status: 'not_started', confidence: 0, attempts: 0 },
  { title: 'Best Time to Buy and Sell Stock', difficulty: 'easy', topic: 'Greedy', patterns: ['Greedy', 'Kadane'], companies: ['Amazon', 'Meta'], status: 'mastered', confidence: 5, attempts: 2 },
  { title: 'Merge Intervals', difficulty: 'medium', topic: 'Intervals', patterns: ['Sorting', 'Intervals'], companies: ['Amazon', 'Google', 'Meta'], status: 'attempted', confidence: 3, attempts: 2 },
  { title: 'Insert Interval', difficulty: 'medium', topic: 'Intervals', patterns: ['Intervals', 'Sorting'], companies: ['Amazon', 'Google'], status: 'solved', confidence: 3, attempts: 1 },
  { title: 'Non-overlapping Intervals', difficulty: 'medium', topic: 'Intervals', patterns: ['Intervals', 'Greedy'], companies: ['Meta'], status: 'not_started', confidence: 0, attempts: 0 },
  { title: 'Meeting Rooms II', difficulty: 'medium', topic: 'Intervals', patterns: ['Intervals', 'Heap'], companies: ['Amazon', 'Meta'], status: 'attempted', confidence: 2, attempts: 2 },
];

// ---------------------------------------------------------------- LLD curriculum

export interface TopicSeed {
  title: string;
  slug: string;
  description: string;
  keyConcepts: string[];
  difficulty: Difficulty;
  estimatedMinutes: number;
  status: TopicStatus;
  confidence: number;
}

export const LLD_FUNDAMENTALS: TopicSeed[] = [
  { title: 'Object-Oriented Programming', slug: 'oop', description: 'Encapsulation, inheritance, polymorphism and abstraction as the four pillars of class design.', keyConcepts: ['Encapsulation', 'Inheritance', 'Polymorphism', 'Abstraction'], difficulty: 'easy', estimatedMinutes: 45, status: 'completed', confidence: 4 },
  { title: 'SOLID Principles', slug: 'solid', description: 'The five principles that keep a class hierarchy maintainable as requirements change.', keyConcepts: ['SRP', 'OCP', 'LSP', 'ISP', 'DIP'], difficulty: 'medium', estimatedMinutes: 60, status: 'learning', confidence: 3 },
  { title: 'Composition vs Inheritance', slug: 'composition-vs-inheritance', description: 'When to favour has-a over is-a, and why deep hierarchies become brittle.', keyConcepts: ['Favour composition', 'Fragile base class', 'Delegation'], difficulty: 'medium', estimatedMinutes: 45, status: 'completed', confidence: 4 },
  { title: 'Abstraction', slug: 'abstraction', description: 'Modelling only the behaviour a client needs, and hiding the rest behind a stable contract.', keyConcepts: ['Data hiding', 'Leaky abstractions', 'Modelling'], difficulty: 'medium', estimatedMinutes: 40, status: 'completed', confidence: 3 },
  { title: 'Interfaces', slug: 'interfaces', description: 'Programming to a contract so implementations can be swapped without touching callers.', keyConcepts: ['Contract', 'Polymorphic dispatch', 'Mocking'], difficulty: 'easy', estimatedMinutes: 35, status: 'mastered', confidence: 5 },
  { title: 'Dependency Inversion', slug: 'dependency-inversion', description: 'Depending on abstractions rather than concretions, and where to draw the boundary.', keyConcepts: ['DIP', 'IoC', 'Constructor injection'], difficulty: 'hard', estimatedMinutes: 55, status: 'learning', confidence: 2 },
];

export const LLD_PATTERNS: TopicSeed[] = [
  { title: 'Factory Pattern', slug: 'factory', description: 'Centralising object creation so callers never bind to a concrete class.', keyConcepts: ['Simple factory', 'Factory method', 'Abstract factory'], difficulty: 'medium', estimatedMinutes: 50, status: 'completed', confidence: 4 },
  { title: 'Strategy Pattern', slug: 'strategy', description: 'Swapping an algorithm at runtime by encapsulating each one behind a common interface.', keyConcepts: ['Composition', 'Runtime selection', 'Open/Closed'], difficulty: 'medium', estimatedMinutes: 50, status: 'learning', confidence: 3 },
  { title: 'Observer Pattern', slug: 'observer', description: 'One-to-many notification so publishers and subscribers stay decoupled.', keyConcepts: ['Publish/subscribe', 'Loose coupling', 'Push vs pull'], difficulty: 'medium', estimatedMinutes: 50, status: 'completed', confidence: 4 },
  { title: 'Builder Pattern', slug: 'builder', description: 'Constructing complex objects step by step without exposing a telescoping constructor.', keyConcepts: ['Fluent interface', 'Immutability', 'Step-wise construction'], difficulty: 'easy', estimatedMinutes: 40, status: 'completed', confidence: 4 },
  { title: 'Adapter Pattern', slug: 'adapter', description: 'Bridging an incompatible interface so legacy and new code can cooperate.', keyConcepts: ['Wrapper', 'Interface translation'], difficulty: 'easy', estimatedMinutes: 40, status: 'completed', confidence: 3 },
  { title: 'Decorator Pattern', slug: 'decorator', description: 'Adding behaviour by wrapping an object, instead of subclassing every combination.', keyConcepts: ['Wrapper chain', 'Open/Closed', 'Runtime composition'], difficulty: 'medium', estimatedMinutes: 50, status: 'learning', confidence: 3 },
  { title: 'Singleton Pattern', slug: 'singleton', description: 'Guaranteeing a single shared instance — and the reasons to avoid it.', keyConcepts: ['Global state', 'Thread safety', 'Testability tradeoffs'], difficulty: 'easy', estimatedMinutes: 35, status: 'mastered', confidence: 5 },
  { title: 'Command Pattern', slug: 'command', description: 'Turning a request into an object so it can be queued, undone or logged.', keyConcepts: ['Encapsulated request', 'Undo/redo', 'Queueing'], difficulty: 'medium', estimatedMinutes: 50, status: 'not_started', confidence: 0 },
];

export const LLD_EXERCISES: TopicSeed[] = [
  { title: 'Parking Lot', slug: 'parking-lot', description: 'Model a multi-level lot with vehicle sizes, spot allocation and ticket billing.', keyConcepts: ['Entities', 'Strategy for pricing', 'Concurrency'], difficulty: 'medium', estimatedMinutes: 75, status: 'completed', confidence: 4 },
  { title: 'Elevator System', slug: 'elevator-system', description: 'Schedule requests across multiple cars with direction-aware dispatch.', keyConcepts: ['State machine', 'Scheduling', 'Concurrency'], difficulty: 'hard', estimatedMinutes: 90, status: 'learning', confidence: 2 },
  { title: 'Vending Machine', slug: 'vending-machine', description: 'Model states, inventory, payment and change dispensing.', keyConcepts: ['State pattern', 'Inventory', 'Transactions'], difficulty: 'medium', estimatedMinutes: 70, status: 'completed', confidence: 4 },
  { title: 'Tic Tac Toe', slug: 'tic-tac-toe', description: 'Game loop, board abstraction and a winning-condition strategy.', keyConcepts: ['Board model', 'Win detection', 'Players'], difficulty: 'easy', estimatedMinutes: 50, status: 'mastered', confidence: 5 },
  { title: 'Chess', slug: 'chess', description: 'Piece movement rules, board state and move validation.', keyConcepts: ['Polymorphic pieces', 'Move validation', 'Board state'], difficulty: 'hard', estimatedMinutes: 110, status: 'not_started', confidence: 0 },
  { title: 'Splitwise', slug: 'splitwise', description: 'Track shared expenses, split strategies and debt simplification.', keyConcepts: ['Split strategies', 'Ledger', 'Graph simplification'], difficulty: 'medium', estimatedMinutes: 80, status: 'learning', confidence: 3 },
  { title: 'Library Management', slug: 'library-management', description: 'Cataloguing, lending, returns, fines and reservations.', keyConcepts: ['Entities', 'Lending rules', 'Fines'], difficulty: 'medium', estimatedMinutes: 70, status: 'completed', confidence: 3 },
  { title: 'Car Rental', slug: 'car-rental', description: 'Fleet inventory, reservations, pricing and returns across branches.', keyConcepts: ['Inventory', 'Reservations', 'Pricing strategy'], difficulty: 'medium', estimatedMinutes: 75, status: 'not_started', confidence: 0 },
  { title: 'Food Delivery', slug: 'food-delivery', description: 'Restaurants, menus, carts, orders and courier assignment.', keyConcepts: ['Order lifecycle', 'Matching', 'State machine'], difficulty: 'hard', estimatedMinutes: 95, status: 'not_started', confidence: 0 },
  { title: 'Movie Ticket Booking', slug: 'movie-ticket-booking', description: 'Showtimes, seat maps, holds and payment confirmation.', keyConcepts: ['Seat locking', 'Bookings', 'Concurrency'], difficulty: 'medium', estimatedMinutes: 80, status: 'needs_revision', confidence: 2 },
];

// ---------------------------------------------------------------- HLD curriculum

export const HLD_FUNDAMENTALS: TopicSeed[] = [
  { title: 'Scalability', slug: 'scalability', description: 'What breaks first as load grows, and the standard levers for fixing it.', keyConcepts: ['Vertical vs horizontal', 'Statelessness', 'Bottlenecks'], difficulty: 'easy', estimatedMinutes: 50, status: 'completed', confidence: 4 },
  { title: 'Latency vs Throughput', slug: 'latency-vs-throughput', description: 'Why optimising one can hurt the other, and how to reason about the tradeoff.', keyConcepts: ['p50/p99', 'Queueing', 'Little\u2019s Law'], difficulty: 'medium', estimatedMinutes: 45, status: 'completed', confidence: 4 },
  { title: 'Horizontal vs Vertical Scaling', slug: 'horizontal-vs-vertical-scaling', description: 'Cost, ceiling and operational complexity of each scaling axis.', keyConcepts: ['Scale up/out', 'Cost curve', 'Ceilings'], difficulty: 'easy', estimatedMinutes: 40, status: 'completed', confidence: 4 },
  { title: 'Load Balancing', slug: 'load-balancing', description: 'Distribution algorithms, health checks and session affinity.', keyConcepts: ['Round robin', 'Least connections', 'Health checks', 'Sticky sessions'], difficulty: 'medium', estimatedMinutes: 55, status: 'completed', confidence: 3 },
  { title: 'Reverse Proxy', slug: 'reverse-proxy', description: 'TLS termination, routing, compression and request coalescing.', keyConcepts: ['TLS termination', 'Routing', 'Timeouts'], difficulty: 'easy', estimatedMinutes: 40, status: 'completed', confidence: 4 },
  { title: 'Caching', slug: 'caching', description: 'Cache layers, invalidation strategies and what to do about stampedes.', keyConcepts: ['Cache-aside', 'Write-through', 'TTL', 'Invalidation', 'Stampede'], difficulty: 'medium', estimatedMinutes: 70, status: 'learning', confidence: 3 },
  { title: 'CDN', slug: 'cdn', description: 'Edge caching, cache-control headers and origin shielding.', keyConcepts: ['Edge PoPs', 'Cache-Control', 'Purge', 'Origin shield'], difficulty: 'medium', estimatedMinutes: 50, status: 'completed', confidence: 3 },
  { title: 'Database Indexing', slug: 'database-indexing', description: 'B-tree vs hash indexes, covering indexes and the cost of write amplification.', keyConcepts: ['B-tree', 'Composite index', 'Covering index', 'Selectivity'], difficulty: 'medium', estimatedMinutes: 60, status: 'learning', confidence: 3 },
  { title: 'Replication', slug: 'replication', description: 'Leader-follower and multi-leader topologies, lag and failover.', keyConcepts: ['Leader/follower', 'Replication lag', 'Failover', 'Read replicas'], difficulty: 'medium', estimatedMinutes: 65, status: 'learning', confidence: 2 },
  { title: 'Sharding', slug: 'sharding', description: 'Choosing a shard key and living with hot partitions and resharding.', keyConcepts: ['Shard key', 'Hot partition', 'Resharding', 'Directory'], difficulty: 'hard', estimatedMinutes: 75, status: 'not_started', confidence: 0 },
  { title: 'SQL vs NoSQL', slug: 'sql-vs-nosql', description: 'Access patterns first, then consistency and scaling requirements.', keyConcepts: ['Access patterns', 'Joins', 'Denormalisation', 'Scaling model'], difficulty: 'medium', estimatedMinutes: 55, status: 'completed', confidence: 4 },
  { title: 'CAP Theorem', slug: 'cap-theorem', description: 'Consistency, availability and partition tolerance — and what you actually choose.', keyConcepts: ['Consistency', 'Availability', 'Partitions', 'PACELC'], difficulty: 'medium', estimatedMinutes: 50, status: 'completed', confidence: 3 },
  { title: 'Message Queues', slug: 'message-queues', description: 'Decoupling producers and consumers, ordering, retries and dead-letter queues.', keyConcepts: ['Decoupling', 'At-least-once', 'DLQ', 'Backpressure'], difficulty: 'medium', estimatedMinutes: 65, status: 'learning', confidence: 3 },
  { title: 'Event-driven Architecture', slug: 'event-driven-architecture', description: 'Events as the source of truth, and the complexity that comes with them.', keyConcepts: ['Events vs commands', 'Event sourcing', 'Choreography'], difficulty: 'hard', estimatedMinutes: 70, status: 'not_started', confidence: 0 },
  { title: 'Rate Limiting', slug: 'rate-limiting', description: 'Token bucket, sliding window and distributed enforcement.', keyConcepts: ['Token bucket', 'Sliding window', 'Distributed counters'], difficulty: 'medium', estimatedMinutes: 60, status: 'completed', confidence: 3 },
  { title: 'Consistent Hashing', slug: 'consistent-hashing', description: 'Distributing keys so adding or removing a node moves minimal data.', keyConcepts: ['Hash ring', 'Virtual nodes', 'Rebalancing'], difficulty: 'hard', estimatedMinutes: 65, status: 'needs_revision', confidence: 1 },
  { title: 'Distributed Locks', slug: 'distributed-locks', description: 'Mutual exclusion across nodes, leases and the failure modes involved.', keyConcepts: ['Leases', 'Fencing tokens', 'Redlock caveats'], difficulty: 'hard', estimatedMinutes: 65, status: 'not_started', confidence: 0 },
  { title: 'Idempotency', slug: 'idempotency', description: 'Making retries safe with idempotency keys and deduplication stores.', keyConcepts: ['Idempotency key', 'Dedup store', 'Exactly-once effects'], difficulty: 'medium', estimatedMinutes: 50, status: 'learning', confidence: 3 },
];

export const HLD_SYSTEMS: TopicSeed[] = [
  { title: 'URL Shortener', slug: 'url-shortener', description: 'Key generation, redirects at scale and read-heavy caching.', keyConcepts: ['Key generation', 'Redirect latency', 'Caching'], difficulty: 'easy', estimatedMinutes: 60, status: 'completed', confidence: 4 },
  { title: 'Rate Limiter', slug: 'rate-limiter', description: 'A shared rate-limiting service with per-tenant policies.', keyConcepts: ['Algorithms', 'Distributed state', 'Policy config'], difficulty: 'medium', estimatedMinutes: 70, status: 'completed', confidence: 3 },
  { title: 'Notification Service', slug: 'notification-service', description: 'Fan-out across channels with retries, preferences and deduplication.', keyConcepts: ['Fan-out', 'Retries', 'Preferences', 'Dedup'], difficulty: 'medium', estimatedMinutes: 80, status: 'learning', confidence: 3 },
  { title: 'Chat System', slug: 'chat-system', description: 'Real-time delivery, presence, ordering and offline sync.', keyConcepts: ['WebSockets', 'Presence', 'Ordering', 'Offline queue'], difficulty: 'hard', estimatedMinutes: 95, status: 'learning', confidence: 2 },
  { title: 'News Feed', slug: 'news-feed', description: 'Fan-out on write vs read, ranking and timeline caching.', keyConcepts: ['Fan-out strategies', 'Ranking', 'Timeline cache'], difficulty: 'hard', estimatedMinutes: 90, status: 'not_started', confidence: 0 },
  { title: 'File Storage', slug: 'file-storage', description: 'Chunked uploads, deduplication, metadata and sharing.', keyConcepts: ['Chunking', 'Dedup', 'Metadata store', 'Sharing'], difficulty: 'medium', estimatedMinutes: 85, status: 'not_started', confidence: 0 },
  { title: 'Search Autocomplete', slug: 'search-autocomplete', description: 'Trie-based suggestions with ranking and freshness.', keyConcepts: ['Trie', 'Ranking', 'Prefix cache'], difficulty: 'medium', estimatedMinutes: 75, status: 'not_started', confidence: 0 },
  { title: 'Payment System', slug: 'payment-system', description: 'Ledgers, idempotency, reconciliation and exactly-once effects.', keyConcepts: ['Double-entry ledger', 'Idempotency', 'Reconciliation'], difficulty: 'hard', estimatedMinutes: 100, status: 'not_started', confidence: 0 },
  { title: 'Ticket Booking', slug: 'ticket-booking', description: 'Inventory holds, contention and payment integration.', keyConcepts: ['Seat holding', 'Contention', 'Saga'], difficulty: 'hard', estimatedMinutes: 95, status: 'not_started', confidence: 0 },
  { title: 'Food Delivery', slug: 'hld-food-delivery', description: 'Order lifecycle, courier matching and geo-indexing.', keyConcepts: ['Geo index', 'Matching', 'State machine'], difficulty: 'hard', estimatedMinutes: 95, status: 'not_started', confidence: 0 },
  { title: 'Ride Sharing', slug: 'ride-sharing', description: 'Driver matching, pricing surges and location streaming.', keyConcepts: ['Geo sharding', 'Matching', 'Surge pricing'], difficulty: 'hard', estimatedMinutes: 100, status: 'not_started', confidence: 0 },
];

// ----------------------------------------------------------------------- helpers

export const LLD_SEED: { seed: TopicSeed; category: LLDCategory }[] = [
  ...LLD_FUNDAMENTALS.map((seed) => ({ seed, category: 'fundamentals' as const })),
  ...LLD_PATTERNS.map((seed) => ({ seed, category: 'design_patterns' as const })),
  ...LLD_EXERCISES.map((seed) => ({ seed, category: 'design_exercises' as const })),
];

export const HLD_SEED: { seed: TopicSeed; category: HLDCategory }[] = [
  ...HLD_FUNDAMENTALS.map((seed) => ({ seed, category: 'fundamentals' as const })),
  ...HLD_SYSTEMS.map((seed) => ({ seed, category: 'system_design' as const })),
];

/** Display names for catalog categories, re-exported from `lib/constants`. */
export { HLD_CATEGORY_LABELS, LLD_CATEGORY_LABELS } from '@/lib/constants';
