/**
 * Mock AI tutor.
 *
 * Mirrors the real tutor's pedagogy, which is the important part: hints get progressively
 * stronger and the full solution is never dumped unless the user explicitly asks for it.
 * Responses are composed from the context the server would have sent, so the panel behaves
 * identically against the real provider.
 */

import type { AIAction, AIContextType } from '@/types/common';
import type { AIChatRequest } from '@/types/ai';

export interface ResponderContext {
  /** Display name of the entity in focus (problem title, topic title). */
  label?: string | null;
  topic?: string | null;
  patterns?: string[];
  difficulty?: string | null;
  /** How many hint-style replies have already been given for this thread. */
  hintLevel: number;
}

const ACTION_LABEL: Record<string, string> = {
  give_hint: 'Hint',
  explain_concept: 'Concept',
  explain_code: 'Code walkthrough',
  find_bug: 'Bug review',
  complexity: 'Complexity',
  alternative_approach: 'Alternative approach',
  interview_me: 'Interview practice',
  general: 'Tutor',
};

export function actionLabel(action: string | undefined): string {
  return ACTION_LABEL[action ?? 'general'] ?? 'Tutor';
}

function hintFor(context: ResponderContext): string {
  const { label, topic, patterns, hintLevel } = context;
  const pattern = patterns?.[0] ?? topic ?? 'the core pattern';
  const subject = label ? `**${label}**` : 'this problem';

  if (hintLevel === 0) {
    return `Let's keep it to one nudge for now.\n\nThink about ${subject} as a **${pattern}** problem. Ask yourself what invariant you could maintain while scanning the input a single time.\n\nWhat are you currently tracking as you iterate?`;
  }

  if (hintLevel === 1) {
    return `Stronger hint.\n\nThe invariant you want is one that lets you answer "have I seen the complement of this element before?" in constant time. A **hash map** from value to something useful is the usual vehicle for that.\n\nWhat would you store as the *value* — the index, a count, or something else?`;
  }

  if (hintLevel === 2) {
    return `Close to it now.\n\nWalk the input once. At each element, compute what earlier state would make the current position a valid answer, look that up, then record the current state.\n\nWrite that as two lines of pseudocode before touching the editor — the ordering of the lookup and the record matters.`;
  }

  return `You're at the point where the shape is clear.\n\n- One pass, no nested loop.\n- A hash map for O(1) lookups of the complementary state.\n- Update the running answer from the lookup, *then* record the new state.\n\nIf you'd like the full reference implementation, ask me directly — I'll hold off otherwise so the recall work stays yours.`;
}

function conceptFor(context: ResponderContext): string {
  const { label, topic, patterns } = context;
  const pattern = patterns?.[0] ?? topic ?? 'The pattern';
  return `**${pattern}** in context${label ? ` — ${label}` : ''}\n\n**Why it exists.** ${pattern} turns a problem that looks like it needs nested iteration into a single pass, by carrying the state you would otherwise recompute.\n\n**When to reach for it**\n- The brute force re-scans the same region repeatedly.\n- You can express "have I seen this before?" as a constant-time lookup.\n- The answer is derivable from a running aggregate rather than the whole input.\n\n**Watch out for**\n- Boundary conditions on the very first and last elements.\n- Duplicate keys that need counting rather than overwriting.\n\nWant me to connect this to a concrete problem you've attempted?`;
}

