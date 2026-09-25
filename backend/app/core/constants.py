"""Shared enums and string constants.

Kept in one module so the enum values stored in PostgreSQL, the values accepted by the
API, and the values the React/iOS clients switch on can never drift apart.
"""

from __future__ import annotations

from enum import StrEnum


class ProblemStatus(StrEnum):
    """Lifecycle of a DSA problem for a single user."""

    NOT_STARTED = "not_started"
    ATTEMPTED = "attempted"
    SOLVED = "solved"
    NEEDS_REVISION = "needs_revision"
    MASTERED = "mastered"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class AttemptOutcome(StrEnum):
    GAVE_UP = "gave_up"
    PARTIAL = "partial"
    SOLVED = "solved"
    SOLVED_WITH_HINT = "solved_with_hint"
    REVISION_SUCCESS = "revision_success"
    REVISION_FAILED = "revision_failed"


class TopicStatus(StrEnum):
    """Shared lifecycle for LLD/HLD topics."""

    NOT_STARTED = "not_started"
    LEARNING = "learning"
    COMPLETED = "completed"
    NEEDS_REVISION = "needs_revision"
    MASTERED = "mastered"


class LLDCategory(StrEnum):
    FUNDAMENTALS = "fundamentals"
    DESIGN_PATTERNS = "design_patterns"
    DESIGN_EXERCISES = "design_exercises"


class HLDCategory(StrEnum):
    FUNDAMENTALS = "fundamentals"
    SYSTEM_DESIGN = "system_design"


class ItemType(StrEnum):
    """Kind of entry inside a daily plan."""

    DSA_NEW = "dsa_new"
    DSA_REVISION = "dsa_revision"
    LLD = "lld"
    HLD = "hld"


class PlanStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class RevisionReason(StrEnum):
    LOW_CONFIDENCE = "low_confidence"
    FAILED_ATTEMPT = "failed_attempt"
    SCHEDULED_REVISION = "scheduled_revision"
    MANUAL = "manual"
    LONG_TIME_SINCE_REVIEW = "long_time_since_review"


class RevisionResult(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


class SessionType(StrEnum):
    DSA = "dsa"
    LLD = "lld"
    HLD = "hld"
    REVISION = "revision"
    MOCK_INTERVIEW = "mock_interview"


class CodeContextType(StrEnum):
    DSA = "dsa"
    LLD = "lld"
    HLD = "hld"


class Language(StrEnum):
    PYTHON = "python"
    JAVA = "java"
    SWIFT = "swift"
    CPP = "cpp"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    GO = "go"
    OTHER = "other"


class AIContextType(StrEnum):
    DSA = "dsa"
    LLD = "lld"
    HLD = "hld"
    GENERAL = "general"


class AIAction(StrEnum):
    EXPLAIN_CONCEPT = "explain_concept"
    GIVE_HINT = "give_hint"
    EXPLAIN_CODE = "explain_code"
    FIND_BUG = "find_bug"
    COMPLEXITY = "complexity"
    ALTERNATIVE_APPROACH = "alternative_approach"
    INTERVIEW_ME = "interview_me"
    GENERAL = "general"


class AIMessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class SyncOperation(StrEnum):
    UPSERT = "upsert"
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"


class SyncEntity(StrEnum):
    """Entities participating in the offline sync protocol."""

    PROBLEM_PROGRESS = "problem_progress"
    PROBLEM_ATTEMPT = "problem_attempt"
    PROBLEM_NOTES = "problem_notes"
    CODE_SNIPPET = "code_snippet"
    REVISION = "revision"
    LLD_PROGRESS = "lld_progress"
    LLD_NOTES = "lld_notes"
    HLD_PROGRESS = "hld_progress"
    HLD_NOTES = "hld_notes"
    STUDY_SESSION = "study_session"
    USER_SETTINGS = "user_settings"


class SyncChangeOperation(StrEnum):
    UPSERT = "upsert"
    DELETE = "delete"


class DeviceType(StrEnum):
    IOS = "ios"
    WEB = "web"
    ANDROID = "android"
    OTHER = "other"


class ActivityKind(StrEnum):
    """Reason a calendar day counts towards a streak."""

    PROBLEM_SOLVED = "problem_solved"
    ATTEMPT_LOGGED = "attempt_logged"
    REVISION_COMPLETED = "revision_completed"
    TOPIC_COMPLETED = "topic_completed"
    STUDY_MINUTES = "study_minutes"
    PLAN_COMPLETED = "plan_completed"


# Values accepted by the `language` column, kept in one place for validation + seeding.
LANGUAGE_VALUES: tuple[str, ...] = tuple(item.value for item in Language)
PROBLEM_STATUS_VALUES: tuple[str, ...] = tuple(item.value for item in ProblemStatus)
ATTEMPT_OUTCOME_VALUES: tuple[str, ...] = tuple(item.value for item in AttemptOutcome)
