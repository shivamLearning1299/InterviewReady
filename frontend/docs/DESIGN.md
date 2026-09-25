# InterviewReady — Frontend Design & Architecture

Companion document to the implementation in `frontend/`. It records the information
architecture, navigation, flows, design system, layout decisions and component inventory that
the code was built from.

---

## 1. Information architecture

Eight top-level destinations, grouped by how often they are used. Nothing is nested more than
two levels deep — a study tool you have to navigate is a study tool you avoid.

```
InterviewReady
├── Today                    ← daily driver: what to do right now
│
├── Learn (browse & drill)
│   ├── DSA                  → /dsa
│   │   └── Problem          → /dsa/:problemId
│   ├── Low-Level Design     → /lld
│   │   └── Topic            → /lld/:topicId
│   └── High-Level Design    → /hld
│       └── System           → /hld/:topicId
│
├── Retain (keep what you learned)
│   └── Revisions            → /revisions
│
├── Reflect (is it working?)
│   └── Statistics           → /stats
│
├── Help
│   └── AI Tutor             → /ai
│       └── Conversation     → /ai/:conversationId
│
└── Configure
    └── Settings             → /settings

Auth
├── Sign in                  → /login
└── Not found                → *
```

Three entity types — **Problem**, **LLD Topic**, **HLD Topic** — each with a list view and a
workspace view. The workspace views share a structural contract: breadcrumb, header with
progress controls, tabbed content, and an AI panel pinned to the right.

---

## 2. Page hierarchy & responsibilities

| Route | Page | Question it answers |
|---|---|---|
| `/` | Today | What should I do today? |
| `/dsa` | DSA catalog | What have I solved, what is left? |
| `/dsa/:id` | Problem workspace | Let me work on this problem |
| `/revisions` | Revisions | What do I need to review? |
| `/lld` | LLD curriculum | How far through LLD am I? |
| `/lld/:id` | LLD workspace | Let me design this thing |
| `/hld` | HLD curriculum | How far through HLD am I? |
| `/hld/:id` | HLD workspace | Let me design this system |
| `/stats` | Statistics | Is my studying working? |
| `/ai` | AI Tutor | Help me understand something |
| `/settings` | Settings | Change how this behaves |

**Deliberate omissions:** no dashboard/landing page (Today *is* the landing page), no global
"add problem" screen (the catalog is backend-seeded), no profile page (settings covers it).

---

## 3. Navigation structure

**Sidebar** — persistent, collapsible, state remembered in `localStorage['ir-sidebar-collapsed']`.

```
┌──────────────────┐
│ IR  InterviewReady│  ← brand
├──────────────────┤
│ ☀ Today       [3]│  ← revision-due badge when > 0
│ ≡ DSA            │
│ ↻ Revisions      │
│ ⛁ LLD            │
│ ▤ HLD            │
│ ▮ Statistics     │
│ ✦ AI Tutor       │
│ ⚙ Settings       │
├──────────────────┤
│ 🔥 14 days       │  ← collapsed-rail streak pill
└──────────────────┘
```

**Header** — search trigger (`⌘K`), streak indicator, theme menu, account menu.

**Mobile (< `lg`)** — sidebar becomes an off-canvas drawer with a body-scroll lock; the same
`Sidebar` component renders in both positions so the navigation never diverges.

**Command palette** — `⌘K` / `Ctrl+K`. Fuzzy search across problems, LLD topics, HLD topics and
your own notes, with scope filters (All / Problems / LLD / HLD). This is the only search in the
app; per-page filter bars are for *filtering a known list*, not finding things.

---

## 4. Major user flows

### 4.1 Daily study loop (the critical path)

```
Open app → Today
  │
  ├─ "Today's DSA: 0/3"  → tick a lesson off (optimistic, advances streak)
  │                       or click through → Problem workspace
  │
  ├─ "Revision due: 4"   → Revisions → Start revision session
  │
  └─ "Today's Design"    → LLD/HLD workspace
```

### 4.2 Solve a problem