function codeFor(context: ResponderContext, selectedCode?: string | null): string {
  if (!selectedCode?.trim()) {
    return `I don't see a code selection. Highlight the part of your solution you want me to walk through in the editor, then pick **Explain Selected Code** again.\n\nIf you'd rather review the whole snippet, say so and I'll read it in full.`;
  }

  const lines = selectedCode.trim().split('\n').length;
  return `Walking through the ${lines}-line selection you highlighted:\n\n1. **Setup** — the state you initialise here is what the rest of the loop depends on, so any mistake in this region compounds.\n2. **Loop body** — the ordering of the lookup and the update is the crux. Doing the update first silently breaks the invariant.\n3. **Return** — confirm this is the value the problem statement asks for, not an intermediate accumulator.\n\nQuestion to check your own understanding: if the loop ran over two elements instead of one, would this selection still produce the right answer? ${
    context.patterns?.[0] ? `That's the test of whether the **${context.patterns[0]}** invariant is correctly held.` : ''
  }`;
}

function bugFor(context: ResponderContext, selectedCode?: string | null): string {
  const snippet = selectedCode?.trim();
  const observations = [
    '- **Empty input.** Several paths assume at least one element. Add an early return.',
    '- **Off-by-one at the tail.** The last element is often skipped when the loop condition uses the wrong comparison.',
    '- **Shared mutable default.** If a container is created outside the loop but mutated inside, state leaks between iterations.',
  ];

  return `Let me review${snippet ? ' the highlighted region' : ' this'}.\n\nI can't execute code, so this is a reasoning review — check each of these against your version:\n\n${observations.join('\n')}\n\n${
    context.patterns?.[0] ? `Given this is a **${context.patterns[0]}** problem, I'd also check that the invariant is restored before every lookup, not after.\n\n` : ''
  }Tell me which of these you've already ruled out and I'll dig further.`;
}

function complexityFor(context: ResponderContext, selectedCode?: string | null): string {
  const hasNested = (selectedCode ?? '').split('\n').filter((line) => /for |while /.test(line)).length > 1;
  return `**Reading the complexity from the structure**\n\n- The outer loop touches each input element once → that's your $n$ term.\n- ${
    hasNested
      ? 'There is a second loop visible, but confirm whether it runs a fixed number of iterations or scales with $n$. If it depends on $n$, you have $O(n^2)$.'
      : 'There is no nested iteration, and every lookup is constant time, so the dominant term is linear.'
  }\n\n**Time:** ${
    hasNested ? 'likely $O(n^2)$ — show me the bounds of the inner loop and I will confirm' : '$O(n)$'
  }\n**Space:** the auxiliary structure grows with distinct elements, so $O(n)$ in the worst case and $O(1)$ when inputs are bounded.\n\n${
    context.patterns?.[0] === 'Prefix Sum' || context.patterns?.[0] === 'Sliding Window'
      ? `The ${context.patterns[0]} formulation is what lets the inner scan collapse into a lookup — that is exactly where the $n^2$ becomes $n$.`
      : ''
  }`;
}

function alternativeFor(context: ResponderContext): string {
  const pattern = context.patterns?.[0] ?? context.topic ?? 'the pattern';
  return `**Alternative angles on ${context.label ?? 'this problem'}**\n\n1. **Sort first.** $O(n \\log n)$ but often turns the problem into a linear two-pointer sweep, and it removes the need for a hash structure when the answer doesn't depend on original order.\n2. **Different data structure.** Where you use a map, a heap or a balanced tree may replace a full scan with $O(\\log n)$ per element — worthwhile when you also need order.\n3. **Divide and conquer.** Split, solve each half, then combine. Worth exploring if the input supports associative merging.\n\nTrade-off summary: the **${pattern}** approach you have is $O(n)$ time and $O(n)$ space. The sorting variant trades a log factor for $O(1)$ auxiliary space. Which of those two constraints actually matters here?`;
}

function interviewFor(context: ResponderContext): string {
  const pattern = context.patterns?.[0] ?? context.topic ?? 'this topic';
  return `Let's run a short interview on ${context.label ? `**${context.label}**` : `**${pattern}**`}. I'll ask one question at a time.\n\n**Question 1.** State the problem in your own words in two sentences, including the input constraints. Constraints are where most candidates lose points.\n\n**Question 2.** What is your brute-force approach and its complexity? Say it out loud before optimising — interviewers score the reasoning, not just the final answer.\n\n**Question 3.** Which invariant does your optimised solution maintain, and what breaks if you evaluate it before versus after updating state?\n\nAnswer these in order and I'll follow up with the harder probes on edge cases, scaling and trade-offs.`;
}

