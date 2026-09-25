"""Prompt and context construction for the AI tutor.

Two rules drive this module:

**Minimal context.** The requirement is explicit: never send the user's whole database.
Each request assembles only what the chosen ``context_type`` needs — the problem's title,
topic, patterns and the user's own notes/confidence for DSA; the current topic plus notes
for LLD/HLD; nothing but the conversation for ``general``. Selected code is included only
when the action calls for it.

**Pedagogy guardrails.** The default tutor behaviour is *not* to hand over an answer. The
system prompts enforce progressive hints, explain the underlying pattern, and withhold full
code unless the user explicitly asks for it (or has turned on
``ai_auto_reveal_solution``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.constants import AIAction, AIContextType, ProblemStatus
from app.core.logging import get_logger

logger = get_logger(__name__)

#: Shared preamble: identity, tone, and the anti-spoiler rules.
BASE_SYSTEM_PROMPT = """You are the InterviewReady tutor, helping a software engineer prepare \
for technical interviews.

How you teach:
- Be concise and concrete. Prefer a short, well-chosen explanation over a long one.
- Diagnose before prescribing: state what the user's mistake or gap appears to be.
- Never restate the user's whole question back at them.
- Use small examples with actual values rather than abstract descriptions.

Non-negotiable guardrails:
- Do NOT reveal a complete solution unless the user explicitly asks for full code.
- Default to the smallest hint that unblocks the user, and offer to go further.
- If the user asks for the answer outright, first confirm by offering a hint; then comply.
- Never invent constraints, test cases, or problem statements you were not given.
- If the provided context is insufficient, say what you would need instead of guessing.
"""

#: Per-action instructions appended to the base prompt.
ACTION_PROMPTS: dict[str, str] = {
    AIAction.EXPLAIN_CONCEPT.value: (
        "The user wants to understand an underlying concept.\n"
        "Explain the *pattern* and when it applies, using a minimal example. "
        "Do not solve their specific problem for them."
    ),
    AIAction.GIVE_HINT.value: (
        "The user wants a hint ONLY.\n"
        "Give exactly one progressive hint — the smallest insight that moves them forward. "
        "Do not provide pseudocode. End by asking what they will try next."
    ),
    AIAction.EXPLAIN_CODE.value: (
        "The user shared code and wants it explained.\n"
        "Walk through it in execution order. State the time and space complexity and "
        "identify any subtle behaviour (off-by-one, mutation, early exit)."
    ),
    AIAction.FIND_BUG.value: (
        "The user's code is failing. Find the bug.\n"
        "1. State the failing condition in one line.\n"
        "2. Name the exact line or expression responsible.\n"
        "3. Explain the fix conceptually — give the corrected code only if asked."
    ),
    AIAction.COMPLEXITY.value: (
        "Analyse time and space complexity.\n"
        "Justify each term by pointing at the specific loop, recursion or data structure "
        "that produces it. Mention the worst case explicitly."
    ),
    AIAction.ALTERNATIVE_APPROACH.value: (
        "Offer a different approach to the one the user appears to be taking.\n"
        "Compare the two on time, space, and code complexity. Be honest when the user's "
        "current approach is already the better trade-off."
    ),
    AIAction.INTERVIEW_ME.value: (
        "Act as a realistic technical interviewer for this topic.\n"
        "Ask ONE question at a time and wait for the answer. Probe the user's reasoning "
        "and edge cases. Do not supply the solution; give feedback on their answer after "
        "they respond."
    ),
    AIAction.GENERAL.value: (
        "Answer the user's question directly and helpfully, staying within the subject of "
        "software engineering interview preparation."
    ),
}

#: Appended when the user has enabled automatic solution reveals.
REVEAL_OVERRIDE = (
    "\n\nThe user has enabled automatic solution reveals for this account, so you may "
    "provide complete, working code when it is the most direct answer."
)


@dataclass(slots=True)
class TutorContext:
    """The minimal context assembled for one tutor request.

    Every field is optional and populated only when relevant, which keeps prompts small
    and avoids shipping unrelated personal data to a third party.
    """

    context_type: str
    context_id: str | None = None
    context_label: str | None = None
    #: Structured facts about the entity (title, topic, patterns, difficulty, ...).
    entity: dict[str, Any] = field(default_factory=dict)
    #: The user's own notes for the entity.
    notes: dict[str, Any] = field(default_factory=dict)
    #: The user's progress signals (status, confidence, attempts).
    progress: dict[str, Any] = field(default_factory=dict)
    #: Only populated when the action requires it.
    code: str | None = None
    #: Conversation history, already trimmed to the configured window.
    history: list[dict[str, str]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """A description of what was sent — logged instead of the prompt itself.

        Includes field names and sizes, never the user's content, so the log stream stays
        free of private notes and code.
        """
        return {
            "context_type": self.context_type,
            "has_entity": bool(self.entity),
            "entity_fields": sorted(self.entity),
            "notes_fields": [key for key, value in self.notes.items() if value],
            "has_progress": bool(self.progress),
            "progress_status": self.progress.get("status"),
            "has_code": bool(self.code),
            "code_chars": len(self.code) if self.code else 0,
            "history_messages": len(self.history),
        }

    def render(self) -> str:
        """Serialise the context into a compact block for the system prompt."""
        sections: list[str] = []

        if self.entity:
            lines = [f"- {key}: {value}" for key, value in self.entity.items() if value]
            if lines:
                sections.append("### Problem context\n" + "\n".join(lines))

        if self.progress:
            lines = [f"- {key}: {value}" for key, value in self.progress.items() if value is not None]
            if lines:
                sections.append("### The user's current progress\n" + "\n".join(lines))

        populated_notes = {key: value for key, value in self.notes.items() if value}
        if populated_notes:
            lines = [
                f"**{key.replace('_', ' ').title()}**\n{value}"
                for key, value in populated_notes.items()
            ]
            sections.append(
                "### The user's own notes\n"
                "These are the user's words, not ground truth. Correct them if wrong.\n\n"
                + "\n\n".join(lines)
            )

        if self.code:
            sections.append(
                "### Code the user is asking about\n```\n" + self.code.strip() + "\n```"
            )

        return "\n\n".join(sections)


def build_system_prompt(
    *,
    action: str,
    context: TutorContext,
    auto_reveal_solution: bool = False,
) -> str:
    """Assemble the final system prompt for a request."""
    parts = [BASE_SYSTEM_PROMPT, ACTION_PROMPTS.get(action, ACTION_PROMPTS[AIAction.GENERAL.value])]

    rendered = context.render()
    if rendered:
        parts.append(rendered)

    if auto_reveal_solution:
        parts.append(REVEAL_OVERRIDE)

    return "\n\n".join(parts)


def select_entity_fields(
    *, context_type: str, problem: Any = None, topic: Any = None
) -> dict[str, Any]:
    """Pick the fields worth sending for the relevant entity.

    Deliberately excludes anything large or unrelated — no full catalogs, no other users'
    data, no historical attempts list.
    """
    if problem is not None:
        return {
            "title": problem.title,
            "difficulty": problem.difficulty,
            "primary_topic": problem.primary_topic,
            "patterns": ", ".join(problem.patterns) if problem.patterns else None,
            "companies": ", ".join(problem.companies[:5]) if problem.companies else None,
            "source": problem.source,
        }

    if topic is not None:
        return {
            "title": topic.title,
            "category": topic.category,
            "difficulty": topic.difficulty,
            "key_concepts": ", ".join(topic.key_concepts) if topic.key_concepts else None,
            "description": (topic.description or "")[:500] or None,
        }

    return {}


def select_progress_fields(progress: Any) -> dict[str, Any]:
    """The progress signals that change how the tutor should pitch its answer."""
    if progress is None:
        return {}
    return {
        "status": getattr(progress, "status", None),
        "confidence": getattr(progress, "confidence", None),
        "attempts": getattr(progress, "attempts", None),
        "times_reviewed": getattr(progress, "revision_count", None),
    }


def select_note_fields(*, context_type: str, notes: Any) -> dict[str, Any]:
    """Trim the user's notes to the fields that inform tutoring.

    Values are truncated so a pasted wall of text cannot dominate the prompt or the bill.
    """
    if notes is None:
        return {}

    if context_type == AIContextType.DSA.value:
        keys = ("approach", "notes", "mistakes", "revision_notes", "time_complexity", "space_complexity")
    elif context_type == AIContextType.LLD.value:
        keys = ("summary", "design_explanation", "class_responsibilities", "relationships", "mistakes")
    elif context_type == AIContextType.HLD.value:
        keys = (
            "functional_requirements",
            "non_functional_requirements",
            "high_level_architecture",
            "tradeoffs",
            "final_notes",
        )
    else:
        return {}

    result: dict[str, Any] = {}
    for key in keys:
        value = getattr(notes, key, None)
        if value:
            result[key] = str(value)[:1500]
    return result


def history_for_prompt(
    messages: list[Any], *, max_messages: int
) -> list[dict[str, str]]:
    """Convert stored messages into provider turns, newest window only.

    ``max_messages`` is enforced here rather than at read time so the boundary is explicit
    and testable: the tutor never forwards an unbounded conversation.
    """
    trimmed = messages[-max_messages:] if max_messages > 0 else []
    return [
        {"role": message.role, "content": message.content}
        for message in trimmed
        if message.role in ("user", "assistant") and message.content
    ]


def default_conversation_title(*, context_type: str, context_label: str | None, message: str) -> str:
    """A short, human-readable title for a new conversation."""
    if context_label:
        return f"{context_label} — {context_type.upper()}"[:200]
    snippet = message.strip().splitlines()[0] if message.strip() else "New conversation"
    return snippet[:120]


def answer_looks_like_full_solution(action: str) -> bool:
    """Whether an action inherently expects complete code in the reply.

    Used by tests and by any future post-processing that wants to warn when a hint-only
    action returned a full solution.
    """
    return action in {AIAction.EXPLAIN_CODE.value, AIAction.FIND_BUG.value}


__all__ = [
    "ACTION_PROMPTS",
    "BASE_SYSTEM_PROMPT",
    "REVEAL_OVERRIDE",
    "TutorContext",
    "answer_looks_like_full_solution",
    "build_system_prompt",
    "default_conversation_title",
    "history_for_prompt",
    "select_entity_fields",
    "select_note_fields",
    "select_progress_fields",
]

# Imported for readability of the status comparison above.
_SOLVED_STATES = (ProblemStatus.SOLVED.value, ProblemStatus.MASTERED.value)