```
/dsa → filter/search → click row → /dsa/:id
  │
  ├─ set Status → Solved (auto-schedules first revision)
  ├─ Code tab   → Monaco, autosaves, multi-solution tabs
  ├─ Notes tab  → approach, complexity, mistakes, lesson
  ├─ Attempts   → log outcome + confidence
  └─ AI panel   → hint / concept / complexity / review
```

### 4.3 Revision session (active recall)

```
/revisions → Start revision session
  │
  Problem 1 / 8   ⏱ 04:12
  ├─ "Explain the approach out loud"          ← no answers visible
  ├─ [Show previous approach] [Show previous code]   ← opt-in reveal
  └─ [Mark successful] [Partially recalled] [Still weak]
        │
        └─ records result → advances or resets the interval → next problem
```

The concealment is the point: a queue that shows you the answer is a queue that teaches you
nothing.

### 4.4 Design a system

```
/hld → category group → click topic → /hld/:id
  │
  ├─ Requirements  → functional, non-functional, capacity
  ├─ Design Doc    → 10 numbered sections (4–13)
  ├─ Diagram       → plain-text architecture sketch
  └─ Interview Notes → how it went, what you missed
        │
        └─ AI panel → review_architecture, scaling_bottlenecks,
                      database_choice, failure_scenarios, …
```

### 4.5 Auth

```
Any protected route → RequireAuth
  ├─ session valid   → render
  └─ no session      → /login (stashes `location.state.from`)
                        → sign in → redirected to the originally-requested route
```

---

## 5. UI design system

### 5.1 Principles

1. **Restraint over decoration.** No gradients, no glassmorphism, no oversized hero cards.
2. **Density is a feature.** A study tool shows a lot at once; generous padding wastes screen.
3. **Numbers are tabular.** Every count aligns (`font-variant-numeric: tabular-nums`).
4. **Colour carries meaning, never decoration.** Red = overdue, amber = needs work, green = done.
5. **Empty states explain and offer the one action** that would populate them.
6. **Dark and light are equals.** Same layout, same hierarchy — only the tokens change.

### 5.2 Tokens

Defined once in `src/styles/index.css` as CSS custom properties, mapped to Tailwind utilities
via `@theme inline`. Dark mode is a class-based variant (`@custom-variant dark`), applied to
`<html>` before first paint by an inline script in `index.html` — so there is no theme flash.

| Group | Tokens |
|---|---|
| Surface | `--background`, `--surface`, `--surface-hover`, `--muted`, `--overlay`, `--sidebar` |
| Text | `--foreground`, `--muted-foreground`, `--subtle-foreground` |
| Border | `--border`, `--border-strong`, `--ring` |
| Accent | `--primary`, `--primary-hover`, `--primary-foreground`, `--primary-soft`, `--accent` |
| Semantic | `--success`, `--warning`, `--danger`, `--info` (+ `-soft` variants) |
| Difficulty | `--easy`, `--medium`, `--hard` (+ `-soft`) |
| Charts | `--chart-1…5`, `--chart-grid`, `--chart-axis` |
| Geometry | `--radius-card: 0.625rem`, `--radius-control: 0.5rem` |

Recharts reads the chart tokens as CSS variables, so a theme switch re-colours the charts with
no JavaScript.

### 5.3 Typography

- **UI:** Inter Variable, self-hosted via `@fontsource-variable/inter`.
- **Code:** system monospace stack (`ui-monospace, SFMono-Regular, …`).
- **Scale:** `20px` page title, `14px` section heading, `13px` body/controls, `12px` metadata,
  `11px` uppercase eyebrow labels. Nothing larger than 24px — this is a tool, not a poster.

### 5.4 Spacing & shape

4px base unit. Cards `10px` radius, controls `8px`. Section rhythm: `12px` inside a card,
`16px` between cards, `20px` between page sections. Borders are 1px at `--border`; hover states
step to `--border-strong` rather than adding shadow.

---

## 6. Desktop wireframes

### 6.1 Today (`/`)