function codeActionFor(context: ResponderContext, action: AIAction): string {
  switch (action) {
    case 'review_design':
      return `**Design review${context.label ? ` — ${context.label}` : ''}**\n\nI look for four things: single responsibility per class, dependencies pointing at abstractions, extension without modification, and no leaked implementation detail.\n\nAgainst what you've written, check:\n- Does any class have more than one reason to change?\n- Are concrete types referenced in signatures where an interface would do?\n- Is there a conditional ladder that a new variant would have to be added to?\n\nTell me which classes you want scrutinised and paste them, or highlight the region in the editor.`;
    case 'solid_check':
      return `**SOLID scan**\n\n- **S**ingle responsibility — does each class have exactly one reason to change? Look for methods that don't touch the same fields as the rest.\n- **O**pen/closed — could you add a new variant without editing existing branches? If not, that's the seam to extract.\n- **L**iskov — does every subtype honour the parent's contract, or does it throw on a case the parent supports?\n- **I**nterface segregation — is any implementer forced to stub methods it doesn't need?\n- **D**ependency inversion — do high-level modules depend on abstractions only?\n\nName the class you're least sure about and I'll dig into it.`;
    case 'missing_classes':
      return `**Entities that are commonly missing**\n\n- **Money / Duration / Range value objects** — primitives leak units and invite bugs.\n- **Repository** — isolates storage from domain logic, so persistence can change independently.\n- **Factory or Builder** — if construction takes more than three arguments, it belongs in one.\n- **Policy / Strategy** — anything described as "it depends on the type" is a strategy seam.\n- **State machine** — lifecycles (an order, a booking, a session) deserve an explicit state object rather than booleans.\n\nDescribe the lifecycle in your design and I'll point at which of these is genuinely absent versus over-engineering.`;
    case 'review_architecture':
      return `**Architecture review framework**\n\nWalk it in this order and the weak point shows itself:\n\n1. **Read path** — what serves the 95% case, and is it cached at the right layer?\n2. **Write path** — where is the single write bottleneck?\n3. **State** — what is stored, where does it live, and what is the source of truth?\n4. **Failure** — what happens when each box disappears?\n\nTell me your read:write ratio and I'll focus the review on the half that will actually break first.`;
    case 'scaling_bottlenecks':
      return `**Where this breaks first, in order**\n\n1. **Database writes** — a single primary saturates well before reads do. Look at write amplification per request.\n2. **Unbounded fan-out** — one write triggering thousands of downstream effects will stall under load. Queue it.\n3. **Hot partition** — a shard key with a skewed access pattern concentrates traffic on one node.\n4. **Shared mutable state** — any global counter or lock becomes a serialisation point.\n\nWhich of these four is present in your design? Name it and I'll go deeper on mitigation.`;
    case 'database_choice':
      return `**Database choice, decided by access pattern**\n\n- **Strong relational integrity, joins, moderate scale** → PostgreSQL.\n- **Massive write throughput, key-based reads** → wide-column (Cassandra) or DynamoDB.\n- **Full-text / relevance ranking** → a search engine alongside the primary store.\n- **Ordered time-series** → a TSDB, or Postgres partitioned by time.\n\nState your top two access patterns with approximate rates and I'll give a concrete recommendation rather than a menu.`;
    case 'api_design_review':
      return `**API design checklist**\n\n- **Resource shape** — nouns in the path, verbs in the method. Use \`/users/{id}/sessions\` rather than \`/getUserSessions\`.\n- **Idempotency** — every unsafe endpoint that a client might retry needs an idempotency key.\n- **Pagination** — cursor-based for anything that grows; offsets break under concurrent writes.\n- **Errors** — one consistent envelope with a stable machine-readable code.\n- **Versioning** — decided up front, even if you never bump it.\n\nPaste your endpoint list and I'll flag which of these is missing.`;
    case 'challenge_assumptions':
      return `**Challenging your assumptions**\n\n1. You assumed the read:write ratio holds under peak. What happens at 10x writes?\n2. You assumed the cache is warm. What is the latency when it is cold, and who absorbs that?\n3. You assumed strong consistency is needed. For which specific field, and what breaks with a stale read?\n4. You assumed the queue is unbounded. What is the backpressure policy when consumers fall behind?\n\nAnswer any one of these and I'll press on the weakest link.`;
    case 'failure_scenarios':
      return `**Failure scenarios to walk through**\n\n- **Primary database dies.** How long is the failover, and what is the write behaviour in the meantime?\n- **Cache node lost.** Does the origin survive the stampede, or is there request coalescing?\n- **Consumer crashes mid-processing.** At-least-once delivery means your handler must be idempotent. Is it?\n- **Network partition between regions.** Which side keeps serving writes, and how is divergence reconciled?\n- **Dependency timeout.** Is there a circuit breaker, and what is the degraded response?\n\nPick the scenario you find hardest and I'll walk it end to end with you.`;
    default:
      return `I can review your design, find scaling bottlenecks, challenge your assumptions or run a mock interview on it. Which direction is most useful right now?`;
  }
}

