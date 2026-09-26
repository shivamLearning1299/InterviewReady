"""Offline synchronisation service.

Implements the push/pull protocol the iOS SwiftData client depends on. Three properties
make it reliable:

**Idempotency.** Every mutation carries a client-generated ``mutation_id``. It is recorded
in ``sync_mutations`` with a unique constraint on ``(user_id, mutation_id)``, so a retried
push returns the original result instead of applying the write twice.

**Optimistic concurrency.** A mutation states the ``base_version`` it last saw. If the row
has moved on, the server returns ``conflict`` together with its **current record**, so the
client can merge rather than silently overwrite a change made on another device.

**Server-authoritative ordering.** The pull cursor is the global ``sync_changes.seq``
identity column, never a device timestamp. Two changes sharing a timestamp still get
distinct, ordered cursor values, and deletions are represented explicitly — neither is
possible with an ``updated_at`` cursor.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.core.config import Settings
from app.core.constants import ProblemStatus, SyncChangeOperation, SyncEntity, SyncOperation
from app.core.logging import get_logger
from app.db.models import StudySession
from app.repositories.activity import ActivityRepository, StudySessionRepository
from app.repositories.dsa import (
    CodeSnippetRepository,
    ProblemAttemptRepository,
    ProblemNotesRepository,
    ProblemProgressRepository,
)
from app.repositories.planning import RevisionRepository
from app.repositories.sync import SyncRepository, UserDeviceRepository
from app.repositories.topics import HLDRepository, LLDRepository
from app.repositories.user import UserSettingsRepository
from app.schemas.sync import (
    SyncChangeRecord,
    SyncMutationPayload,
    SyncMutationResult,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
    SyncStatusResponse,
)
from app.services.study_session_service import MAX_SESSION_MINUTES
from app.utils.datetime_utils import clamp_minutes, utcnow

logger = get_logger(__name__)

#: PostgreSQL SQLSTATE for ``unique_violation``.
_UNIQUE_VIOLATION_SQLSTATE = "23505"


def _is_unique_violation(exc: IntegrityError) -> bool:
    """Whether an ``IntegrityError`` came from a unique constraint.

    Only a unique violation can mean "this mutation was already applied by a concurrent
    request". Every other integrity failure — NOT NULL, CHECK, foreign key — means the
    write did *not* happen, and reporting it as a duplicate would silently lose data.
    """
    orig = getattr(exc, "orig", None)
    sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    if sqlstate == _UNIQUE_VIOLATION_SQLSTATE:
        return True
    # Fall back to the message when the driver does not expose a SQLSTATE.
    return "uniqueviolation" in str(orig or exc).lower().replace(" ", "")


class SyncService:
    def __init__(
        self,
        *,
        sync_repo: SyncRepository,
        device_repo: UserDeviceRepository,
        progress_repo: ProblemProgressRepository,
        attempt_repo: ProblemAttemptRepository,
        notes_repo: ProblemNotesRepository,
        snippet_repo: CodeSnippetRepository,
        revision_repo: RevisionRepository,
        lld_repo: LLDRepository,
        hld_repo: HLDRepository,
        settings_repo: UserSettingsRepository,
        activity_repo: ActivityRepository,
        session_repo: StudySessionRepository,
        settings: Settings,
    ) -> None:
        self._sync = sync_repo
        self._devices = device_repo
        self._progress = progress_repo
        self._attempts = attempt_repo
        self._notes = notes_repo
        self._snippets = snippet_repo
        self._revisions = revision_repo
        self._lld = lld_repo
        self._hld = hld_repo
        self._settings_repo = settings_repo
        self._activity = activity_repo
        self._sessions = session_repo
        self._settings = settings

    # ================================================================== PUSH
    async def push(self, *, user_id: uuid.UUID, payload: SyncPushRequest) -> SyncPushResponse:
        """Apply a batch of queued offline mutations."""
        server_time = utcnow()
        results: list[SyncMutationResult] = []

        # One lookup for every mutation already applied, so a retry of a whole batch is
        # cheap rather than one query per mutation.
        already = await self._sync.get_mutations(
            user_id=user_id, mutation_ids=[m.mutation_id for m in payload.mutations]
        )

        # Ids seen earlier *within this batch*. A device can queue the same change twice,
        # and the ledger row for the first occurrence is only written once its savepoint
        # commits — so without this a batch could apply the same mutation twice.
        applied_in_batch: set[uuid.UUID] = set()

        for mutation in payload.mutations:
            if mutation.mutation_id in already or mutation.mutation_id in applied_in_batch:
                # Replay: return a duplicate result rather than applying again. This is what
                # makes a retried push safe, whether the original was sent in an earlier
                # request or earlier in this same batch.
                stored = already.get(mutation.mutation_id)
                results.append(
                    SyncMutationResult(
                        mutation_id=mutation.mutation_id,
                        status="skipped_duplicate",
                        entity=mutation.entity,
                        record_id=(stored.record_id if stored else None) or mutation.record_id,
                        version=(stored.result or {}).get("version") if stored else None,
                        updated_at=(stored.result or {}).get("updated_at") if stored else None,
                        applied=False,
                        message=(
                            "Mutation was already applied"
                            if stored
                            else "Duplicate mutation in this batch"
                        ),
                    )
                )
                continue

            applied_in_batch.add(mutation.mutation_id)

            try:
                # A savepoint per mutation means one bad record cannot roll back the whole
                # batch, while each mutation's data + change-log write stay atomic together.
                async with self._sync.session.begin_nested():
                    result = await self._apply_mutation(
                        user_id=user_id, mutation=mutation, device_id=payload.device_id
                    )
                    await self._sync.record_mutation(
                        user_id=user_id,
                        mutation_id=mutation.mutation_id,
                        entity=mutation.entity,
                        operation=mutation.operation,
                        record_id=result.record_id,
                        status=result.status,
                        result={
                            "version": result.version,
                            "updated_at": result.updated_at.isoformat()
                            if result.updated_at
                            else None,
                            "record_id": str(result.record_id) if result.record_id else None,
                        },
                        device_id=payload.device_id,
                    )
                results.append(result)

            except IntegrityError as exc:
                if _is_unique_violation(exc):
                    # The only IntegrityError that means "already applied" is a unique
                    # violation on the idempotency ledger, i.e. a concurrent request
                    # committed the same mutation_id between our lookup and this insert.
                    logger.info("Sync mutation conflicted on insert; treating as duplicate")
                    results.append(
                        SyncMutationResult(
                            mutation_id=mutation.mutation_id,
                            status="skipped_duplicate",
                            entity=mutation.entity,
                            record_id=mutation.record_id,
                            applied=False,
                            message="Mutation was applied by a concurrent request",
                        )
                    )
                else:
                    # A NOT NULL / CHECK / FK violation is NOT a duplicate. Reporting it as
                    # one claims the write succeeded and silently discards the user's
                    # change, so it must be surfaced as a rejection instead.
                    logger.warning(
                        "Sync mutation violated a constraint",
                        extra={"entity": mutation.entity, "reason": str(exc)[:200]},
                    )
                    results.append(
                        SyncMutationResult(
                            mutation_id=mutation.mutation_id,
                            status="rejected",
                            entity=mutation.entity,
                            record_id=mutation.record_id,
                            error_code="CONSTRAINT_VIOLATION",
                            message=str(exc.orig)[:300] if exc.orig else str(exc)[:300],
                            applied=False,
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "Sync mutation rejected",
                    extra={"entity": mutation.entity, "reason": str(exc)[:200]},
                )
                results.append(
                    SyncMutationResult(
                        mutation_id=mutation.mutation_id,
                        status="rejected",
                        entity=mutation.entity,
                        record_id=mutation.record_id,
                        error_code=getattr(exc, "code", "MUTATION_REJECTED"),
                        message=getattr(exc, "message", None) or str(exc)[:300],
                        applied=False,
                    )
                )

        # Register/refresh the device and hand back a cursor that covers this batch.
        cursor = await self._sync.latest_cursor(user_id=user_id)
        if payload.device_id:
            await self._devices.upsert(
                user_id=user_id,
                device_identifier=payload.device_id,
                device_type=payload.device_type or "ios",
                cursor=cursor,
            )

        await self._sync.session.commit()

        return SyncPushResponse(
            results=results,
            applied_count=sum(1 for r in results if r.status == "applied"),
            conflict_count=sum(1 for r in results if r.status == "conflict"),
            duplicate_count=sum(1 for r in results if r.status == "skipped_duplicate"),
            rejected_count=sum(1 for r in results if r.status == "rejected"),
            server_cursor=cursor,
            server_time=server_time,
        )

    async def _apply_mutation(
        self,
        *,
        user_id: uuid.UUID,
        mutation: SyncMutationPayload,
        device_id: str | None,
    ) -> SyncMutationResult:
        """Dispatch one mutation to its entity handler."""
        handler = self._handlers().get(mutation.entity)
        if handler is None:
            return SyncMutationResult(
                mutation_id=mutation.mutation_id,
                status="rejected",
                entity=mutation.entity,
                record_id=mutation.record_id,
                error_code="UNSUPPORTED_ENTITY",
                message=f"'{mutation.entity}' cannot be synchronised",
                applied=False,
            )

        if mutation.operation == SyncOperation.DELETE:
            return await self._apply_delete(user_id=user_id, mutation=mutation, device_id=device_id)

        return await handler(user_id=user_id, mutation=mutation, device_id=device_id)

    def _handlers(self) -> dict[str, Callable[..., Awaitable[SyncMutationResult]]]:
        return {
            SyncEntity.PROBLEM_PROGRESS.value: self._upsert_progress,
            SyncEntity.PROBLEM_NOTES.value: self._upsert_notes,
            SyncEntity.CODE_SNIPPET.value: self._upsert_snippet,
            SyncEntity.PROBLEM_ATTEMPT.value: self._upsert_attempt,
            SyncEntity.REVISION.value: self._upsert_revision,
            SyncEntity.LLD_PROGRESS.value: self._upsert_lld_progress,
            SyncEntity.LLD_NOTES.value: self._upsert_lld_notes,
            SyncEntity.HLD_PROGRESS.value: self._upsert_hld_progress,
            SyncEntity.HLD_NOTES.value: self._upsert_hld_notes,
            SyncEntity.USER_SETTINGS.value: self._upsert_settings,
            # Added to close a gap: SyncEntity declared 11 values but only 10 were
            # registered, so a client following the published sync contract and pushing a
            # `study_session` received UNSUPPORTED_ENTITY.
            SyncEntity.STUDY_SESSION.value: self._upsert_study_session,
        }

    # ----------------------------------------------------------- entity handlers
    async def _upsert_progress(
        self, *, user_id: uuid.UUID, mutation: SyncMutationPayload, device_id: str | None
    ) -> SyncMutationResult:
        problem_id = self._require_problem_id(mutation)
        current = await self._progress.get(user_id=user_id, problem_id=problem_id)

        conflict = self._conflict_if_stale(mutation=mutation, current=current)
        if conflict is not None:
            return conflict

        values = self._field_filter(
            mutation.payload,
            allowed={
                "status",
                "attempts",
                "confidence",
                "time_spent_minutes",
                "is_favorite",
                "revision_count",
                "first_attempt_date",
                "solved_date",
                "last_reviewed_date",
                "next_revision_date",
            },
        )

        if (
            current is not None
            and "time_spent_minutes" in values
            and mutation.operation == SyncOperation.UPSERT
        ):
            # Treat the incoming value as authoritative: the offline client already merged
            # its local delta into the total.
            values["time_spent_minutes"] = max(0, int(values["time_spent_minutes"]))

        # ``status`` is NOT NULL on ``user_problem_progress`` and — unlike ``attempts``,
        # ``confidence``, ``time_spent_minutes``, ``revision_count`` and ``is_favorite`` —
        # it has no server default. A client may legitimately push a partial update such as
        # ``{"problem_id": ..., "confidence": 5}``. PostgreSQL validates NOT NULL on the
        # proposed insert row before ``ON CONFLICT`` resolution, so the column has to be
        # present for the statement to be valid at all. It is supplied here and listed in
        # ``preserve_columns`` below, so an existing row keeps its real status.
        #
        # ``_field_filter`` drops ``None``, so an absent key and an explicit ``null`` are
        # equivalent and must both preserve: otherwise a null status would reset a solved
        # problem back to ``not_started``.
        values.setdefault("status", ProblemStatus.NOT_STARTED.value)
        preserve = {"status"} if mutation.payload.get("status") is None else set()

        row = await self._progress.upsert(
            user_id=user_id,
            problem_id=problem_id,
            values=values,
            preserve_columns=preserve,
        )
        await self._record_change(
            user_id=user_id, entity=mutation.entity, record=row, device_id=device_id
        )
        return self._applied(mutation, row)

    async def _upsert_notes(
        self, *, user_id: uuid.UUID, mutation: SyncMutationPayload, device_id: str | None
    ) -> SyncMutationResult:
        problem_id = self._require_problem_id(mutation)
        current = await self._notes.get(user_id=user_id, problem_id=problem_id)

        conflict = self._conflict_if_stale(mutation=mutation, current=current)
        if conflict is not None:
            return conflict

        # These columns are NOT NULL DEFAULT '' in the existing schema.
        values = {
            key: (str(value) if value is not None else "")
            for key, value in self._field_filter(
                mutation.payload,
                allowed={
                    "approach",
                    "notes",
                    "mistakes",
                    "revision_notes",
                    "time_complexity",
                    "space_complexity",
                },
            ).items()
        }

        row = await self._notes.upsert(user_id=user_id, problem_id=problem_id, values=values)
        await self._record_change(
            user_id=user_id, entity=mutation.entity, record=row, device_id=device_id
        )
        return self._applied(mutation, row)

    async def _upsert_attempt(
        self, *, user_id: uuid.UUID, mutation: SyncMutationPayload, device_id: str | None
    ) -> SyncMutationResult:
        problem_id = self._require_problem_id(mutation)
        record_id = mutation.record_id or mutation.mutation_id

        existing = None
        try:
            existing = await self._attempts.get(user_id=user_id, attempt_id=record_id)
        except Exception:
            existing = None

        conflict = self._conflict_if_stale(mutation=mutation, current=existing)
        if conflict is not None:
            return conflict

        values = self._field_filter(
            mutation.payload,
            allowed={
                "started_at",
                "completed_at",
                "duration_minutes",
                "outcome",
                "notes",
            },
        )

        if existing is None:
            # Attempts have no natural key other than their id, so the client's record_id
            # is honoured as the primary key to keep devices in agreement.
            row = await self._attempts.create(
                user_id=user_id, problem_id=problem_id, values={"id": record_id, **values}
            )
        else:
            row = await self._attempts.update(existing, values)

        await self._record_change(
            user_id=user_id, entity=mutation.entity, record=row, device_id=device_id
        )
        return self._applied(mutation, row)

    async def _upsert_snippet(
        self, *, user_id: uuid.UUID, mutation: SyncMutationPayload, device_id: str | None
    ) -> SyncMutationResult:
        record_id = mutation.record_id or mutation.mutation_id

        existing = None
        try:
            existing = await self._snippets.get(user_id=user_id, snippet_id=record_id)
        except Exception:
            existing = None

        conflict = self._conflict_if_stale(mutation=mutation, current=existing)
        if conflict is not None:
            return conflict

        values = self._field_filter(
            mutation.payload,
            allowed={
                "language",
                "code",
                "title",
                "is_primary",
                "context_type",
                "context_id",
                "problem_id",
            },
        )
        # Default the context so a snippet pushed without one is still addressable.
        values.setdefault("context_type", "dsa")
        if "context_id" not in values:
            values["context_id"] = values.get("problem_id") or ""

        if existing is None:
            row = await self._snippets.upsert_by_id(
                user_id=user_id, snippet_id=record_id, values=values
            )
        else:
            row = await self._snippets.update(existing, values)

        await self._record_change(
            user_id=user_id, entity=mutation.entity, record=row, device_id=device_id
        )
        return self._applied(mutation, row)

    async def _upsert_revision(
        self, *, user_id: uuid.UUID, mutation: SyncMutationPayload, device_id: str | None
    ) -> SyncMutationResult:
        record_id = mutation.record_id or mutation.mutation_id
        problem_id = self._require_problem_id(mutation)

        existing = None
        try:
            existing = await self._revisions.get(user_id=user_id, revision_id=record_id)
        except Exception:
            existing = None

        conflict = self._conflict_if_stale(mutation=mutation, current=existing)
        if conflict is not None:
            return conflict

        values = self._field_filter(
            mutation.payload,
            allowed={
                "due_at",
                "reason",
                "priority",
                "completed",
                "completed_at",
                "result",
                "notes",
            },
        )

        if existing is None:
            if "due_at" not in values:
                # A revision with no due date cannot be scheduled; reject instead of
                # writing a row that will never surface.
                return SyncMutationResult(
                    mutation_id=mutation.mutation_id,
                    status="rejected",
                    entity=mutation.entity,
                    record_id=record_id,
                    error_code="MISSING_DUE_AT",
                    message="A revision requires 'due_at'",
                    applied=False,
                )
            values.setdefault("reason", "manual")
            values.setdefault("priority", 3)
            row = await self._revisions.upsert_by_id(
                user_id=user_id,
                revision_id=record_id,
                values={"problem_id": problem_id, **values},
            )
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            existing.version = (existing.version or 1) + 1
            existing.updated_at = utcnow()
            await self._revisions.session.flush()
            row = existing

        await self._record_change(
            user_id=user_id, entity=mutation.entity, record=row, device_id=device_id
        )
        return self._applied(mutation, row)

    async def _upsert_lld_progress(
        self, *, user_id: uuid.UUID, mutation: SyncMutationPayload, device_id: str | None
    ) -> SyncMutationResult:
        return await self._upsert_topic_progress(
            user_id=user_id, mutation=mutation, device_id=device_id, repo=self._lld
        )

    async def _upsert_hld_progress(
        self, *, user_id: uuid.UUID, mutation: SyncMutationPayload, device_id: str | None
    ) -> SyncMutationResult:
        return await self._upsert_topic_progress(
            user_id=user_id, mutation=mutation, device_id=device_id, repo=self._hld
        )

    async def _upsert_topic_progress(
        self, *, user_id: uuid.UUID, mutation: SyncMutationPayload, device_id: str | None, repo: Any
    ) -> SyncMutationResult:
        topic_id = mutation.payload.get("topic_id") or mutation.record_id
        if topic_id is None:
            return SyncMutationResult(
                mutation_id=mutation.mutation_id,
                status="rejected",
                entity=mutation.entity,
                error_code="MISSING_TOPIC_ID",
                message="A topic mutation requires 'topic_id'",
                applied=False,
            )

        topic_uuid = uuid.UUID(str(topic_id))
        current = await repo.get_progress(user_id=user_id, topic_id=topic_uuid)

        conflict = self._conflict_if_stale(mutation=mutation, current=current)
        if conflict is not None:
            return conflict

        values = self._field_filter(
            mutation.payload,
            allowed={
                "status",
                "confidence",
                "last_reviewed_date",
                "completed_at",
                "next_revision_at",
                "next_revision_date",
                "total_time_spent_minutes",
                "revision_count",
            },
        )
        row = await repo.upsert_progress(user_id=user_id, topic_id=topic_uuid, values=values)
        await self._record_change(
            user_id=user_id, entity=mutation.entity, record=row, device_id=device_id
        )
        return self._applied(mutation, row)

    async def _upsert_lld_notes(
        self, *, user_id: uuid.UUID, mutation: SyncMutationPayload, device_id: str | None
    ) -> SyncMutationResult:
        return await self._upsert_topic_notes(
            user_id=user_id, mutation=mutation, device_id=device_id, repo=self._lld
        )

    async def _upsert_hld_notes(
        self, *, user_id: uuid.UUID, mutation: SyncMutationPayload, device_id: str | None
    ) -> SyncMutationResult:
        return await self._upsert_topic_notes(
            user_id=user_id, mutation=mutation, device_id=device_id, repo=self._hld
        )

    async def _upsert_topic_notes(
        self, *, user_id: uuid.UUID, mutation: SyncMutationPayload, device_id: str | None, repo: Any
    ) -> SyncMutationResult:
        topic_id = mutation.payload.get("topic_id") or mutation.record_id
        if topic_id is None:
            return SyncMutationResult(
                mutation_id=mutation.mutation_id,
                status="rejected",
                entity=mutation.entity,
                error_code="MISSING_TOPIC_ID",
                message="A notes mutation requires 'topic_id'",
                applied=False,
            )

        topic_uuid = uuid.UUID(str(topic_id))
        current = await repo.get_notes(user_id=user_id, topic_id=topic_uuid)

        conflict = self._conflict_if_stale(mutation=mutation, current=current)
        if conflict is not None:
            return conflict

        # Pass the payload through minus the routing key: the note tables differ per area.
        values = {
            key: value
            for key, value in mutation.payload.items()
            if key not in {"topic_id", "id", "user_id", "created_at", "version"}
        }
        row = await repo.upsert_notes(user_id=user_id, topic_id=topic_uuid, values=values)
        await self._record_change(
            user_id=user_id, entity=mutation.entity, record=row, device_id=device_id
        )
        return self._applied(mutation, row)

    async def _upsert_study_session(
        self, *, user_id: uuid.UUID, mutation: SyncMutationPayload, device_id: str | None
    ) -> SyncMutationResult:
        """Sync a study session that was created or completed while offline.

        Duration is **server-measured**, exactly as in ``StudySessionService.stop``: the
        client never supplies ``duration_minutes``. A device clock (or a tampered one)
        cannot inflate study time, and a backgrounded app cannot over-report.

        Two shapes are accepted, matching the offline reality:

        * **start** — ``started_at`` with no ``ended_at``: the session is still running.
        * **complete** — ``started_at`` plus ``ended_at``: the elapsed time is derived and
          folded into ``minutes`` / ``duration_minutes``.

        Uniqueness: a session is identified by its own row id (``record_id``), not by a
        business key, because two sessions on the same day are legitimate. A replay with
        the same ``mutation_id`` is already handled by the idempotency ledger before this
        handler runs.
        """
        payload = mutation.payload

        # ---- timezone-aware parsing ------------------------------------------
        started_at = self._parse_datetime(payload.get("started_at")) or utcnow()
        ended_at = self._parse_datetime(payload.get("ended_at"))

        # An end before the start is nonsense; clamp rather than reject, so a device with a
        # skewed clock still drains its queue instead of retrying forever.
        if ended_at is not None and ended_at < started_at:
            ended_at = started_at

        session_type = str(payload.get("session_type") or payload.get("area") or "dsa")

        # ---- existing row? (update path) -------------------------------------
        current: StudySession | None = None
        if mutation.record_id is not None:
            current = await self._sessions.find(user_id=user_id, session_id=mutation.record_id)

        conflict = self._conflict_if_stale(mutation=mutation, current=current)
        if conflict is not None:
            return conflict

        if current is None:
            row = await self._sessions.create(
                user_id=user_id,
                session_type=session_type,
                context_id=payload.get("context_id"),
                context_label=payload.get("context_label"),
                started_at=started_at,
                device_id=device_id,
                # Honour the device-assigned id so the client can correlate its queued row
                # with the server's, matching every other entity in the sync protocol.
                session_id=mutation.record_id,
            )
        else:
            row = current
            row.session_type = session_type
            # Keep the legacy free-text column mirroring `session_type`.
            row.area = session_type
            if payload.get("context_id") is not None:
                row.context_id = payload["context_id"]
            if payload.get("context_label") is not None:
                row.context_label = payload["context_label"]
            row.started_at = started_at
            row.date = started_at

        # ---- close it out when the client says the session ended -------------
        if ended_at is not None:
            elapsed_seconds = (ended_at - row.started_at).total_seconds()
            duration = clamp_minutes(elapsed_seconds / 60, maximum=MAX_SESSION_MINUTES)
            row.ended_at = ended_at
            row.duration_minutes = duration
            # `minutes` is NOT NULL on the pre-existing table and must stay authoritative.
            row.minutes = duration

        if payload.get("note") is not None:
            row.note = payload["note"]

        row.version = (row.version or 1) + 1
        row.updated_at = utcnow()
        await self._sync.session.flush()

        await self._record_change(
            user_id=user_id, entity=mutation.entity, record=row, device_id=device_id
        )
        return self._applied(mutation, row)

    async def _upsert_settings(
        self, *, user_id: uuid.UUID, mutation: SyncMutationPayload, device_id: str | None
    ) -> SyncMutationResult:
        current = await self._settings_repo.get(user_id=user_id)

        conflict = self._conflict_if_stale(mutation=mutation, current=current)
        if conflict is not None:
            return conflict

        values = self._field_filter(
            mutation.payload,
            allowed={
                "daily_dsa_count",
                "daily_revision_count",
                "include_lld_daily",
                "include_hld_daily",
                "timezone",
                "preferred_languages",
                "theme",
                "revision_enabled",
                "ai_auto_reveal_solution",
                "daily_plan_preferences",
                "revision_preferences",
                "ai_preferences",
            },
        )
        row = await self._settings_repo.upsert(user_id=user_id, values=values)
        await self._record_change(
            user_id=user_id, entity=mutation.entity, record=row, device_id=device_id
        )
        return self._applied(mutation, row)

    # ---------------------------------------------------------------- deletes
    async def _apply_delete(
        self, *, user_id: uuid.UUID, mutation: SyncMutationPayload, device_id: str | None
    ) -> SyncMutationResult:
        """Tombstone a record so other devices learn about the removal.

        Deletes are soft everywhere: a hard delete would be invisible to ``/sync/pull``,
        leaving the deleted row alive in every other device's local store forever.
        """
        record_id = mutation.record_id or mutation.mutation_id
        now = utcnow()

        deleted = False
        if mutation.entity == SyncEntity.CODE_SNIPPET.value:
            deleted = await self._snippets.soft_delete_by_id(user_id=user_id, snippet_id=record_id)
        elif mutation.entity in (SyncEntity.PROBLEM_NOTES.value, SyncEntity.PROBLEM_PROGRESS.value):
            problem_id = self._require_problem_id(mutation)
            if mutation.entity == SyncEntity.PROBLEM_NOTES.value:
                note = await self._notes.get(user_id=user_id, problem_id=problem_id)
                if note is not None:
                    note.deleted_at = now
                    note.version = (note.version or 1) + 1
                    await self._notes.session.flush()
                    deleted = True
            else:
                progress = await self._progress.get(user_id=user_id, problem_id=problem_id)
                if progress is not None:
                    progress.deleted_at = now
                    progress.version = (progress.version or 1) + 1
                    await self._progress.session.flush()
                    deleted = True
        elif mutation.entity in (SyncEntity.LLD_NOTES.value, SyncEntity.HLD_NOTES.value):
            repo = self._lld if mutation.entity == SyncEntity.LLD_NOTES.value else self._hld
            topic_id = mutation.payload.get("topic_id") or mutation.record_id
            if topic_id is not None:
                note = await repo.get_notes(user_id=user_id, topic_id=uuid.UUID(str(topic_id)))
                if note is not None:
                    note.deleted_at = now
                    note.version = (note.version or 1) + 1
                    await repo.session.flush()
                    deleted = True
        elif mutation.entity == SyncEntity.REVISION.value:
            try:
                revision = await self._revisions.get(user_id=user_id, revision_id=record_id)
                revision.deleted_at = now
                revision.version = (revision.version or 1) + 1
                await self._revisions.session.flush()
                deleted = True
            except Exception:
                deleted = False

        elif mutation.entity == SyncEntity.STUDY_SESSION.value:
            # Without this branch an offline session deletion was silently dropped: the
            # upsert path succeeded, the delete fell through to ``not deleted`` and was
            # reported as ``skipped_duplicate``, so the row stayed visible forever and the
            # deletion never propagated to the user's other devices.
            #
            # ``find`` rather than ``get`` on purpose: ``get`` raises when the row is
            # absent, which would be indistinguishable from a real failure here. An absent
            # row correctly means "already deleted" and should take the existing
            # ``not deleted`` path below.
            session_row = await self._sessions.find(user_id=user_id, session_id=record_id)
            if session_row is not None:
                session_row.deleted_at = now
                session_row.version = (session_row.version or 1) + 1
                await self._sync.session.flush()
                deleted = True

        if not deleted:
            # Already absent. Report success so the client stops retrying this mutation.
            return SyncMutationResult(
                mutation_id=mutation.mutation_id,
                status="skipped_duplicate",
                entity=mutation.entity,
                record_id=record_id,
                applied=False,
                message="Record was already absent",
            )

        await self._sync.record_change(
            user_id=user_id,
            entity=mutation.entity,
            record_id=record_id,
            operation=SyncChangeOperation.DELETE.value,
            version=None,
            data=None,
            device_id=device_id,
        )

        return SyncMutationResult(
            mutation_id=mutation.mutation_id,
            status="applied",
            entity=mutation.entity,
            record_id=record_id,
            updated_at=now,
            applied=True,
        )

    # ================================================================== PULL
    async def pull(
        self,
        *,
        user_id: uuid.UUID,
        cursor: int,
        limit: int | None = None,
        device_id: str | None = None,
    ) -> SyncPullResponse:
        """Return every change after ``cursor``, oldest first."""
        page_size = min(
            limit or self._settings.sync_pull_page_size,
            self._settings.sync_pull_max_page_size,
        )

        changes = await self._sync.pull_changes(
            user_id=user_id,
            cursor=cursor,
            limit=page_size + 1,  # one extra row to detect "has more" without a count query
        )

        has_more = len(changes) > page_size
        page = changes[:page_size]

        remaining = await self._sync.count_changes_after(user_id=user_id, cursor=cursor)
        next_cursor = page[-1].seq if page else cursor

        if device_id:
            await self._devices.update_cursor(
                user_id=user_id, device_identifier=device_id, cursor=next_cursor
            )
            await self._sync.session.commit()

        return SyncPullResponse(
            changes=[
                SyncChangeRecord(
                    seq=change.seq,
                    entity=change.entity,
                    record_id=change.record_id,
                    operation=change.operation,  # type: ignore[arg-type]
                    version=change.version,
                    updated_at=change.created_at,
                    data=change.data,
                )
                for change in page
            ],
            next_cursor=next_cursor,
            has_more=has_more,
            server_time=utcnow(),
            remaining=max(remaining - len(page), 0),
        )

    # ================================================================== STATUS
    async def status(
        self, *, user_id: uuid.UUID, device_id: str | None = None
    ) -> SyncStatusResponse:
        cursor = await self._sync.latest_cursor(user_id=user_id)
        last_change = await self._sync.last_change_at(user_id=user_id)

        last_sync = None
        if device_id:
            device = await self._devices.get(user_id=user_id, device_identifier=device_id)
            last_sync = device.last_sync_at if device else None

        return SyncStatusResponse(
            server_cursor=cursor,
            last_change_at=last_change,
            last_sync_at=last_sync,
            pending_changes=0,
            server_time=utcnow(),
        )

    # ================================================================== helpers
    async def _record_change(
        self,
        *,
        user_id: uuid.UUID,
        entity: str,
        record: Any,
        device_id: str | None,
    ) -> None:
        """Append the change-log entry for a write, in the same transaction."""
        snapshot = self._serialise(record)
        await self._sync.record_change(
            user_id=user_id,
            entity=entity,
            record_id=uuid.UUID(str(record.id)),
            operation=SyncChangeOperation.UPSERT.value,
            version=getattr(record, "version", None),
            data=snapshot,
            device_id=device_id,
        )

    @staticmethod
    def _serialise(record: Any) -> dict[str, Any]:
        """JSON-safe snapshot of a record for the pull stream.

        Datetimes become ISO strings and ``UUID``s become strings so the JSONB payload is
        directly usable by the client's decoder.
        """
        data: dict[str, Any] = {}
        for column in record.__table__.columns:
            value = getattr(record, column.key, None)
            if isinstance(value, datetime):
                data[column.key] = value.isoformat()
            elif isinstance(value, uuid.UUID):
                data[column.key] = str(value)
            else:
                data[column.key] = value
        return data

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        """Parse a client-supplied ISO-8601 instant, tolerating a naive value.

        Offline clients send whatever their encoder produced. ``datetime.fromisoformat``
        handles both ``Z`` and ``+00:00`` forms on Python 3.11+; a naive value is pinned to
        UTC rather than rejected, and an unparseable one returns ``None`` so the caller can
        fall back to server time instead of failing the whole mutation.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                return None
        if parsed.tzinfo is None:
            from app.utils.datetime_utils import UTC_TZ

            parsed = parsed.replace(tzinfo=UTC_TZ)
        return parsed

    @staticmethod
    def _field_filter(payload: dict[str, Any], *, allowed: set[str]) -> dict[str, Any]:
        """Keep only recognised, non-None fields.

        An unknown key would otherwise raise on the model and turn a whole mutation into a
        rejection; silently ignoring it lets a newer client push a field an older server
        does not know yet.
        """
        return {
            key: value for key, value in payload.items() if key in allowed and value is not None
        }

    @staticmethod
    def _require_problem_id(mutation: SyncMutationPayload) -> str:
        problem_id = mutation.payload.get("problem_id")
        if problem_id is None and mutation.record_id is not None:
            # Progress and notes are keyed by problem, not by their own row id, so a client
            # that only sends record_id is interpreted as referring to a problem.
            problem_id = str(mutation.record_id)
        if problem_id is None:
            raise ValueError("This mutation requires a 'problem_id'")
        return str(problem_id)

    @staticmethod
    def _conflict_if_stale(
        *, mutation: SyncMutationPayload, current: Any | None
    ) -> SyncMutationResult | None:
        """Detect a lost-update situation.

        Returns a ``conflict`` result carrying the server's current record when the client's
        ``base_version`` is behind, or when the client believes a row exists that does not.
        Returns ``None`` when the write may proceed.
        """
        if mutation.base_version is None:
            # No expectation stated: an insert, or a client that does not track versions.
            return None

        server_version = getattr(current, "version", None) if current is not None else None

        if current is None:
            return SyncMutationResult(
                mutation_id=mutation.mutation_id,
                status="conflict",
                entity=mutation.entity,
                record_id=mutation.record_id,
                version=None,
                server_record=None,
                error_code="RECORD_MISSING",
                message="The client expected an existing record but none was found",
                applied=False,
            )

        if server_version is not None and server_version != mutation.base_version:
            return SyncMutationResult(
                mutation_id=mutation.mutation_id,
                status="conflict",
                entity=mutation.entity,
                record_id=uuid.UUID(str(current.id)),
                version=server_version,
                updated_at=getattr(current, "updated_at", None),
                server_record=SyncService._serialise(current),
                error_code="VERSION_CONFLICT",
                message=(
                    f"Server version is {server_version}, client based on "
                    f"{mutation.base_version}. Merge and retry."
                ),
                applied=False,
            )

        return None

    @staticmethod
    def _applied(mutation: SyncMutationPayload, record: Any) -> SyncMutationResult:
        return SyncMutationResult(
            mutation_id=mutation.mutation_id,
            status="applied",
            entity=mutation.entity,
            record_id=uuid.UUID(str(record.id)),
            version=getattr(record, "version", None),
            updated_at=getattr(record, "updated_at", None),
            applied=True,
        )


__all__ = ["SyncService"]