```
┌────────────┬──────────────────────────────────────────────────────────────┐
│  SIDEBAR   │  ┌ Search problems, topics, notes…  ⌘K ┐   🔥14  ◐  ACCOUNT │
│            ├──────────────────────────────────────────────────────────────┤
│ ☀ Today 3  │  Still up, Demo                        [ ▶ Start study timer]│
│ ≡ DSA      │  🔥 14 day streak · 34/69 DSA solved · 2h 3m studied today    │
│ ↻ Revisions│                                                              │
│ ⛁ LLD      │  ┌ Today's DSA ──────────────── 0/3 ──── All problems → ┐    │
│ ▤ HLD      │  │ ☐ 1  Subarray Sum Equals K      Medium  [Continue →] │    │
│ ▮ Stats    │  │      Arrays & Hashing · Why today: weak topic        │    │
│ ✦ AI Tutor │  │ ☐ 2  Number of Islands          Medium  [Continue →] │    │
│ ⚙ Settings │  │ ☐ 3  Merge Intervals            Medium  [Continue →] │    │
│            │  └──────────────────────────────────────────────────────┘    │
│            │                                                              │
│            │  ┌ Revision due ── 4 ───────┐  ┌ Weekly progress ─────────┐ │
│            │  │ ▤ 4 due  ⚠ 4 overdue      │  │  ▁ █ ▅ █ █ ▅ ▂          │ │
│            │  │ Valid Parens      Easy  → │  │  M T W T F S S          │ │
│            │  │ Linked List Cycle Easy  → │  │  12 solved · 6h 40m     │ │
│            │  │ Valid Anagram     Easy  → │  └─────────────────────────┘ │
│            │  └───────────────────────────┘                              │
│            │                                                              │
│ 🔥 14 days │  ┌ Today's Design ──────────┐  ┌ AI Tutor (general) ──────┐ │
│            │  │ ⛁ LLD · OOP Refactor     │  │ [Explain DP] [BFS vs DFS]│ │
│            │  │   Not Started         →  │  │                          │ │
│            │  │ ▤ HLD · Scalable Msging  │  │ ┌──────────────────────┐ │ │
│            │  │   Not Started         →  │  │ │ Ask about strategy…  │ │ │
│            │  └──────────────────────────┘  └──────────────────────────┘ │
└────────────┴──────────────────────────────────────────────────────────────┘
```

### 6.2 DSA catalog (`/dsa`)

```
┌────────────┬──────────────────────────────────────────────────────────────┐
│  SIDEBAR   │  Data Structures & Algorithms                                │
│            │  127 / 400 solved · 41 mastered · 3 need revision            │
│            ├──────────────────────────────────────────────────────────────┤
│            │ ┌ 🔍 Search ──────┐ [Topic ▾] [Difficulty ▾] [Status ▾] [▤|☰]│
│            ├──────────────────────────────────────────────────────────────┤
│            │ #  Problem               Topic            Diff   Status  ▸  │
│            │ 1  Subarray Sum Equals K Arrays & Hash.  Medium Attempted  │
│            │ 2  Number of Islands     Graphs          Medium Attempted  │
│            │ 3  Merge Intervals       Intervals       Medium Attempted  │
│            │ 4  Valid Parentheses     Stack           Easy   Solved     │
│            │ …                                                            │
│            ├──────────────────────────────────────────────────────────────┤
│            │                                              ┌ Progress ─────┐│
│            │                                              │ Easy   42/120 ││
│            │                                              │ Medium 68/200 ││
│            │                                              │ Hard   17/80  ││
│            │                                              └───────────────┘│
└────────────┴──────────────────────────────────────────────────────────────┘
```

### 6.3 Problem workspace (`/dsa/:id`)

