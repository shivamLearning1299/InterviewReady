"""Study session service.

The critical rule here is that **elapsed time is measured on the server**. The client never
sends an accumulated duration, because a backgrounded iOS app, a paused timer or a tampered
clock would all produce numbers that do not reflect real study time.

The legacy ``study_sessions`` columns (``date``, ``minutes``, ``area``) are kept populated by
the repository so existing readers keep working.
"""

from __future__ import annotations

import uuid

from app.core.config import Settings
from app.core.exceptions import StudySessionConflictError
from app.core.logging import get_logger
from app.db.models import StudySession
from app.repositories.activity import ActivityRepository, StudySessionRepository
from app.repositories.dsa import ProblemProgressRepository
from app.schemas.study import (
    StudySessionResponse,
    StudySessionStartRequest,
    StudySessionStopRequest,
)
from app.services.activity_service import ActivityService
from app.utils.datetime_utils import clamp_minutes, resolve_timezone, today_local, utcnow

logger = get_logger(__name__)

#: Sessions longer than this are almost certainly a forgotten timer. Cap rather than reject
#: so the honest part of the study time is still recorded.
MAX_SESSION_MINUTES = 8 * 60


class StudySessionService:
    def __init__(
        self,
        *,
        session_repo: StudySessionRepository,
        activity_repo: ActivityRepository,
        progress_repo: ProblemProgressRepository,
        activity_service: ActivityService,
        settings: Settings,
    ) -> None:
        self._sessions = session_repo
        self._activity_repo = activity_repo
        self._progress = progress_repo
        self._activity = activity_service
        self._settings = settings

    # ---------------------------------------------------------------------- start
    async def start(
        self,
        *,
        user_id: uuid.UUID,
        payload: StudySessionStartRequest,
        timezone: str | None = None,
    ) -> StudySessionResponse:
        """Open a session.

        If a session is already running, that one is returned instead of creating a second —
        a double-tap on "start" (or a retried offline request) must not spawn two timers.
        The database also enforces this with a partial unique index, so the guarantee holds
        even if two requests arrive at once.
        """
        running = await self._sessions.get_running(user_id=user_id)
        if running is not None:
            logger.info("Study session already running; returning it")
            return self._to_response(running)

        started_at = payload.started_at
        if started_at is not None:
            now = utcnow()
            if started_at.tzinfo is None:
                from app.utils.datetime_utils import UTC_TZ

                started_at = started_at.replace(tzinfo=UTC_TZ)
            # An offline client may report a start time in the past, but never in the future:
            # a future timestamp would produce a negative duration on stop.
            if started_at > now:
                started_at = now

        session = await self._sessions.create(
            user_id=user_id,
            session_type=payload.session_type.value,
            context_id=str(payload.context_id) if payload.context_id else None,
            context_label=payload.context_label,
            started_at=started_at,
            device_id=payload.device_id,
        )
        await self._sessions.session.commit()

        logger.info(
            "Study session started",
            extra={"session_type": session.session_type, "session_id": str(session.id)},
        )
        return self._to_response(session)

    # ----------------------------------------------------------------------- stop
    async def stop(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        payload: StudySessionStopRequest,
        timezone: str | None = None,
    ) -> StudySessionResponse:
        """Close a session and record the server-measured duration.

        Idempotent: stopping an already-stopped session returns the stored result with the
        original duration rather than recomputing it from the current time (which would
        silently inflate the total on every retry).
        """
        session = await self._sessions.get(user_id=user_id, session_id=session_id)

        if session.ended_at is not None:
            logger.info("Study session already stopped; returning stored duration")
            return self._to_response(session)

        now = utcnow()
        ended_at = payload.ended_at or now

        if ended_at.tzinfo is None:
            from app.utils.datetime_utils import UTC_TZ

            ended_at = ended_at.replace(tzinfo=UTC_TZ)

        # Never trust a client end time beyond "now", and never allow an end before the start.
        if ended_at > now:
            ended_at = now
        if ended_at < session.started_at:
            ended_at = session.started_at

        elapsed_seconds = (ended_at - session.started_at).total_seconds()
        duration = clamp_minutes(elapsed_seconds / 60, maximum=MAX_SESSION_MINUTES)

        updated = await self._sessions.stop(
            session, ended_at=ended_at, duration_minutes=duration, note=payload.note
        )

        # Fold the measured time into the linked problem and the activity ledger.
        if payload.update_progress and updated.context_id and updated.session_type == "dsa":
            try:
                problem_id = str(updated.context_id)
                existing = await self._progress.get(user_id=user_id, problem_id=problem_id)
                if existing is not None:
                    await self._progress.increment_time(
                        user_id=user_id, problem_id=problem_id, minutes=duration
                    )
            except Exception:
                logger.info("Could not attribute study time to a problem")

        if duration > 0:
            tz = resolve_timezone(timezone or self._settings.default_timezone)
            # Attribute the time to the day the session *started*, so a session that runs
            # past midnight is not split across two days.
            activity_date = today_local(tz) if session.started_at.date() == today_local(tz) else None
            await self._activity.record(
                user_id=user_id,
                timezone=tz,
                activity_date=activity_date,
                activity_count=1,
                study_minutes=duration,
            )

        await self._sessions.session.commit()

        logger.info(
            "Study session stopped",
            extra={"session_id": str(session_id), "duration_minutes": duration},
        )
        return self._to_response(updated)

    # ----------------------------------------------------------------------- read
    async def list_sessions(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        offset: int,
        session_type: str | None = None,
        context_id: uuid.UUID | None = None,
        started_after=None,
        started_before=None,
        running_only: bool = False,
    ) -> tuple[list[StudySessionResponse], int]:
        sessions, total = await self._sessions.list_for_user(
            user_id=user_id,
            limit=limit,
            offset=offset,
            session_type=session_type,
            context_id=str(context_id) if context_id else None,
            started_after=started_after,
            started_before=started_before,
            running_only=running_only,
        )
        return [self._to_response(session) for session in sessions], total

    async def get_running(self, *, user_id: uuid.UUID) -> StudySessionResponse | None:
        session = await self._sessions.get_running(user_id=user_id)
        return self._to_response(session) if session else None

    # -------------------------------------------------------------------- mapping
    @staticmethod
    def _to_response(session: StudySession) -> StudySessionResponse:
        return StudySessionResponse(
            id=session.id,
            user_id=session.user_id,
            created_at=session.created_at,
            updated_at=session.updated_at,
            version=session.version,
            session_type=session.session_type,
            context_id=session.context_id,
            context_label=session.context_label,
            started_at=session.started_at,
            ended_at=session.ended_at,
            duration_minutes=session.duration_minutes if session.duration_minutes is not None else session.minutes,
            paused_minutes=0,
            note=session.note,
        )


__all__ = ["MAX_SESSION_MINUTES", "StudySessionConflictError", "StudySessionService"]
