"""AI conversation storage and per-user rate-limit counters."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConversationNotFoundError
from app.db.models import AIConversation, AIMessage, AIRateLimitCounter
from app.utils.datetime_utils import utcnow


class AIConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, *, user_id: uuid.UUID, conversation_id: uuid.UUID) -> AIConversation:
        conversation = await self.session.scalar(
            select(AIConversation).where(
                AIConversation.id == conversation_id,
                AIConversation.user_id == user_id,
                AIConversation.deleted_at.is_(None),
            )
        )
        if conversation is None:
            raise ConversationNotFoundError()
        return conversation

    async def get_optional(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> AIConversation | None:
        return await self.session.scalar(
            select(AIConversation).where(
                AIConversation.id == conversation_id,
                AIConversation.user_id == user_id,
                AIConversation.deleted_at.is_(None),
            )
        )

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        context_type: str,
        context_id: uuid.UUID | None,
        context_label: str | None,
        title: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> AIConversation:
        conversation = AIConversation(
            user_id=user_id,
            context_type=context_type,
            context_id=context_id,
            context_label=context_label,
            title=title,
            provider=provider,
            model=model,
        )
        self.session.add(conversation)
        await self.session.flush()
        return conversation

    async def touch(
        self, conversation: AIConversation, *, message_count_delta: int = 1
    ) -> AIConversation:
        conversation.message_count = (conversation.message_count or 0) + message_count_delta
        conversation.last_message_at = utcnow()
        conversation.version = (conversation.version or 1) + 1
        conversation.updated_at = utcnow()
        await self.session.flush()
        return conversation

    async def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        offset: int,
        context_type: str | None = None,
    ) -> tuple[list[tuple[AIConversation, str | None]], int]:
        """Conversations plus a short preview of the latest message.

        The preview is fetched with a correlated subquery rather than a second query per
        conversation.
        """
        base = select(AIConversation).where(
            AIConversation.user_id == user_id, AIConversation.deleted_at.is_(None)
        )
        if context_type:
            base = base.where(AIConversation.context_type == context_type)

        total = int(
            await self.session.scalar(
                select(func.count()).select_from(base.order_by(None).subquery())
            )
            or 0
        )

        preview = (
            select(func.substr(AIMessage.content, 1, 160))
            .where(
                AIMessage.conversation_id == AIConversation.id,
                AIMessage.role == "assistant",
                AIMessage.deleted_at.is_(None),
            )
            .order_by(AIMessage.created_at.desc())
            .limit(1)
            .correlate(AIConversation)
            .scalar_subquery()
        )

        stmt = (
            select(AIConversation, preview)
            .where(
                AIConversation.user_id == user_id,
                AIConversation.deleted_at.is_(None),
            )
        )
        if context_type:
            stmt = stmt.where(AIConversation.context_type == context_type)

        stmt = (
            stmt.order_by(AIConversation.last_message_at.desc().nullslast(), AIConversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = [(row[0], row[1]) for row in (await self.session.execute(stmt)).all()]
        return rows, total

    async def soft_delete(self, conversation: AIConversation) -> None:
        """Tombstone the conversation and its messages.

        Messages are tombstoned too rather than cascaded away, because an offline client
        needs to learn that the thread was deleted when it next pulls.
        """
        now = utcnow()
        conversation.deleted_at = now
        conversation.version = (conversation.version or 1) + 1
        conversation.updated_at = now

        await self.session.execute(
            update(AIMessage)
            .where(AIMessage.conversation_id == conversation.id)
            .values(deleted_at=now, version=AIMessage.version + 1, updated_at=func.now())
        )
        await self.session.flush()

    async def count_for_user(self, *, user_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).where(
                    AIConversation.user_id == user_id, AIConversation.deleted_at.is_(None)
                )
            )
            or 0
        )


class AIMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        action: str | None = None,
        selected_code: str | None = None,
        snippet_id: uuid.UUID | None = None,
        provider: str | None = None,
        model: str | None = None,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> AIMessage:
        message = AIMessage(
            user_id=user_id,
            conversation_id=conversation_id,
            role=role,
            content=content,
            action=action,
            selected_code=selected_code,
            snippet_id=snippet_id,
            provider=provider,
            model=model,
            usage=usage,
            error=error,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def list_for_conversation(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID, limit: int = 200
    ) -> list[AIMessage]:
        stmt = (
            select(AIMessage)
            .where(
                AIMessage.user_id == user_id,
                AIMessage.conversation_id == conversation_id,
                AIMessage.deleted_at.is_(None),
            )
            .order_by(AIMessage.created_at.asc())
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def recent_history(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID, limit: int
    ) -> list[AIMessage]:
        """The most recent turns, returned oldest-first for prompt assembly.

        Only a bounded tail is loaded so the prompt sent to the model stays small — the
        requirement explicitly forbids forwarding the user's whole history.
        """
        stmt = (
            select(AIMessage)
            .where(
                AIMessage.user_id == user_id,
                AIMessage.conversation_id == conversation_id,
                AIMessage.deleted_at.is_(None),
                AIMessage.error.is_(None),
            )
            .order_by(AIMessage.created_at.desc())
            .limit(limit)
        )
        rows = list((await self.session.scalars(stmt)).all())
        return list(reversed(rows))

    async def count_for_conversation(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).where(
                    AIMessage.user_id == user_id,
                    AIMessage.conversation_id == conversation_id,
                    AIMessage.deleted_at.is_(None),
                )
            )
            or 0
        )


class AIRateLimitRepository:
    """Fixed-window counter backing ``429`` responses on the AI endpoints."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _window_start(now: datetime, window_seconds: int = 3600) -> datetime:
        """Floor ``now`` to the start of its fixed window."""
        epoch = int(now.timestamp())
        return datetime.fromtimestamp(epoch - (epoch % window_seconds), tz=now.tzinfo)

    async def check_and_increment(
        self, *, user_id: uuid.UUID, limit: int, window_seconds: int = 3600
    ) -> tuple[bool, int, datetime]:
        """Atomically consume one unit of quota.

        Returns ``(allowed, current_count, window_reset_at)``. The increment happens in a
        single statement with a conditional set, so concurrent requests cannot both read
        a stale count and slip past the limit.
        """
        now = utcnow()
        window_start = self._window_start(now, window_seconds)
        reset_at = window_start + timedelta(seconds=window_seconds)

        stmt = (
            pg_insert(AIRateLimitCounter)
            .values(user_id=user_id, window_start=window_start, request_count=1)
            .on_conflict_do_update(
                index_elements=["user_id", "window_start"],
                set_={
                    "request_count": AIRateLimitCounter.request_count + 1,
                    "updated_at": func.now(),
                },
                # Only increment while under the limit: once at the ceiling, the update is
                # skipped and the stored count stays put.
                where=AIRateLimitCounter.request_count < limit,
            )
            .returning(AIRateLimitCounter.request_count)
        )

        new_count = (await self.session.execute(stmt)).scalar_one_or_none()

        if new_count is None:
            # Row exists and is at/over the limit — read the current value for the error body.
            current = await self.session.scalar(
                select(AIRateLimitCounter.request_count).where(
                    AIRateLimitCounter.user_id == user_id,
                    AIRateLimitCounter.window_start == window_start,
                )
            )
            return False, int(current or limit), reset_at

        return True, int(new_count), reset_at

    async def peek(
        self, *, user_id: uuid.UUID, window_seconds: int = 3600
    ) -> int:
        window_start = self._window_start(utcnow(), window_seconds)
        value = await self.session.scalar(
            select(AIRateLimitCounter.request_count).where(
                AIRateLimitCounter.user_id == user_id,
                AIRateLimitCounter.window_start == window_start,
            )
        )
        return int(value or 0)

    async def reset(self, *, user_id: uuid.UUID) -> None:
        """Clear this user's counter for the current window only."""
        window_start = self._window_start(utcnow())
        await self.session.execute(
            update(AIRateLimitCounter)
            .where(
                AIRateLimitCounter.user_id == user_id,
                AIRateLimitCounter.window_start == window_start,
            )
            .values(request_count=0, updated_at=func.now())
        )