```
┌────────────────────────────────────────────────────────────┬───────────────┐
│ ← DSA  /  Arrays & Hashing                    Original ↗   │  AI TUTOR     │
├────────────────────────────────────────────────────────────┤               │
│ Subarray Sum Equals K  Medium  ☆                           │ Context:      │
│ Arrays & Hashing • Prefix Sum • Hash Map                   │ Subarray Sum… │
│ Leetcode · ~35m · 2 attempts · 41m logged                  │               │
│  Status [Attempted ▾]  Conf ▁▂▃▄▅  Next rev: —             │ [Hint]        │
│  [✓ Mark solved] [⏱ Time me]                                │ [Concept]     │
├────────────────────────────────────────────────────────────┤ [Code]        │
│ [ Code 1 ] [ Notes ] [ Attempts 2 ] [ Revision History ]   │ [Complexity]  │
├────────────────────────────────────────────────────────────┤ [Alt approach]│
│ ▤ Solution · Python · primary                    [+ Add]    │ [Interview me]│
│ ┌────────────────────────────────────────────────────────┐ │               │
│ │ 1  """Subarray Sum Equals K — Prefix Sum, Hash Map     │ │ ┌───────────┐ │
│ │ 2     Approach: see notes. O(n) time, O(n) space."""   │ │ │ Ask…      │ │
│ │ 3                                                       │ │ └───────────┘ │
│ │ 4  def solve(data):                                    │ │ [ Send ]      │
│ │ 5      seen = {}                                        │ │               │
│ │ …                                                       │ │               │
│ └────────────────────────────────────────────────────────┘ │               │
│ Autosaves as you type                        Updated 4d ago│               │
│ Stored as plain text — never compiled or run.               │               │
└────────────────────────────────────────────────────────────┴───────────────┘
```

### 6.4 Revisions (`/revisions`)

```
┌────────────┬──────────────────────────────────────────────────────────────┐
│  SIDEBAR   │  Revisions            [↻ Queue stale] [✦ Start session]      │
│            │  Spaced repetition over everything you have solved.          │
│            ├──────────────────────────────────────────────────────────────┤
│            │ ┌Due today 0┐┌Overdue 4 ─┐┌Upcoming 10┐┌ Queue ───────────┐ │
│            │ └───────────┘└───────────┘└───────────┘└ 4/14 need now     │ │
│            ├──────────────────────────────────────────────────────────────┤
│            │ [Due today] [Overdue 4] [Upcoming 10]                        │
│            │ ┌────────────────────────────────────┐ ┌ Weak topics ──────┐│
│            │ │ Minimum Window Substring    ⚠Overdue│ │ Graphs      14%  ││
│            │ │ Hard · Sliding Window    5d overdue│ │ ▓░░░░░░░░░       ││
│            │ │ Last solved 17 Sep · Confidence:   │ │ 1/7 solved       ││
│            │ │ Struggling · Interval 2d           │ │ Intervals   25%  ││
│            │ │ ⟲ Scheduled because: Low confidence│ │ ▓▓░░░░░░░░       ││
│            │ │                                    │ │ Heap        33%  ││
│            │ │ Median of Two Sorted Arrays Overdue│ │ ▓▓▓░░░░░░░       ││
│            │ │ Hard · Binary Search     1d overdue│ │ …                ││
│            │ │ …                                  │ │                  ││
│            │ └────────────────────────────────────┘ └──────────────────┘│
└────────────┴──────────────────────────────────────────────────────────────┘
```

**Active session (expands inline):**

```
┌──────────────────────────────────────────────────────────────────────────┐
│ Problem 1 / 8   ⏱ 04:12                             [← Prev] [Skip →] [✕]│
│ ████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
├──────────────────────────────────────────────────┬───────────────────────┤
│ Minimum Window Substring                         │  AI TUTOR             │
│ 5 days overdue · confidence before Struggling    │  (scoped to this      │
│                                                  │   problem)            │
│ ┌──────────────────────────────────────────────┐ │                       │
│ │ Explain the approach out loud before         │ │                       │
│ │ revealing anything. What was the key insight?│ │                       │
│ └──────────────────────────────────────────────┘ │                       │
│                                                  │                       │
│ [📄 Show previous approach] [<> Show previous code] [Open problem ↗]     │
│                                                  │                       │
│ ┌─ previous approach / code hidden ────────────┐ │                       │
│ │            ◉  Previous approach and code      │ │                       │
│ │               are hidden.                     │ │                       │
│ └──────────────────────────────────────────────┘ │                       │
│                                                  │                       │
│ ─────────────────────────────────────────────────┤                       │
│ [↑ Mark successful] [Partially] [↓ Still weak]   │                       │
├──────────────────────────────────────────────────┴───────────────────────┤
│ 0 reviewed · 8 remaining              ◉ Answers stay hidden until asked  │
└──────────────────────────────────────────────────────────────────────────┘
```

