"""Unit tests for the pure policy/service logic.

These need no database, so they always run. They pin the *rules* the product depends on:
the spaced-repetition ladder, the determinism of the daily scheduler, and streak maths.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import CheckConstraint

from app.core.config import DEFAULT_REVISION_INTERVALS, Settings
from app.services.revision_policy import RevisionPolicy
from app.services.streak_service import StreakService


@pytest.fixture
def cfg() -> Settings:
    """A standalone Settings object.

    Named ``cfg`` rather than ``settings`` so it does not shadow the session-scoped
    database fixture defined in ``conftest.py``.
    """
    return Settings(AI_PROVIDER="stub", DATABASE_URL="postgresql://x/y")


@pytest.fixture
def policy(cfg: Settings) -> RevisionPolicy:
    return RevisionPolicy(cfg)


# --------------------------------------------------------------------------- the ladder
def test_ladder_starts_at_the_first_rung(policy: RevisionPolicy) -> None:
    """A first review uses index 0 of the confidence's ladder."""
    for confidence, ladder in DEFAULT_REVISION_INTERVALS.items():
        assert policy.interval_days(confidence=int(confidence), revision_count=0) == ladder[0]


def test_ladder_clamps_instead_of_running_off_the_end(policy: RevisionPolicy) -> None:
    """Reviewing more times than the ladder has rungs keeps the longest interval."""
    ladder = DEFAULT_REVISION_INTERVALS["3"]
    assert policy.interval_days(confidence=3, revision_count=99) == ladder[-1]


def test_ladder_intervals_are_monotonically_increasing() -> None:
    """Spacing must widen with each successful review, or revision would never taper off."""
    for confidence, ladder in DEFAULT_REVISION_INTERVALS.items():
        assert ladder == sorted(ladder), f"ladder {confidence} is not increasing"


def test_higher_confidence_waits_longer(policy: RevisionPolicy) -> None:
    """Well-understood material should come back later than shaky material."""
    low = policy.interval_days(confidence=1, revision_count=0)
    high = policy.interval_days(confidence=5, revision_count=0)
    assert high > low


def test_unknown_confidence_falls_back_to_zero(policy: RevisionPolicy) -> None:
    assert policy.interval_days(confidence=None, revision_count=0) == (
        DEFAULT_REVISION_INTERVALS["0"][0]
    )


def test_out_of_range_confidence_is_clamped(policy: RevisionPolicy) -> None:
    """A 9 cannot index past the top of the ladder."""
    assert policy.interval_days(confidence=9, revision_count=0) == (
        DEFAULT_REVISION_INTERVALS["5"][0]
    )


# ------------------------------------------------------------------- schedule behaviour
def test_failed_review_returns_tomorrow(policy: RevisionPolicy) -> None:
    """Failing is the strongest signal, so it ignores the ladder and retries in a day."""
    base = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    due_at, interval = policy.failure_retry_at(from_time=base)
    assert interval == 1
    assert due_at == base + timedelta(days=1)


