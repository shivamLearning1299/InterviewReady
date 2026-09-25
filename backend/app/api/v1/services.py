"""Service wiring for the API layer.

Services are constructed per request from the request-scoped database session. They are
deliberately **not** cached on ``app.state``: a cached service would hold a cached
``AsyncSession``, and a session must never outlive the request that owns it.

Construction is cheap — the services themselves are thin — while the things that *are*
expensive to build (the SQLAlchemy engine, the cached JWKS, the AI provider) live on
``app.state`` or in the engine module.
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.repositories.activity import ActivityRepository, StudySessionRepository
from app.repositories.ai import (
    AIConversationRepository,
    AIMessageRepository,
    AIRateLimitRepository,
)
from app.repositories.catalog import DSAProblemRepository
from app.repositories.dsa import (
    CodeSnippetRepository,
    ProblemAttemptRepository,
    ProblemNotesRepository,
    ProblemProgressRepository,
)
from app.repositories.planning import DailyPlanRepository, RevisionRepository
from app.repositories.stats import StatsRepository
from app.repositories.sync import SyncRepository, UserDeviceRepository
from app.repositories.topics import HLDRepository, LLDRepository
from app.repositories.user import UserSettingsRepository
from app.services.activity_service import ActivityService
from app.services.ai_tutor_service import AITutorService
from app.services.daily_plan_scheduler import DailyPlanScheduler
from app.services.daily_plan_service import DailyPlanService
from app.services.dsa_service import (
    AttemptService,
    CodeSnippetService,
    NotesService,
    ProgressService,
)
from app.services.revision_policy import RevisionPolicy
from app.services.revision_service import RevisionService
from app.services.stats_service import StatsService
from app.services.streak_service import StreakService
from app.services.study_session_service import StudySessionService
from app.services.sync_service import SyncService
from app.services.topic_service import HLDService, LLDService
from app.services.user_service import ExportService, SettingsService


class Services:
    """Container holding every service for one request.

    A single object keeps route signatures short (``services: ServicesDep``) while still
    making the dependency on a session explicit.
    """

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

        # ------------------------------------------------------------ repositories
        self.catalog = DSAProblemRepository(session)
        self.progress_repo = ProblemProgressRepository(session)
        self.attempt_repo = ProblemAttemptRepository(session)
        self.notes_repo = ProblemNotesRepository(session)
        self.snippet_repo = CodeSnippetRepository(session)
        self.plan_repo = DailyPlanRepository(session)
        self.revision_repo = RevisionRepository(session)
        self.activity_repo = ActivityRepository(session)
        self.study_session_repo = StudySessionRepository(session)
        self.stats_repo = StatsRepository(session)
        self.sync_repo = SyncRepository(session)
        self.device_repo = UserDeviceRepository(session)
        self.settings_repo = UserSettingsRepository(session, settings)
        self.lld_repo = LLDRepository(session)
        self.hld_repo = HLDRepository(session)
        self.ai_conversation_repo = AIConversationRepository(session)
        self.ai_message_repo = AIMessageRepository(session)
        self.ai_rate_limit_repo = AIRateLimitRepository(session)

        # --------------------------------------------------------------- policies
        self.revision_policy = RevisionPolicy(settings)
        self.scheduler = DailyPlanScheduler(settings, self.revision_policy)

        # --------------------------------------------------------------- services
        self.activity = ActivityService(activity_repo=self.activity_repo, settings=settings)
        self.streaks = StreakService(
            activity_repo=self.activity_repo,
            activity_service=self.activity,
            settings=settings,
        )
        self.daily_plans = DailyPlanService(
            plan_repo=self.plan_repo,
            catalog_repo=self.catalog,
            progress_repo=self.progress_repo,
            revision_repo=self.revision_repo,
            settings=settings,
            scheduler=self.scheduler,
            streak_service=self.streaks,
            activity_repo=self.activity_repo,
        )
        self.progress = ProgressService(
            progress_repo=self.progress_repo,
            catalog_repo=self.catalog,
            revision_repo=self.revision_repo,
            plan_repo=self.plan_repo,
            activity_service=self.activity,
            revision_policy=self.revision_policy,
            settings=settings,
        )
        self.attempts = AttemptService(
            attempt_repo=self.attempt_repo,
            progress_repo=self.progress_repo,
            catalog_repo=self.catalog,
            revision_repo=self.revision_repo,
            activity_service=self.activity,
            revision_policy=self.revision_policy,
        )
        self.notes = NotesService(notes_repo=self.notes_repo, catalog_repo=self.catalog)
        self.code = CodeSnippetService(snippet_repo=self.snippet_repo, catalog_repo=self.catalog)
        self.revisions = RevisionService(
            revision_repo=self.revision_repo,
            progress_repo=self.progress_repo,
            catalog_repo=self.catalog,
            activity_service=self.activity,
            revision_policy=self.revision_policy,
            settings=settings,
        )
        self.lld = LLDService(
            repo=self.lld_repo,
            snippet_repo=self.snippet_repo,
            activity_service=self.activity,
            revision_policy=self.revision_policy,
            settings=settings,
        )
        self.hld = HLDService(
            repo=self.hld_repo,
            snippet_repo=self.snippet_repo,
            activity_service=self.activity,
            revision_policy=self.revision_policy,
            settings=settings,
        )
        self.study_sessions = StudySessionService(
            session_repo=self.study_session_repo,
            activity_repo=self.activity_repo,
            progress_repo=self.progress_repo,
            activity_service=self.activity,
            settings=settings,
        )
        self.stats = StatsService(
            stats_repo=self.stats_repo,
            activity_repo=self.activity_repo,
            activity_service=self.activity,
            streak_service=self.streaks,
            lld_repo=self.lld_repo,
            hld_repo=self.hld_repo,
            settings=settings,
        )
        self.sync = SyncService(
            sync_repo=self.sync_repo,
            device_repo=self.device_repo,
            progress_repo=self.progress_repo,
            attempt_repo=self.attempt_repo,
            notes_repo=self.notes_repo,
            snippet_repo=self.snippet_repo,
            revision_repo=self.revision_repo,
            lld_repo=self.lld_repo,
            hld_repo=self.hld_repo,
            settings_repo=self.settings_repo,
            activity_repo=self.activity_repo,
            settings=settings,
        )
        self.settings_service = SettingsService(settings_repo=self.settings_repo, settings=settings)
        self.ai = AITutorService(
            conversation_repo=self.ai_conversation_repo,
            message_repo=self.ai_message_repo,
            rate_limit_repo=self.ai_rate_limit_repo,
            catalog_repo=self.catalog,
            progress_repo=self.progress_repo,
            notes_repo=self.notes_repo,
            snippet_repo=self.snippet_repo,
            lld_repo=self.lld_repo,
            hld_repo=self.hld_repo,
            settings=settings,
            # Reuse the process-wide provider (its HTTP client and connection pool are
            # expensive to rebuild per request) when startup managed to create one.
            provider=None,
        )
        self.export = ExportService(
            progress_repo=self.progress_repo,
            attempt_repo=self.attempt_repo,
            notes_repo=self.notes_repo,
            snippet_repo=self.snippet_repo,
            revision_repo=self.revision_repo,
            plan_repo=self.plan_repo,
            lld_repo=self.lld_repo,
            hld_repo=self.hld_repo,
            activity_repo=self.activity_repo,
            conversation_repo=self.ai_conversation_repo,
            settings_repo=self.settings_repo,
            settings=settings,
        )


def get_services(request: Request, session: AsyncSession, settings: Settings) -> Services:
    """Build the container, reusing the app-level AI provider when present."""
    services = Services(session, settings)

    provider = getattr(request.app.state, "ai_provider", None)
    if provider is not None:
        services.ai._provider = provider

    return services


__all__ = ["Services", "get_services"]