### 6.5 LLD / HLD catalog (`/lld`, `/hld`)

```
┌────────────┬──────────────────────────────────────────────────────────────┐
│  SIDEBAR   │  Low-Level Design                                            │
│            │  14 / 24 completed · 3 mastered · 1 need revision            │
│            ├──────────────────────────────────────────────────────────────┤
│            │ ┌ 🔍 Search topics ─┐ [Category ▾] [Status ▾]                │
│            ├──────────────────────────────────────────────────────────────┤
│            │ ┌ Fundamentals ────────── 4/6 ────────── ▓▓▓▓░░ 67% ────────┐│
│            │ │ Object-Oriented Programming        ▓▓▓▓▓░░░ 80%  Completed ││
│            │ │ Encapsulation, inheritance,        ▓▓▓▓▓░░░ 80%  Completed ││
│            │ │ polymorphism and abstraction…                                │
│            │ │ [Encapsulation][Inheritance][Polymorphism]                  ││
│            │ ├─────────────────────────────────────────────────────────────┤│
│            │ │ SOLID Principles                   ▓▓▓░░░░░ 35%  Learning  ││
│            │ └─────────────────────────────────────────────────────────────┘│
│            │ ┌ Design Patterns ─────── 7/8 ────────── ▓▓▓▓▓▓▓░ 88% ───────┐│
│            │ │ Factory Pattern   Strategy Pattern   Observer …             ││
│            │ └─────────────────────────────────────────────────────────────┘│
│            ├──────────────────────────────────────────────────────────────┤
│            │                                    ┌ Overall progress ──────┐│
│            │                                    │ 14/24 ▓▓▓▓▓▓░░░ 58%    ││
│            │                                    │ Completed    10        ││
│            │                                    │ Mastered      3        ││
│            │                                    │ Learning      6        ││
│            │                                    │ Needs rev.    1        ││
│            │                                    │ Not started   4        ││
│            │                                    └────────────────────────┘│
└────────────┴──────────────────────────────────────────────────────────────┘
```

### 6.6 HLD workspace — design document (`/hld/:id`)

```
┌────────────────────────────────────────────────────────────┬───────────────┐
│ ← HLD  /  Scalability                                       │  AI TUTOR     │
├────────────────────────────────────────────────────────────┤ Context:      │
│ Scalability  Completed  Easy                                │ Scalability   │
│ What breaks first as load grows…                            │               │
│                                   ⏱ 00:00  [Start]          │ [Review arch] │
│  Status [NotStarted][Learning][Completed][NeedsRev][Mastered]│ [Scaling      │
│  Conf ▁▂▃▄▅    Completion ▓▓▓▓▓▓▓▓░░ 80%                    │  bottlenecks] │
├────────────────────────────────────────────────────────────┤ [DB choice]   │
│ [ Requirements 3 ] [ Design Document 0/13 ] [ Diagram ]     │ [Failure      │
│                                              [ Interview ]  │  scenarios]   │
├────────────────────────────────────────────────────────────┤ [API review]  │
│ Design document   0 of 13 written   Autosaves   [Save now]  │               │
│ ┌────────────────────────────────────────────────────────┐ │               │
│ │ 4. API Design                                           │ │               │
│ │ ┌────────────────────────────────────────────────────┐ │ │               │
│ │ │ The handful of endpoints that matter…               │ │ │               │
│ │ └────────────────────────────────────────────────────┘ │ │               │
│ ├────────────────────────────────────────────────────────┤ │               │
│ │ 5. Data Model                                           │ │               │
│ │ ┌────────────────────────────────────────────────────┐ │ │               │
│ │ │ Entities, key fields, access patterns…              │ │ │               │
│ │ └────────────────────────────────────────────────────┘ │ │               │
│ ├────────────────────────────────────────────────────────┤ │               │
│ │ 6. Database Choice · 7. High-Level Architecture        │ │               │
│ │ 8. Caching · 9. Message Queues · 10. Scaling           │ │               │
│ │ 11. Failure Handling · 12. Tradeoffs · 13. Final Notes │ │               │
│ └────────────────────────────────────────────────────────┘ │               │
├────────────────────────────────────────────────────────────┤               │
│ 50 min studied · last reviewed Yesterday                    │               │
└────────────────────────────────────────────────────────────┴───────────────┘
```