def test_failure_retry_is_one_day_even_for_high_confidence(policy: RevisionPolicy) -> None:
    """Regression guard: the retry interval must not be derived from the ladder."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _, interval = policy.failure_retry_at(from_time=base)
    assert interval == 1


def test_low_confidence_solve_is_flagged_for_revision(policy: RevisionPolicy, cfg: Settings) -> None:
    """Solving something you barely understand should be marked low-confidence."""
    schedule = policy.schedule_after_solve(confidence=cfg.revision_low_confidence_threshold)
    assert schedule.reason == "low_confidence"


def test_confident_solve_uses_a_normal_schedule(policy: RevisionPolicy, cfg: Settings) -> None:
    schedule = policy.schedule_after_solve(confidence=cfg.revision_low_confidence_threshold + 1)
    assert schedule.reason == "scheduled_revision"


def test_missing_confidence_still_schedules_a_revision(policy: RevisionPolicy) -> None:
    """A problem with no confidence recorded must not become un-revisable."""
    schedule = policy.schedule_after_solve(confidence=None)
    assert schedule.interval_days >= 1
    assert schedule.due_at is not None


def test_low_confidence_outranks_high_confidence_in_priority(policy: RevisionPolicy) -> None:
    low = policy.priority_for(confidence=0, reason="low_confidence")
    high = policy.priority_for(confidence=5, reason="scheduled_revision")
    assert low > high, "lower confidence must mean higher (more urgent) priority"


def test_staleness_threshold_comes_from_the_ladder(policy: RevisionPolicy, cfg: Settings) -> None:
    """``revision_ladder_max_interval`` is derived, so the two can never disagree."""
    longest = max(max(v) for v in cfg.revision_intervals.values())
    assert cfg.revision_ladder_max_interval == longest


def test_ladder_is_exposed_for_clients(policy: RevisionPolicy) -> None:
    described = policy.describe_ladder()
    assert described == DEFAULT_REVISION_INTERVALS


# ----------------------------------------------------------------------------- streaks
def test_empty_history_has_no_streak() -> None:
    assert StreakService._longest_run(set()) == 0


def test_single_day_is_a_one_day_streak() -> None:
    assert StreakService._longest_run({date(2026, 1, 1)}) == 1


def test_consecutive_days_form_one_run() -> None:
    days = {date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)}
    assert StreakService._longest_run(days) == 3


def test_a_gap_splits_the_run() -> None:
    """One missed day breaks the streak — the whole point of a streak."""
    days = {date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6)}
    assert StreakService._longest_run(days) == 2


def test_longest_run_wins_even_if_earlier() -> None:
    days = {
        date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3), date(2026, 1, 4),
        date(2026, 1, 10), date(2026, 1, 11),
    }
    assert StreakService._longest_run(days) == 4


def test_unordered_input_is_handled() -> None:
    """The set is sorted internally, so insertion order must not matter."""
    days = {date(2026, 3, 5), date(2026, 3, 3), date(2026, 3, 4)}
    assert StreakService._longest_run(days) == 3


def test_run_across_a_month_boundary() -> None:
    days = {date(2026, 1, 30), date(2026, 1, 31), date(2026, 2, 1)}
    assert StreakService._longest_run(days) == 3


def test_run_across_a_leap_day() -> None:
    days = {date(2028, 2, 28), date(2028, 2, 29), date(2028, 3, 1)}
    assert StreakService._longest_run(days) == 3


# ------------------------------------------------------------------------- scheduler
def test_jitter_is_deterministic(cfg: Settings) -> None:
    """Identical inputs must give an identical nudge across processes and replays."""
    from app.services.daily_plan_scheduler import DailyPlanScheduler

    user = uuid.UUID("11111111-1111-1111-1111-111111111111")
    plan_date = date(2026, 1, 1)

    first = DailyPlanScheduler._jitter(user_id=user, plan_date=plan_date, problem_id="two-sum")
    second = DailyPlanScheduler._jitter(user_id=user, plan_date=plan_date, problem_id="two-sum")
    assert first == second


def test_jitter_stays_in_range() -> None:
    from app.services.daily_plan_scheduler import DailyPlanScheduler

    user = uuid.UUID("11111111-1111-1111-1111-111111111111")
    for index in range(200):
        value = DailyPlanScheduler._jitter(
            user_id=user, plan_date=date(2026, 1, 1), problem_id=f"problem-{index}"
        )
        assert 0.0 <= value < 3.0


def test_jitter_varies_between_problems() -> None:
    """It must actually discriminate, otherwise it would add no tie-breaking value."""
    from app.services.daily_plan_scheduler import DailyPlanScheduler

    user = uuid.UUID("11111111-1111-1111-1111-111111111111")
    values = {
        DailyPlanScheduler._jitter(
            user_id=user, plan_date=date(2026, 1, 1), problem_id=f"problem-{index}"
        )
        for index in range(50)
    }
    assert len(values) > 10


def test_jitter_differs_per_user() -> None:
    """Two users must not receive identical tie-breaks."""
    from app.services.daily_plan_scheduler import DailyPlanScheduler

    a = DailyPlanScheduler._jitter(
        user_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        plan_date=date(2026, 1, 1),
        problem_id="two-sum",
    )
    b = DailyPlanScheduler._jitter(
        user_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        plan_date=date(2026, 1, 1),
        problem_id="two-sum",
    )
    assert a != b


def test_jitter_differs_per_day() -> None:
    """Tomorrow's plan must not be a carbon copy of today's."""
    from app.services.daily_plan_scheduler import DailyPlanScheduler

    user = uuid.UUID("11111111-1111-1111-1111-111111111111")
    a = DailyPlanScheduler._jitter(user_id=user, plan_date=date(2026, 1, 1), problem_id="two-sum")
    b = DailyPlanScheduler._jitter(user_id=user, plan_date=date(2026, 1, 2), problem_id="two-sum")
    assert a != b


def test_difficulty_stage_progresses_with_completion() -> None:
    from app.services.daily_plan_scheduler import DailyPlanScheduler

    assert DailyPlanScheduler._stage_for(solved_count=0, total=100) == 0
    assert DailyPlanScheduler._stage_for(solved_count=20, total=100) == 1
    assert DailyPlanScheduler._stage_for(solved_count=50, total=100) == 2
    assert DailyPlanScheduler._stage_for(solved_count=90, total=100) == 3


def test_difficulty_stage_handles_an_empty_catalog() -> None:
    """Dividing by zero here would break the first request on a fresh install."""
    from app.services.daily_plan_scheduler import DailyPlanScheduler

    assert DailyPlanScheduler._stage_for(solved_count=0, total=0) == 0


def test_weakest_topics_are_ranked_by_confidence() -> None:
    """Weakest (lowest average confidence) first — that is what the planner targets."""
    from app.services.daily_plan_scheduler import DailyPlanScheduler

    weakest = DailyPlanScheduler._weakest_topics(
        {
            "graphs": {"interacted": 4, "average_confidence": 1.0},
            "arrays": {"interacted": 9, "average_confidence": 4.8},
            "strings": {"interacted": 5, "average_confidence": 3.0},
        }
    )
    assert weakest == ["graphs", "strings", "arrays"]


def test_weakest_topics_ignores_unstarted_topics() -> None:
    """A topic with no exposure is unstarted, not weak — curriculum position covers it."""
    from app.services.daily_plan_scheduler import DailyPlanScheduler

    weakest = DailyPlanScheduler._weakest_topics(
        {
            "graphs": {"interacted": 0, "average_confidence": 0.0},
            "arrays": {"interacted": 3, "average_confidence": 2.0},
        }
    )
    assert weakest == ["arrays"]


def test_weakest_topics_breaks_ties_by_exposure_then_name() -> None:
    """Deterministic ordering keeps plan generation reproducible."""
    from app.services.daily_plan_scheduler import DailyPlanScheduler

    weakest = DailyPlanScheduler._weakest_topics(
        {
            "zeta": {"interacted": 2, "average_confidence": 2.0},
            "beta": {"interacted": 2, "average_confidence": 2.0},
            "alpha": {"interacted": 2, "average_confidence": 2.0},
        }
    )
    assert weakest == ["alpha", "beta", "zeta"]


def test_weakest_topics_on_empty_input() -> None:
    from app.services.daily_plan_scheduler import DailyPlanScheduler

    assert DailyPlanScheduler._weakest_topics({}) == []


def test_scheduler_version_is_pinned() -> None:
    """Stored on every plan; changing it silently would invalidate stored plans."""
    from app.services.daily_plan_scheduler import SCHEDULER_VERSION

    assert SCHEDULER_VERSION == "scheduler_v1"


# ------------------------------------------------------------------------ config rules
def test_daily_count_is_clamped_to_the_maximum(cfg: Settings) -> None:
    """A client must not be able to request an unbounded plan."""
    assert cfg.dsa_daily_count(10_000) == cfg.daily_dsa_count_max


def test_daily_count_falls_back_to_the_default(cfg: Settings) -> None:
    assert cfg.dsa_daily_count(None) == cfg.daily_dsa_count_default


def test_revision_count_allows_zero(cfg: Settings) -> None:
    """Zero revisions is a legitimate preference, not an error."""
    assert cfg.revision_daily_count(0) == 0


def test_postgres_scheme_is_rewritten_for_asyncpg() -> None:
    """Supabase hands out ``postgresql://``; SQLAlchemy needs the async driver."""
    assert Settings(DATABASE_URL="postgresql://u:p@h:5432/d").database_url.startswith(
        "postgresql+asyncpg://"
    )


