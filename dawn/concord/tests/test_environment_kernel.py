"""Tests for CONCORD v0.4-alpha — environment_kernel.py.

Key scenario tested:
  "Show me the ExecutionEnvironment lifecycle when a session has active intents
  and the environment goes unhealthy."

  - Environment heartbeat fails → mark_environment_unhealthy
  - Session has intents in ADMITTED/EXECUTING → get_blocking_intents
  - Compensation is triggered for each blocking intent (compensate_fn callback)
  - ENVIRONMENT_UNHEALTHY error code is emitted
  - agent_should = 'escalate_and_request_environment_replacement'
  - can_terminate is False until all compensation succeeds
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from dawn.concord.environment_kernel import (
    EnvironmentTeardownResult,
    get_blocking_intents,
    handle_unhealthy_environment,
    mark_environment_unhealthy,
)
from dawn.concord.types.entities import ExecutionEnvironment, Intent
from dawn.concord.types.enums import (
    ConsistencyProfile,
    EnvironmentClass,
    EnvironmentStatus,
    IntentStatus,
    IsolationLevel,
    ProvisioningStatus,
    RiskLevel,
    SessionMode,
    TrustTier,
)

NOW = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)


# ── Fixture helpers ───────────────────────────────────────────────────────────


def _env(
    env_id: str = "env-1",
    status: EnvironmentStatus = EnvironmentStatus.ACTIVE,
    session_id: str | None = "sess-1",
) -> ExecutionEnvironment:
    return ExecutionEnvironment(
        environment_id=env_id,
        environment_class=EnvironmentClass.PERSISTENT,
        provisioning_status=ProvisioningStatus.ASSIGNED,
        isolation_level=IsolationLevel.CONTAINER,
        resource_spec={"cpu": 2, "memory_gb": 4},
        preload_manifest=[],
        created_at=NOW,
        max_lifetime_ms=3_600_000,
        heartbeat_interval_ms=30_000,
        status=status,
        assigned_session_id=session_id,
        ready_at=NOW,
        assigned_at=NOW,
    )


def _intent(
    intent_id: str,
    status: IntentStatus,
    session_id: str = "sess-1",
) -> Intent:
    return Intent(
        id=intent_id,
        session_id=session_id,
        resource_type="change_request",
        resource_id="cr-42",
        action_name="update",
        idempotency_key=f"idem-{intent_id}",
        status=status,
        consistency_profile=ConsistencyProfile.STRONG,
        risk_level=RiskLevel.MODERATE,
        participates_in_saga=False,
        created_at=NOW,
    )


# ── mark_environment_unhealthy ────────────────────────────────────────────────


class TestMarkEnvironmentUnhealthy:
    def test_active_becomes_unhealthy(self):
        env = _env(status=EnvironmentStatus.ACTIVE)
        updated = mark_environment_unhealthy(env)
        assert updated.status == EnvironmentStatus.UNHEALTHY

    def test_original_env_unchanged(self):
        env = _env(status=EnvironmentStatus.ACTIVE)
        mark_environment_unhealthy(env)
        assert env.status == EnvironmentStatus.ACTIVE

    def test_already_unhealthy_stays_unhealthy(self):
        env = _env(status=EnvironmentStatus.UNHEALTHY)
        updated = mark_environment_unhealthy(env)
        assert updated.status == EnvironmentStatus.UNHEALTHY

    def test_terminated_stays_terminated(self):
        env = _env(status=EnvironmentStatus.TERMINATED)
        updated = mark_environment_unhealthy(env)
        assert updated.status == EnvironmentStatus.TERMINATED

    def test_environment_id_preserved(self):
        env = _env(env_id="env-99")
        updated = mark_environment_unhealthy(env)
        assert updated.environment_id == "env-99"


# ── get_blocking_intents ──────────────────────────────────────────────────────


class TestGetBlockingIntents:
    def test_admitted_is_blocking(self):
        intents = [_intent("i1", IntentStatus.ADMITTED)]
        assert len(get_blocking_intents(intents)) == 1

    def test_executing_is_blocking(self):
        intents = [_intent("i1", IntentStatus.EXECUTING)]
        assert len(get_blocking_intents(intents)) == 1

    def test_proposed_is_not_blocking(self):
        intents = [_intent("i1", IntentStatus.PROPOSED)]
        assert get_blocking_intents(intents) == []

    def test_queued_is_not_blocking(self):
        intents = [_intent("i1", IntentStatus.QUEUED)]
        assert get_blocking_intents(intents) == []

    def test_committed_is_not_blocking(self):
        intents = [_intent("i1", IntentStatus.COMMITTED)]
        assert get_blocking_intents(intents) == []

    def test_failed_is_not_blocking(self):
        intents = [_intent("i1", IntentStatus.FAILED)]
        assert get_blocking_intents(intents) == []

    def test_mixed_statuses_returns_only_blocking(self):
        intents = [
            _intent("i1", IntentStatus.ADMITTED),
            _intent("i2", IntentStatus.COMMITTED),
            _intent("i3", IntentStatus.EXECUTING),
            _intent("i4", IntentStatus.FAILED),
            _intent("i5", IntentStatus.PROPOSED),
        ]
        blocking = get_blocking_intents(intents)
        assert {i.id for i in blocking} == {"i1", "i3"}

    def test_empty_intents(self):
        assert get_blocking_intents([]) == []

    def test_returns_in_input_order(self):
        intents = [
            _intent("i3", IntentStatus.EXECUTING),
            _intent("i1", IntentStatus.ADMITTED),
        ]
        blocking = get_blocking_intents(intents)
        assert [i.id for i in blocking] == ["i3", "i1"]


# ── handle_unhealthy_environment ──────────────────────────────────────────────


class TestHandleUnhealthyEnvironment:
    # ── No blocking intents (safe teardown) ──────────────────────────────────

    def test_no_intents_can_terminate(self):
        env = _env()
        result = handle_unhealthy_environment(env, [])
        assert result.can_terminate is True

    def test_no_intents_env_becomes_terminated(self):
        env = _env()
        result = handle_unhealthy_environment(env, [])
        assert result.updated_environment.status == EnvironmentStatus.TERMINATED

    def test_no_intents_no_error_code(self):
        env = _env()
        result = handle_unhealthy_environment(env, [])
        assert result.error_code is None
        assert result.agent_should is None

    def test_no_intents_blocking_list_empty(self):
        env = _env()
        result = handle_unhealthy_environment(env, [])
        assert result.blocking_intent_ids == []

    def test_only_committed_intents_can_terminate(self):
        env = _env()
        intents = [
            _intent("i1", IntentStatus.COMMITTED),
            _intent("i2", IntentStatus.FAILED),
        ]
        result = handle_unhealthy_environment(env, intents)
        assert result.can_terminate is True
        assert result.error_code is None

    # ── Blocking intents present — THE CORE SCENARIO ─────────────────────────

    def test_admitted_intent_blocks_teardown(self):
        """Heartbeat fails; session has ADMITTED intent → teardown blocked."""
        env = _env()
        intents = [_intent("i1", IntentStatus.ADMITTED)]
        result = handle_unhealthy_environment(env, intents)

        assert result.can_terminate is False
        assert result.error_code == "ENVIRONMENT_UNHEALTHY"

    def test_executing_intent_blocks_teardown(self):
        env = _env()
        intents = [_intent("i1", IntentStatus.EXECUTING)]
        result = handle_unhealthy_environment(env, intents)

        assert result.can_terminate is False
        assert result.error_code == "ENVIRONMENT_UNHEALTHY"

    def test_agent_should_is_escalate(self):
        """ENVIRONMENT_UNHEALTHY must carry agent_should = escalate..."""
        env = _env()
        intents = [_intent("i1", IntentStatus.ADMITTED)]
        result = handle_unhealthy_environment(env, intents)

        assert result.agent_should == "escalate_and_request_environment_replacement"

    def test_blocking_intent_ids_listed(self):
        env = _env()
        intents = [
            _intent("i1", IntentStatus.ADMITTED),
            _intent("i2", IntentStatus.EXECUTING),
            _intent("i3", IntentStatus.COMMITTED),
        ]
        result = handle_unhealthy_environment(env, intents)
        assert set(result.blocking_intent_ids) == {"i1", "i2"}

    def test_env_stays_unhealthy_when_blocking_and_no_compensate_fn(self):
        env = _env()
        intents = [_intent("i1", IntentStatus.ADMITTED)]
        result = handle_unhealthy_environment(env, intents)
        assert result.updated_environment.status == EnvironmentStatus.UNHEALTHY

    def test_no_compensate_fn_gives_empty_outcomes(self):
        env = _env()
        intents = [_intent("i1", IntentStatus.ADMITTED)]
        result = handle_unhealthy_environment(env, intents)
        assert result.compensation_outcomes == {}

    # ── Compensation path ─────────────────────────────────────────────────────

    def test_successful_compensation_allows_termination(self):
        """After all compensation succeeds, environment may be terminated."""
        env = _env()
        intents = [
            _intent("i1", IntentStatus.ADMITTED),
            _intent("i2", IntentStatus.EXECUTING),
        ]
        compensate_fn = lambda intent_id: True   # noqa: E731
        result = handle_unhealthy_environment(env, intents, compensate_fn=compensate_fn)

        assert result.can_terminate is True
        assert result.updated_environment.status == EnvironmentStatus.TERMINATED

    def test_compensation_called_for_each_blocking_intent(self):
        env = _env()
        intents = [
            _intent("i1", IntentStatus.ADMITTED),
            _intent("i2", IntentStatus.EXECUTING),
        ]
        called: list[str] = []
        def compensate_fn(intent_id: str) -> bool:
            called.append(intent_id)
            return True

        handle_unhealthy_environment(env, intents, compensate_fn=compensate_fn)
        assert set(called) == {"i1", "i2"}

    def test_partial_compensation_failure_blocks_termination(self):
        """If one intent fails compensation, can_terminate = False."""
        env = _env()
        intents = [
            _intent("i1", IntentStatus.ADMITTED),
            _intent("i2", IntentStatus.EXECUTING),
        ]
        def compensate_fn(intent_id: str) -> bool:
            return intent_id == "i1"   # i2 fails

        result = handle_unhealthy_environment(env, intents, compensate_fn=compensate_fn)
        assert result.can_terminate is False
        assert result.compensation_outcomes == {"i1": True, "i2": False}
        assert result.updated_environment.status == EnvironmentStatus.UNHEALTHY

    def test_all_compensation_fails_blocks_termination(self):
        env = _env()
        intents = [_intent("i1", IntentStatus.ADMITTED)]
        result = handle_unhealthy_environment(env, intents, compensate_fn=lambda _: False)
        assert result.can_terminate is False
        assert result.updated_environment.status == EnvironmentStatus.UNHEALTHY

    def test_compensation_not_called_for_non_blocking_intents(self):
        env = _env()
        intents = [
            _intent("i1", IntentStatus.ADMITTED),
            _intent("i2", IntentStatus.COMMITTED),  # non-blocking
        ]
        called: list[str] = []
        handle_unhealthy_environment(env, intents, compensate_fn=lambda i: (called.append(i), True)[1])
        assert "i2" not in called

    # ── Result invariants ─────────────────────────────────────────────────────

    def test_environment_id_preserved_in_result(self):
        env = _env(env_id="env-99")
        result = handle_unhealthy_environment(env, [])
        assert result.environment_id == "env-99"

    def test_returns_environment_teardown_result(self):
        result = handle_unhealthy_environment(_env(), [])
        assert isinstance(result, EnvironmentTeardownResult)

    def test_error_code_emitted_iff_blocking_intents(self):
        env = _env()
        no_block = handle_unhealthy_environment(env, [])
        with_block = handle_unhealthy_environment(env, [_intent("i1", IntentStatus.ADMITTED)])
        assert no_block.error_code is None
        assert with_block.error_code == "ENVIRONMENT_UNHEALTHY"