### 6.7 Statistics (`/stats`)

```
┌────────────┬──────────────────────────────────────────────────────────────┐
│  SIDEBAR   │  Statistics                                  🔥 14 days       │
│            ├──────────────────────────────────────────────────────────────┤
│            │  COVERAGE                                                    │
│            │ ┌DSA solved───┐┌LLD completed┐┌HLD completed┐┌Revision─────┐ │
│            │ │ 127 / 400   ││ 18 / 50     ││ 16 / 40     ││ backlog  4  │ │
│            │ │ 41 mastered ││ 6 mastered  ││ 5 mastered  ││ 4 overdue   │ │
│            │ │ ▓▓▓░░░░░░░  ││ ▓▓▓▓░░░░░░  ││ ▓▓▓▓░░░░░░  ││ Review now →│ │
│            │ └─────────────┘└─────────────┘└─────────────┘└─────────────┘ │
│            │  STUDY CADENCE                                               │
│            │ ┌Current──────┐┌Longest─────┐┌Study this wk┐┌Solved today─┐ │
│            │ │ 14 d        ││ 21 d        ││ 6h 40m      ││ 3           │ │
│            │ └─────────────┘└─────────────┘└─────────────┘└─────────────┘ │
│            ├──────────────────────────────────────────────────────────────┤
│            │ ┌ Problems solved      [7d][30d][90d][1y] ┐┌ Study time ────┐│
│            │ │      ╭─╮   ╭──╮                          ││  ▂█▅██▅▂      ││
│            │ │  ╭─╮ │ │ ╭─│  │ ──── attempted           ││  M T W T F S S││
│            │ │ ╭│ ╰─╯ ╰╯ ╰─╯  ╰─ solved                  ││               ││
│            │ └──────────────────────────────────────────┘└───────────────┘│
│            ├──────────────────────────────────────────────────────────────┤
│            │ ┌ Topic strength ───────────┐ ┌ Difficulty mix ────────────┐│
│            │ │ Arrays&Hash ████████      │ │ ▓▓▓▓▓▓▓▓░░░░░            ││
│            │ │ Two Pointers ██████       │ │ Easy    42/120 ▓▓▓░░░     ││
│            │ │ Sliding Win. ████         │ │ Medium  68/200 ▓▓▓▓░░     ││
│            │ │ Graphs       ██           │ │ Hard    17/80  ▓░░░░░     ││
│            │ │ DP           ███          │ ├───────────────────────────┤│
│            │ │ (horizontal, stacked)     │ │ Strongest  /  Weakest     ││
│            │ └───────────────────────────┘ └───────────────────────────┘│
└────────────┴──────────────────────────────────────────────────────────────┘
```

---

## 7. Reusable component inventory

### Primitives — `src/components/ui/` (12)

| Component | Exports | Notes |
|---|---|---|
| `button` | `Button` | 7 variants × 5 sizes, `loading`, `asChild` |
| `card` | `Card`, `CardHeader`, `CardDivider` | 4 paddings, 2 tones |
| `badge` | `Badge` | difficulty/semantic/outline tones, optional dot |
| `input` | `Input`, `Textarea`, `Select`, `Field` | `Field` = label + control + hint/error |
| `empty-state` | `EmptyState`, `ErrorState` | both take an optional action |
| `skeleton` | `Skeleton`, `SkeletonRow`, `SkeletonTable`, `SkeletonCard`, `SkeletonText`, `Spinner` | mirror real content shape |
| `progress` | `ProgressBar`, `ProgressStat`, `StackedBar`, `ProgressRing` | 9 tones |
| `tabs` | `Tabs`, `VerticalTabs` | ARIA tablist + arrow-key nav |
| `menu` | `Menu`, `MenuItem`, `MenuLabel`, `MenuSeparator` | Radix popover shell |
| `dialog` | `Dialog` | Radix dialog shell |
| `switch` | `Switch`, `SegmentedControl`, `ConfidencePicker`, `ConfidenceMeter` | confidence is 1–5 throughout |
| `tooltip` | `Tooltip`, `SectionHeader`, `MetaItem`, `InfoRow` | |