def test_jwks_url_is_derived_from_the_project_url() -> None:
    cfg = Settings(SUPABASE_URL="https://abcdefgh.supabase.co")
    assert cfg.resolved_jwks_url == (
        "https://abcdefgh.supabase.co/auth/v1/.well-known/jwks.json"
    )


def test_issuer_is_derived_from_the_project_url() -> None:
    cfg = Settings(SUPABASE_URL="https://abcdefgh.supabase.co")
    assert cfg.jwt_issuer == "https://abcdefgh.supabase.co/auth/v1"


def test_trailing_slash_on_supabase_url_is_tolerated() -> None:
    cfg = Settings(SUPABASE_URL="https://abcdefgh.supabase.co/")
    assert cfg.resolved_jwks_url == (
        "https://abcdefgh.supabase.co/auth/v1/.well-known/jwks.json"
    )


# ------------------------------------------------- progress check constraints (metadata)
def test_user_problem_progress_declares_its_check_constraints() -> None:
    """The ORM promises these constraints; migration 0004 is what puts them in the DB.

    This is a metadata-level assertion, so it runs without a database. It pins the two
    check-constraint *names* the model advertises — if a rename or a dropped
    ``__table_args__`` entry ever slips through, this test fails before the drift can
    reach a migration or the live schema.
    """
    from app.db.models.dsa import UserProblemProgress

    table = UserProblemProgress.__table__
    checks = {
        constraint.name: str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert "ck_user_problem_progress_status_valid" in checks
    assert "ck_user_problem_progress_confidence_range" in checks
    assert checks["ck_user_problem_progress_status_valid"] == (
        "status IN ('not_started','attempted','solved','needs_revision','mastered')"
    )
    assert checks["ck_user_problem_progress_confidence_range"] == "confidence BETWEEN 0 AND 5"


# --------------------------------------------------------------------------- CORS parsing
# `CORS_ORIGINS` is a `list[str]`, and pydantic-settings JSON-decodes complex types from the
# environment *before* validators run. A comma-separated value is not valid JSON, so the
# setting raised `SettingsError` and `_split_origins` was never reached — the field could not
# be configured from the environment at all.
#
# It went unnoticed because `.env` does not set CORS_ORIGINS, so the default factory was used.
# It surfaced only when deploying, where the variable must be set: it would have failed the
# first production deploy. `Annotated[list[str], NoDecode]` hands the raw string to the
# validator instead.


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://a.example.com,https://b.example.com", ["https://a.example.com", "https://b.example.com"]),
        ("https://a.example.com", ["https://a.example.com"]),
        ("https://a.example.com, https://b.example.com", ["https://a.example.com", "https://b.example.com"]),
        ('["https://a.example.com","https://b.example.com"]', ["https://a.example.com", "https://b.example.com"]),
        ("", []),
    ],
)
def test_cors_origins_parses_from_the_environment(monkeypatch, raw: str, expected: list[str]) -> None:
    """Every documented format must work when supplied as an environment variable."""
    from app.core.config import Settings

    monkeypatch.setenv("CORS_ORIGINS", raw)
    settings = Settings(
        DATABASE_URL="postgresql://u:p@h:5432/d",
        SUPABASE_URL="https://x.supabase.co",
    )
    assert settings.cors_origins == expected