function generalFallback(message: string, contextType: AIContextType): string {
  const trimmed = message.trim();

  if (/bfs|dfs/i.test(trimmed)) {
    return `**BFS vs DFS**\n\n**BFS** explores level by level with a queue. It guarantees the shortest path in an unweighted graph and is the right tool for "minimum number of steps". Memory grows with the width of the frontier.\n\n**DFS** goes as deep as possible first, using a stack or recursion. It uses memory proportional to depth, which is far better on wide graphs, and it is the natural fit for exhaustive traversal, cycle detection and topological ordering.\n\nRule of thumb: *shortest* → BFS, *exhaustive or structural* → DFS.`;
  }

  if (/consistent hashing/i.test(trimmed)) {
    return `**Consistent hashing**\n\nHash both the nodes and the keys onto the same ring. A key belongs to the first node clockwise from its position. Adding or removing a node only remaps the arc it owns, so roughly $1/n$ of keys move instead of everything.\n\nIn practice each physical node is placed at many ring positions ("virtual nodes") so load spreads evenly and a single node failure doesn't hand its entire share to one neighbour.`;
  }

  if (/dynamic programming|\bdp\b/i.test(trimmed)) {
    return `**Dynamic programming in three questions**\n\n1. **What is the state?** The minimum set of values that fully describes a subproblem.\n2. **What is the transition?** How a state is computed from smaller states.\n3. **What is the base case?** The smallest state you can answer directly.\n\nDo those three in order and DP stops being guesswork. Memoisation is just the top-down form of the same recurrence; the bottom-up table is an optimisation, not a different idea.`;
  }

  if (/factory|strategy/i.test(trimmed)) {
    return `**Factory vs Strategy**\n\n**Factory** answers *"how do I create this?"* — it centralises construction so callers never bind to a concrete class.\n\n**Strategy** answers *"how do I behave right now?"* — it encapsulates interchangeable algorithms behind one interface so the choice can change at runtime.\n\nThey compose naturally: a factory selects and injects the strategy, keeping the decision in one place.`;
  }

  if (/caching/i.test(trimmed) && /question|quiz|interview|practice/i.test(trimmed)) {
    return `**Caching practice questions**\n\n1. Your cache hit rate is 92% and p99 latency is still bad. Where do you look first?\n2. A popular key expires and 5,000 requests hit the origin at once. How do you prevent the stampede?\n3. The product wants "delete a user, their data gone in 5 seconds". How does that affect your cache design?\n4. Cache-aside vs write-through for a write-heavy ledger — which, and why?\n\nAnswer #2 for me and I'll go deeper on coalescing strategies.`;
  }

  const scope = contextType === 'general' ? '' : ` within the **${contextType.toUpperCase()}** scope`;
  return `Happy to help with that${scope}.\n\nTo give you something concrete rather than generic: tell me the specific constraint you're stuck on. "Explain X" gets you a summary; "I tried X and it failed at Y" gets you the actual fix.\n\nSome directions I can take from here:\n- Break a concept down from first principles\n- Compare two approaches against a concrete constraint\n- Run a mock interview for a topic\n- Review code or a design you paste in`;
}

/**
 * Produces the assistant reply for a chat request. Deterministic given the same input,
 * so repeated demo runs are consistent.
 */
export function generateReply(payload: AIChatRequest, context: ResponderContext): string {
  const action = payload.action ?? 'general';
  const message = payload.message ?? '';

  // Design-workspace actions are shared across LLD and HLD panels.
  if (
    [
      'review_design',
      'solid_check',
      'missing_classes',
      'review_architecture',
      'scaling_bottlenecks',
      'database_choice',
      'api_design_review',
      'challenge_assumptions',
      'failure_scenarios',
    ].includes(action)
  ) {
    return codeActionFor(context, action as AIAction);
  }

  switch (action) {
    case 'give_hint':
      return hintFor(context);
    case 'explain_concept':
      return conceptFor(context);
    case 'explain_code':
      return codeFor(context, payload.selected_code);
    case 'find_bug':
      return bugFor(context, payload.selected_code);
    case 'complexity':
      return complexityFor(context, payload.selected_code);
    case 'alternative_approach':
      return alternativeFor(context);
    case 'interview_me':
      return interviewFor(context);
    default:
      break;
  }

  if (context.label && /hint|stuck|help/i.test(message)) {
    return hintFor(context);
  }

  return generalFallback(message, payload.context_type);
}