### Shared domain components — `src/components/shared/` (6)

| Component | Purpose |
|---|---|
| `DifficultyBadge`, `StatusBadge`, `TopicBadge`, `PatternList`, `OutcomeBadge` | every domain label resolves through `lib/status.ts`, so a badge in a table, a chip and a chart legend always agree |
| `ProblemRow`, `ProblemTableHeader` | row + card variants of a catalog entry |
| `RevisionCard`, `RevisionHistoryRow`, `RevisionProgress` | revision queue + history |
| `CurriculumItem`, `CurriculumGroupHeader` | LLD/HLD topic rows and category headers |
| `StatCard`, `ProgressStatCard`, `StreakBadge` | metric tiles |
| `PageHeader`, `FilterBar`, `WorkspaceLayout` | page chrome and the 2-column workspace grid |

### Feature components — `src/features/`

| Area | Components |
|---|---|
| `code/` | `CodeEditor` (Monaco), `EditorPlaceholder`, `CodeBlock`, `SolutionsWorkspace` (multi-solution tabs), `useAutosave` |
| `ai/` | `AITutorPanel` — panel **and** page variants, escalating hints, selection-aware |
| `shared/` | `CurriculumCatalog` (LLD+HLD in one), `TopicNotesEditor` (generic structured notes), `DesignWorkspaceShell`, `ReferenceCard` |
| `today/` | `TodayItemRow`, `TodaySectionCard`, `TodaySectionSkeleton`, `greetingFor`, `useWeeklyProgress` |
| `dsa/` | `DsaFilterBar`, `ViewToggle`, `DsaProgressPanel`, `DifficultyBreakdownBar`, `ProblemHeader`, `NotesEditor`, `AttemptsPanel`, `RevisionHistoryPanel` |

### Why some things are shared

- **`CurriculumCatalog`** serves both LLD and HLD. They are the same shape — a categorised topic
  list with per-user progress — so writing it once prevents the two screens from drifting apart
  the first time a filter is added.
- **`TopicNotesEditor`** drives all three notes documents (LLD, HLD, and the section groups inside
  HLD) from a `sections` array. A hook-per-field design would fire 13 requests per keystroke.
- **`DesignWorkspaceShell`** holds the breadcrumb, title, status/confidence controls and timer
  shared by the LLD and HLD workspaces.

---

## 8. Responsive behaviour

Desktop-first, because the primary use is a problem workspace with an editor and a side panel.

| Breakpoint | Behaviour |
|---|---|
| `< 640px` | Single column. Sidebar is a drawer. AI panel moves below content (it stays mounted, so the conversation survives). Catalog switches to cards. Filter bar wraps. Meta lines collapse to the essentials. |
| `640–1024px` | Two-column metric grids. Catalog keeps the table but hides the progress column. Filter bar in one row. |
| `1024–1280px` | Sidebar is visible again. Two-column chart layout. |
| `≥ 1280px` (`xl`) | Full layout: content + 22rem AI panel, catalogs get a 20rem progress rail. |

Two things are deliberately **never** hidden: the study timer and the streak. They are the
reason the user is in the app.

---

## 9. Frontend folder structure