def test_cors_origins_still_rejects_a_production_wildcard(monkeypatch) -> None:
    """The deploy guard must survive the parsing change."""
    from app.core.config import Settings
    from app.main import create_app

    monkeypatch.setenv("CORS_ORIGINS", "*")
    settings = Settings(
        DATABASE_URL="postgresql://u:p@h:5432/d",
        SUPABASE_URL="https://x.supabase.co",
        APP_ENV="production",
    )
    with pytest.raises(RuntimeError, match="Wildcard CORS origin is not permitted"):
        create_app(settings)


# ----------------------------------------------------------------------- CORS preflight
# The frontend sends `X-Timezone` on every request (http.ts), and the backend reads it
# (dependencies.py, alias="X-Timezone"). It was absent from CORS `allow_headers`, so the
# browser's preflight returned 400 and the request was blocked before it was ever made.
#
# This is invisible to curl, which does not preflight a plain GET, and presents in the
# browser as an opaque "preflight request doesn't pass access control check" — easy to
# misdiagnose as a network, auth, or proxy fault.


@pytest.mark.parametrize(
    "header",
    [
        "authorization",
        "content-type",
        "x-request-id",
        "x-device-id",
        "x-timezone",
    ],
)
def test_every_custom_header_the_client_sends_is_allowed_by_cors(header: str) -> None:
    """A header the app reads but CORS omits breaks every request in the browser."""
    from fastapi.middleware.cors import CORSMiddleware

    from app.core.config import Settings
    from app.main import create_app

    settings = Settings(
        DATABASE_URL="postgresql://u:p@h:5432/d",
        SUPABASE_URL="https://x.supabase.co",
        CORS_ORIGINS="https://app.example.com",
    )
    app = create_app(settings)

    cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    allowed = {h.lower() for h in cors.kwargs["allow_headers"]}
    assert header in allowed, f"{header} is sent by the client but not allowed by CORS"
