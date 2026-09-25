"""AI tutor service.

Assembles minimal context, applies the pedagogy guardrails, calls the configured provider
through the ``AIProvider`` abstraction, and persists the conversation.

Context loading is deliberately narrow and per-``context_type``:

* ``dsa``     — the problem's metadata, the user's own notes and progress, plus selected
                code when the action needs it;
* ``lld``/``hld`` — the topic plus the user's notes and relevant saved code;
* ``general`` — nothing but the conversation.

Nothing else is read, so the user's notes, code, attempt history and progress for
*other* problems never reach the model.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.core.config import Settings
from app.core.constants import AIAction, AIContextType, CodeContextType
from app.core.exceptions import (
    AIConfigurationError,
    ForbiddenError,
    RateLimitedError,
    ValidationError,
)
from app.core.logging import get_logger
from app.repositories.ai import (
    AIConversationRepository,
    AIMessageRepository,
    AIRateLimitRepository,
)
from app.repositories.catalog import DSAProblemRepository
from app.repositories.dsa import (
    CodeSnippetRepository,
    ProblemNotesRepository,
    ProblemProgressRepository,
)
from app.repositories.topics import HLDRepository, LLDRepository
from app.schemas.ai import (
    AIChatRequest,
    AIChatResponse,
    AIConversationDetail,
    AIConversationSummary,
    AIMessageResponse,
)
from app.services.ai.factory import build_provider
from app.services.ai.prompts import (
    TutorContext,
    build_system_prompt,
    default_conversation_title,
    history_for_prompt,
    select_entity_fields,
    select_note_fields,
    select_progress_fields,
)
from app.services.ai.provider import AIProvider, ChatMessage

logger = get_logger(__name__)

#: Actions for which the user's saved code should be attached automatically.
_CODE_ACTIONS = {
    AIAction.EXPLAIN_CODE.value,
    AIAction.FIND_BUG.value,
    AIAction.COMPLEXITY.value,
}

MAX_CODE_CHARS = 20_000


class AITutorService:
    def __init__(
        self,
        *,
        conversation_repo: AIConversationRepository,
        message_repo: AIMessageRepository,
        rate_limit_repo: AIRateLimitRepository,
        catalog_repo: DSAProblemRepository,
        progress_repo: ProblemProgressRepository,
        notes_repo: ProblemNotesRepository,
        snippet_repo: CodeSnippetRepository,
        lld_repo: LLDRepository,
        hld_repo: HLDRepository,
        settings: Settings,
        provider: AIProvider | None = None,
    ) -> None:
        self._conversations = conversation_repo
        self._messages = message_repo
        self._rate_limit = rate_limit_repo
        self._catalog = catalog_repo
        self._progress = progress_repo
        self._notes = notes_repo
        self._snippets = snippet_repo
        self._lld = lld_repo
        self._hld = hld_repo
        self._settings = settings
        self._provider = provider

    @property
    def provider(self) -> AIProvider:
        """Build the provider lazily so an unconfigured tutor cannot break app startup."""
        if self._provider is None:
            self._provider = build_provider(self._settings)
        return self._provider

    # ------------------------------------------------------------------------ chat
    async def chat(
        self,
        *,
        user_id: uuid.UUID,
        payload: AIChatRequest,
        timezone: str | None = None,
    ) -> AIChatResponse:
        """Answer a tutor request and persist both turns."""
        await self._enforce_rate_limit(user_id=user_id)

        # Resolve or create the conversation.
        conversation = None
        is_new = False

        if payload.conversation_id is not None:
            conversation = await self._conversations.get(
                user_id=user_id, conversation_id=payload.conversation_id
            )
        else:
            context_label = await self._resolve_context_label(
                user_id=user_id, context_type=payload.context_type.value, context_id=payload.context_id
            )
            conversation = await self._conversations.create(
                user_id=user_id,
                context_type=payload.context_type.value,
                context_id=payload.context_id,
                context_label=context_label,
                title=default_conversation_title(
                    context_type=payload.context_type.value,
                    context_label=context_label,
                    message=payload.message,
                ),
                provider=self.provider.name,
                model=self._settings.ai_model,
            )
            is_new = True

        # Persist the user's turn first: if the provider then fails, the user's message is
        # not lost and the thread still makes sense on reload.
        user_message = await self._messages.add(
            user_id=user_id,
            conversation_id=conversation.id,
            role="user",
            content=payload.message,
            action=payload.action.value,
            selected_code=payload.selected_code,
            snippet_id=payload.snippet_id,
        )

        context = await self._build_context(
            user_id=user_id, conversation=conversation, payload=payload
        )
        system_prompt = build_system_prompt(
            action=payload.action.value,
            context=context,
            auto_reveal_solution=await self._auto_reveal_enabled(user_id=user_id),
        )

        history: list[ChatMessage] = []
        if payload.include_history:
            stored = await self._messages.recent_history(
                user_id=user_id,
                conversation_id=conversation.id,
                # Exclude the turn just inserted; it becomes the final user message.
                limit=self._settings.ai_max_history_messages + 1,
            )
            prior = [message for message in stored if message.id != user_message.id]
            history = [
                ChatMessage(role=turn["role"], content=turn["content"])
                for turn in history_for_prompt(
                    prior, max_messages=self._settings.ai_max_history_messages
                )
            ]

        history.append(ChatMessage(role="user", content=payload.message))

        logger.info(
            "AI tutor request",
            extra={
                "action": payload.action.value,
                "context": context.summary(),
                "provider": self.provider.name,
            },
        )

        try:
            result = await self.provider.chat(messages=history, system=system_prompt)
        except AIConfigurationError:
            raise
        except Exception as exc:
            # Record the failure on the thread so the client can render it inline, then let
            # the error handler produce the error envelope.
            await self._messages.add(
                user_id=user_id,
                conversation_id=conversation.id,
                role="assistant",
                content="",
                action=payload.action.value,
                provider=self.provider.name,
                model=self._settings.ai_model,
                error=str(exc)[:500],
            )
            await self._conversations.touch(conversation, message_count_delta=1)
            await self._conversations.session.commit()
            raise

        assistant_message = await self._messages.add(
            user_id=user_id,
            conversation_id=conversation.id,
            role="assistant",
            content=result.content,
            action=payload.action.value,
            provider=result.provider,
            model=result.model,
            usage=result.usage,
        )

        # message_count tracks both turns of this exchange.
        await self._conversations.touch(conversation, message_count_delta=2)
        await self._conversations.session.commit()

        return AIChatResponse(
            conversation_id=conversation.id,
            message=self._message_response(assistant_message),
            context_used=context.summary(),
            is_new_conversation=is_new,
        )

    # ------------------------------------------------------------------ rate limiting
    async def _enforce_rate_limit(self, *, user_id: uuid.UUID) -> None:
        allowed, count, reset_at = await self._rate_limit.check_and_increment(
            user_id=user_id, limit=self._settings.ai_rate_limit_per_hour
        )
        # Persist the counter increment even when the request is rejected, so the window
        # cannot be reset by repeatedly hammering the endpoint.
        await self._rate_limit.session.commit()

        if not allowed:
            retry_after = max(1, int((reset_at - datetime.now(reset_at.tzinfo)).total_seconds()))
            raise RateLimitedError(
                f"AI tutor limit reached ({self._settings.ai_rate_limit_per_hour}/hour). "
                f"Try again in {retry_after} seconds.",
                details={
                    "limit": self._settings.ai_rate_limit_per_hour,
                    "used": count,
                    "resets_at": reset_at.isoformat(),
                    "retry_after_seconds": retry_after,
                },
            )

    # -------------------------------------------------------------------- context
    async def _build_context(
        self,
        *,
        user_id: uuid.UUID,
        conversation: Any,
        payload: AIChatRequest,
    ) -> TutorContext:
        """Assemble the minimal context for the request."""
        context = TutorContext(
            context_type=conversation.context_type,
            context_id=str(conversation.context_id) if conversation.context_id else None,
            context_label=conversation.context_label,
        )

        context_id = conversation.context_id

        if conversation.context_type == AIContextType.DSA.value and context_id is not None:
            problem_id = str(context_id)
            try:
                problem, progress = await self._catalog.get_with_progress(
                    user_id=user_id, problem_id=problem_id
                )
            except Exception:
                problem, progress = None, None
                logger.info("Tutor context problem not found; continuing without it")

            if problem is not None:
                context.entity = select_entity_fields(context_type="dsa", problem=problem)
                context.progress = select_progress_fields(progress or await self._progress.get(user_id=user_id, problem_id=problem_id))

            notes = await self._notes.get(user_id=user_id, problem_id=problem_id)
            context.notes = select_note_fields(context_type="dsa", notes=notes)

            if payload.action.value in _CODE_ACTIONS:
                context.code = await self._resolve_code(
                    user_id=user_id,
                    context_type=CodeContextType.DSA.value,
                    context_id=problem_id,
                    explicit_code=payload.selected_code,
                    snippet_id=payload.snippet_id,
                )

        elif conversation.context_type == AIContextType.LLD.value and context_id is not None:
            await self._fill_topic_context(
                user_id=user_id, context=context, topic_id=context_id, repo=self._lld, kind="lld", payload=payload
            )

        elif conversation.context_type == AIContextType.HLD.value and context_id is not None:
            await self._fill_topic_context(
                user_id=user_id, context=context, topic_id=context_id, repo=self._hld, kind="hld", payload=payload
            )

        # `general` deliberately gets no entity, notes, progress or code.
        return context

    async def _fill_topic_context(
        self,
        *,
        user_id: uuid.UUID,
        context: TutorContext,
        topic_id: uuid.UUID | str,
        repo: Any,
        kind: str,
        payload: AIChatRequest,
    ) -> None:
        topic_uuid = uuid.UUID(str(topic_id))
        try:
            topic, progress = await repo.get_with_progress(user_id=user_id, topic_id=topic_uuid)
        except Exception:
            topic, progress = None, None
            logger.info("Tutor context topic not found; continuing without it")

        if topic is not None:
            context.entity = select_entity_fields(context_type=kind, topic=topic)
            context.progress = select_progress_fields(progress)

        notes = await repo.get_notes(user_id=user_id, topic_id=topic_uuid)
        context.notes = select_note_fields(context_type=kind, notes=notes)

        if payload.action.value in _CODE_ACTIONS:
            context.code = await self._resolve_code(
                user_id=user_id,
                context_type=kind,
                context_id=str(topic_uuid),
                explicit_code=payload.selected_code,
                snippet_id=payload.snippet_id,
            )

    async def _resolve_code(
        self,
        *,
        user_id: uuid.UUID,
        context_type: str,
        context_id: str,
        explicit_code: str | None,
        snippet_id: uuid.UUID | None,
    ) -> str | None:
        """Resolve which code to attach, preferring what the user explicitly selected."""
        if explicit_code:
            return explicit_code[:MAX_CODE_CHARS]

        snippets = await self._snippets.list_for_context(
            user_id=user_id, context_type=context_type, context_id=context_id
        )
        if not snippets:
            return None

        if snippet_id is not None:
            chosen = next((s for s in snippets if s.id == snippet_id), None)
            if chosen is not None:
                return chosen.code[:MAX_CODE_CHARS]

        # Otherwise use the primary snippet, falling back to the most recent.
        primary = next((s for s in snippets if s.is_primary), snippets[-1])
        return primary.code[:MAX_CODE_CHARS]

    async def _resolve_context_label(
        self, *, user_id: uuid.UUID, context_type: str, context_id: uuid.UUID | None
    ) -> str | None:
        if context_id is None:
            return None
        try:
            if context_type == AIContextType.DSA.value:
                problems = await self._catalog.get_by_ids([str(context_id)])
                problem = problems.get(str(context_id))
                return problem.title if problem else None
            if context_type == AIContextType.LLD.value:
                topic, _ = await self._lld.get_with_progress(user_id=user_id, topic_id=context_id)
                return topic.title
            if context_type == AIContextType.HLD.value:
                topic, _ = await self._hld.get_with_progress(user_id=user_id, topic_id=context_id)
                return topic.title
        except Exception:
            return None
        return None

    async def _auto_reveal_enabled(self, *, user_id: uuid.UUID) -> bool:
        from app.repositories.user import UserSettingsRepository

        repo = UserSettingsRepository(self._conversations.session, self._settings)
        settings_row = await repo.get(user_id=user_id)
        return bool(settings_row.ai_auto_reveal_solution) if settings_row else False

    # ----------------------------------------------------------------- conversation CRUD
    async def list_conversations(
        self,
        *,
        user_id: uuid.UUID,
        limit: int,
        offset: int,
        context_type: str | None = None,
    ) -> tuple[list[AIConversationSummary], int]:
        rows, total = await self._conversations.list_for_user(
            user_id=user_id, limit=limit, offset=offset, context_type=context_type
        )
        return [
            AIConversationSummary(
                id=conversation.id,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
                version=conversation.version,
                title=conversation.title,
                context_type=conversation.context_type,
                context_id=conversation.context_id,
                context_label=conversation.context_label,
                provider=conversation.provider,
                model=conversation.model,
                message_count=conversation.message_count,
                last_message_at=conversation.last_message_at,
                preview=preview,
            )
            for conversation, preview in rows
        ], total

    async def get_conversation(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> AIConversationDetail:
        conversation = await self._conversations.get(
            user_id=user_id, conversation_id=conversation_id
        )
        messages = await self._messages.list_for_conversation(
            user_id=user_id, conversation_id=conversation_id
        )

        return AIConversationDetail(
            id=conversation.id,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            version=conversation.version,
            title=conversation.title,
            context_type=conversation.context_type,
            context_id=conversation.context_id,
            context_label=conversation.context_label,
            provider=conversation.provider,
            model=conversation.model,
            message_count=conversation.message_count,
            last_message_at=conversation.last_message_at,
            preview=None,
            messages=[self._message_response(message) for message in messages],
        )

    async def delete_conversation(
        self, *, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> None:
        conversation = await self._conversations.get(
            user_id=user_id, conversation_id=conversation_id
        )
        await self._conversations.soft_delete(conversation)
        await self._conversations.session.commit()

    # ------------------------------------------------------------------- metadata
    async def available_actions(self) -> dict[str, Any]:
        """Describe the tutor to a client so it need not hardcode the action list."""
        provider_health = await self.provider.health()
        return {
            "actions": [
                {"value": AIAction.EXPLAIN_CONCEPT.value, "label": "Explain the concept"},
                {"value": AIAction.GIVE_HINT.value, "label": "Give me a hint"},
                {"value": AIAction.EXPLAIN_CODE.value, "label": "Explain my code"},
                {"value": AIAction.FIND_BUG.value, "label": "Find the bug"},
                {"value": AIAction.COMPLEXITY.value, "label": "Analyse complexity"},
                {"value": AIAction.ALTERNATIVE_APPROACH.value, "label": "Alternative approach"},
                {"value": AIAction.INTERVIEW_ME.value, "label": "Interview me"},
                {"value": AIAction.GENERAL.value, "label": "General question"},
            ],
            "context_types": [item.value for item in AIContextType],
            "provider": self.provider.name,
            "model": self._settings.ai_model,
            "enabled": bool(provider_health.get("configured")),
        }

    # ------------------------------------------------------------------- helpers
    @staticmethod
    def _message_response(message: Any) -> AIMessageResponse:
        return AIMessageResponse(
            id=message.id,
            created_at=message.created_at,
            updated_at=message.updated_at,
            version=message.version,
            role=message.role,
            content=message.content,
            action=message.action,
            provider=message.provider,
            model=message.model,
            usage=message.usage,
            selected_code=message.selected_code,
            error=message.error,
        )

    @staticmethod
    def _ensure_owner(conversation: Any, user_id: uuid.UUID) -> None:
        """Defence in depth: the repository already scopes by user, but a mismatch here
        means something is deeply wrong and should never be served."""
        if conversation.user_id != user_id:
            raise ForbiddenError("That conversation belongs to another user.")


__all__ = ["AITutorService"]


def _validate_action(action: str) -> str:
    allowed = {item.value for item in AIAction}
    if action not in allowed:
        raise ValidationError(
            f"Unsupported action '{action}'. Allowed: {', '.join(sorted(allowed))}."
        )
    return action
