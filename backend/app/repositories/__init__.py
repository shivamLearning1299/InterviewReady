"""Repository layer: all SQL lives here.

Rules enforced throughout this package:

* **Every personal-data query takes ``user_id`` explicitly and filters on it.** There is no
  "fetch by id" method on a user-owned table that omits the owner, so a route cannot
  accidentally read another user's row.
* **No N+1.** Listing endpoints join or eager-load everything they serialise; the stats
  repository aggregates in SQL rather than looping.
* **No commits.** Repositories flush so callers get generated values, but transaction
  boundaries belong to the service layer, which is what makes the multi-row operations
  (solve a problem + schedule a revision + record the attempt) atomic.
"""

from app.repositories.activity import ActivityRepository, StudySessionRepository
from app.repositories.ai import AIConversationRepository, AIRateLimitRepository
from app.repositories.base import BaseRepository
from app.repositories.catalog import DSAProblemRepository
from app.repositories.devices import UserDeviceRepository
from app.repositories.dsa import (
    CodeSnippetRepository,
    ProblemAttemptRepository,
    ProblemNotesRepository,
    ProblemProgressRepository,
)
from app.repositories.planning import DailyPlanRepository, RevisionRepository
from app.repositories.stats import StatsRepository
from app.repositories.sync import SyncRepository
from app.repositories.topics import (
    HLDRepository,
    LLDRepository,
    TopicCommonRepository,
)
from app.repositories.user import UserSettingsRepository

__all__ = [
    "AIConversationRepository",
    "AIRateLimitRepository",
    "ActivityRepository",
    "BaseRepository",
    "CodeSnippetRepository",
    "DSAProblemRepository",
    "DailyPlanRepository",
    "HLDRepository",
    "LLDRepository",
    "ProblemAttemptRepository",
    "ProblemNotesRepository",
    "ProblemProgressRepository",
    "RevisionRepository",
    "StatsRepository",
    "StudySessionRepository",
    "SyncRepository",
    "TopicCommonRepository",
    "UserDeviceRepository",
    "UserSettingsRepository",
]
