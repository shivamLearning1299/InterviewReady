"""ORM model registry.

Importing this package is what makes ``Base.metadata`` complete. Alembic's autogenerate
and the test-suite's ``create_all`` both rely on that, so every model module must be
imported here — never import model classes directly from their modules elsewhere.
"""

from app.db.models.activity import StudySession, UserActivityDay
from app.db.models.ai import AIConversation, AIMessage, AIRateLimitCounter
from app.db.models.catalog import DSAProblem, DSATopic
from app.db.models.dsa import CodeSnippet, ProblemAttempt, ProblemNote, UserProblemProgress
from app.db.models.hld import HLDNote, HLDProgress, HLDTopic
from app.db.models.lld import LLDNote, LLDProgress, LLDTopic
from app.db.models.planning import DailyPlan, DailyPlanItem, RevisionQueueItem
from app.db.models.settings import UserSettings
from app.db.models.sync import SyncChange, SyncMutation, UserDevice

# Grouped by domain rather than alphabetised: the grouping is what makes the file
# readable, and it is a deliberate ordering choice. ruff's RUF022 is disabled for this
# line in pyproject's per-file ignores.
__all__ = [
    # catalog
    "DSAProblem",
    "DSATopic",
    "LLDTopic",
    "HLDTopic",
    # dsa user data
    "UserProblemProgress",
    "ProblemAttempt",
    "ProblemNote",
    "CodeSnippet",
    # lld / hld user data
    "LLDProgress",
    "LLDNote",
    "HLDProgress",
    "HLDNote",
    # planning
    "DailyPlan",
    "DailyPlanItem",
    "RevisionQueueItem",
    # activity
    "StudySession",
    "UserActivityDay",
    # ai
    "AIConversation",
    "AIMessage",
    "AIRateLimitCounter",
    # sync
    "SyncChange",
    "SyncMutation",
    "UserDevice",
    # settings
    "UserSettings",
]