```
frontend/
├── index.html                  ← includes the pre-paint theme script
├── vite.config.ts              ← /api proxy, @ alias, Monaco chunk split
├── tsconfig.json               ← project references
├── tsconfig.app.json           ← strict + noUnusedLocals + verbatimModuleSyntax
├── .env.example
└── src/
    ├── main.tsx                ← mount + font import
    ├── styles/index.css        ← Tailwind v4 CSS-first config: tokens, base, utilities
    │
    ├── types/                  ← 1 module per backend schema file
    │   ├── common.ts           ← enums + shared shapes (ProgressSummary, TopicProgressSummary)
    │   ├── dsa.ts  lld.ts  hld.ts
    │   ├── today.ts  stats.ts  ai.ts  settings.ts  search.ts
    │   └── index.ts
    │
    ├── api/
    │   ├── config.ts           ← env reading, one place
    │   ├── contract.ts         ← the ApiClient interface
    │   ├── client.ts           ← `api` = USE_MOCKS ? mockClient : realClient
    │   ├── http.ts  errors.ts  auth.ts
    │   └── endpoints/          ← core, dsa, revisions, design, stats, ai, settings, all
    │
    ├── mocks/                  ← a complete in-memory backend
    │   ├── seed.ts             ← 72 DSA problems, 24 LLD topics, 16 HLD systems
    │   ├── deterministic.ts    ← seeded RNG + stable id factory
    │   ├── store.ts            ← mutable state + derived builders
    │   ├── ai-responder.ts     ← deterministic, context-aware tutor replies
    │   └── client.ts           ← `mockClient: ApiClient`
    │
    ├── services/search-service.ts   ← client-side search fan-out + ranking
    │
    ├── lib/
    │   ├── constants.ts   status.ts   format.ts   helpers.ts
    │   ├── query-keys.ts  ← query keys + `routes` link helpers
    │   ├── timezone.ts    utils.ts
    │
    ├── providers/              ← theme, auth, sidebar
    ├── hooks/                  ← use-api (all queries/mutations), use-study-timer
    │
    ├── components/
    │   ├── ui/                 ← 12 primitives
    │   └── shared/             ← 6 domain components
    │
    ├── features/               ← one folder per domain, each owning its pages
    │   ├── today/  dsa/  revision/  lld/  hld/  stats/  ai/  settings/  auth/
    │   ├── code/               ← editor, autosave, multi-solution workspace
    │   └── shared/             ← cross-feature: catalog, notes editor, workspace shell
    │
    └── app/                    ← composition root
        ├── App.tsx             ← providers + route table (lazy where it pays)
        ├── app-shell/          ← app-shell, sidebar, header, command-palette
        ├── require-auth.tsx  error-boundary.tsx
        ├── route-fallback.tsx  scroll-to-top.tsx
```

### Architectural decisions worth stating

**The API layer is dual-implementation.** `ApiClient` (`api/contract.ts`) is implemented twice:
`realClient` (thin HTTP wrappers over the FastAPI routes) and `mockClient` (a stateful in-memory
simulation). `VITE_USE_MOCKS` picks one at startup. Components only ever import `api`, so the
switch is invisible to them — and because the mock implements the same interface, it cannot drift
from the real contract without a type error.

**Types mirror the backend schemas exactly.** `types/dsa.ts` corresponds to
`backend/app/schemas/dsa.py`, and so on. Where the UI needs a derived shape it derives it in the
component rather than inventing a parallel type.

**`ProgressSummary` has no `revision_count`.** The catalog's embedded progress object and the
standalone `ProgressResponse` are different types on the backend, and the UI respects that
distinction instead of assuming fields exist.

**Monaco is loaded but never executed.** Code is stored as plain text. There is no compiler and no
sandbox — the app explicitly tells the user this at the bottom of the editor.

**Query invalidation follows the domain.** Solving a problem invalidates the catalog, the
revision queue, Today's plan and the statistics together, because all four are affected. Leaving
any of them stale is what makes a dashboard feel wrong.

---

## 10. Accessibility

- Tabs use `role="tablist"` / `role="tab"` with `aria-selected` and arrow-key navigation.
- The confidence picker is a real `radiogroup`, not five buttons.
- Toasts are announced via a `role="region"` live region; `aria-live="polite"` on autosave status.
- All icon-only buttons carry `aria-label`.
- Focus is visible everywhere (`:focus-visible` ring, `--ring` token) — including inside Monaco.
- `prefers-reduced-motion` is respected in the CSS layer.
- Colour is never the only signal: overdue items carry both a red label *and* the word "Overdue".
