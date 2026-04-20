"""Tests for CONCORD Phase 6 — recovery_kernel.py.

Coverage:
  - build_receipt
  - SagaStore (ABC enforcement + InMemorySagaStore)
  - create_saga (happy path + validation)
  - advance_saga_step (happy + error cases)
  - complete_saga (happy + error)
  - fail_saga (happy + error)
  - is_saga_timed_out (all 4 timeout policies + missing params)
  - enforce_timeout (timeout fires → FAILED; no timeout → None)
  - CompensationResult (frozen dataclass contract)
  - is_saga_poisoned
  - compensate_saga (all 4 strategies, poison guard, callable enforcement)
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from dawn.concord.recovery_kernel import (
    CompensationResult,
    InMemorySagaStore,
    SagaStore,
    advance_saga_step,
    build_receipt,
    compensate_saga,
    complete_saga,
    create_saga,
    enforce_timeout,
    fail_saga,
    is_saga_poisoned,
    is_saga_timed_out,
)
from dawn.concord.types.entities import Intent, Receipt, Resource, SagaRun
from dawn.concord.types.enums import (
    CompensationStrategy,
    ConsistencyProfile,
    IntentStatus,
    RiskLevel,
    SagaTimeoutPolicy,
)

# ── Shared fixtures ───────────────────────────────────────────────────────────

NOW = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)
PAST = NOW - timedelta(seconds=10)
FUTURE = NOW + timedelta(seconds=10)


def _resource(*, version: int = 1, state: Optional[dict] = None) -> Resource:
    s = state or {"status": "draft"}
    return Resource(
        id="cr-1",
        resource_type="change_request",
        business_state=copy.deepcopy(s),
        coordination_state={},
        version=version,
        created_at=NOW,
        updated_at=NOW,
    )


def _intent() -> Intent:
    return Intent(
        id="intent-1",
        session_id="sess-1",
        resource_type="change_request",
        resource_id="cr-1",
        action_name="update",
        idempotency_key="idem-1",
        status=IntentStatus.EXECUTING,
        consistency_profile=ConsistencyProfile.STRONG,
        risk_level=RiskLevel.LOW,
        participates_in_saga=True,
        created_at=NOW,
        saga_id="saga-1",
    )


def _saga(
    store: SagaStore,
    *,
    steps: list[str] | None = None,
    timeout_policy: SagaTimeoutPolicy = SagaTimeoutPolicy.FIXED,
    timeout_deadline_ms: int = 60_000,
    compensation_strategy: CompensationStrategy = CompensationStrategy.NONE,
    max_compensation_attempts: int = 3,
    step_timeout_ms: int | None = None,
    heartbeat_interval_ms: int | None = None,
    external_dependency_timeout_ms: int | None = None,
    started_at: datetime | None = None,
) -> SagaRun:
    return create_saga(
        store,
        id="saga-1",
        root_intent_id="intent-1",
        steps=steps or ["step-1", "step-2", "step-3"],
        timeout_policy=timeout_policy,
        timeout_deadline_ms=timeout_deadline_ms,
        compensation_strategy=compensation_strategy,
        max_compensation_attempts=max_compensation_attempts,
        step_timeout_ms=step_timeout_ms,
        heartbeat_interval_ms=heartbeat_interval_ms,
        external_dependency_timeout_ms=external_dependency_timeout_ms,
        started_at=started_at or PAST,
    )


# ── TestBuildReceipt ──────────────────────────────────────────────────────────

class TestBuildReceipt:
    def test_returns_receipt(self):
        r = build_receipt(
            operation_id="op-1",
            intent=_intent(),
            resource_before=_resource(version=1, state={"status": "draft"}),
            resource_after=_resource(version=2, state={"status": "submitted"}),
            duration_ms=42,
            policy_decision="allowed",
        )
        assert isinstance(r, Receipt)

    def test_copies_intent_id(self):
        r = build_receipt(
            operation_id="op-1",
            intent=_intent(),
            resource_before=_resource(),
            resource_after=_resource(version=2),
            duration_ms=10,
            policy_decision="allowed",
        )
        assert r.intent_id == "intent-1"

    def test_operation_id(self):
        r = build_receipt(
            operation_id="op-XYZ",
            intent=_intent(),
            resource_before=_resource(),
            resource_after=_resource(version=2),
            duration_ms=10,
            policy_decision="allowed",
        )
        assert r.operation_id == "op-XYZ"

    def test_previous_and_next_state(self):
        before = _resource(version=1, state={"status": "draft"})
        after = _resource(version=2, state={"status": "submitted"})
        r = build_receipt(
            operation_id="op-1",
            intent=_intent(),
            resource_before=before,
            resource_after=after,
            duration_ms=10,
            policy_decision="allowed",
        )
        assert r.previous_state == {"status": "draft"}
        assert r.next_state == {"status": "submitted"}

    def test_versions(self):
        r = build_receipt(
            operation_id="op-1",
            intent=_intent(),
            resource_before=_resource(version=5),
            resource_after=_resource(version=6),
            duration_ms=10,
            policy_decision="allowed",
        )
        assert r.version_before == 5
        assert r.version_after == 6

    def test_duration_and_policy(self):
        r = build_receipt(
            operation_id="op-1",
            intent=_intent(),
            resource_before=_resource(),
            resource_after=_resource(version=2),
            duration_ms=123,
            policy_decision="allowed-by-budget",
        )
        assert r.duration_ms == 123
        assert r.policy_decision == "allowed-by-budget"

    def test_result_status_is_success(self):
        r = build_receipt(
            operation_id="op-1",
            intent=_intent(),
            resource_before=_resource(),
            resource_after=_resource(version=2),
            duration_ms=10,
            policy_decision="allowed",
        )
        assert r.result_status == "success"

    def test_warnings_and_errors(self):
        r = build_receipt(
            operation_id="op-1",
            intent=_intent(),
            resource_before=_resource(),
            resource_after=_resource(version=2),
            duration_ms=10,
            policy_decision="allowed",
            warnings=["w1", "w2"],
            errors=["e1"],
        )
        assert r.warnings == ["w1", "w2"]
        assert r.errors == ["e1"]

    def test_optional_fields_default_empty(self):
        r = build_receipt(
            operation_id="op-1",
            intent=_intent(),
            resource_before=_resource(),
            resource_after=_resource(version=2),
            duration_ms=10,
            policy_decision="allowed",
        )
        assert r.warnings == []
        assert r.errors == []
        assert r.scopes_applied == []
        assert r.environment_id is None
        assert r.entry_point_id is None

    def test_traceability_fields(self):
        r = build_receipt(
            operation_id="op-1",
            intent=_intent(),
            resource_before=_resource(),
            resource_after=_resource(version=2),
            duration_ms=10,
            policy_decision="allowed",
            environment_id="env-prod",
            entry_point_id="ep-api",
            scopes_applied=["scope-a", "scope-b"],
        )
        assert r.environment_id == "env-prod"
        assert r.entry_point_id == "ep-api"
        assert r.scopes_applied == ["scope-a", "scope-b"]

    def test_state_is_deep_copied(self):
        """Mutations to the original resource state must not affect the receipt."""
        before = _resource(version=1, state={"status": "draft"})
        r = build_receipt(
            operation_id="op-1",
            intent=_intent(),
            resource_before=before,
            resource_after=_resource(version=2),
            duration_ms=10,
            policy_decision="allowed",
        )
        before.business_state["status"] = "MUTATED"
        assert r.previous_state["status"] == "draft"


# ── TestInMemorySagaStore ─────────────────────────────────────────────────────

class TestInMemorySagaStore:
    def _bare_saga(self, *, id: str = "saga-1") -> SagaRun:
        return SagaRun(
            id=id,
            root_intent_id="intent-1",
            steps=["step-1"],
            current_step=0,
            timeout_policy=SagaTimeoutPolicy.FIXED,
            timeout_deadline_ms=60_000,
            compensation_strategy=CompensationStrategy.NONE,
            max_compensation_attempts=3,
            attempt_count=0,
            status=IntentStatus.EXECUTING,
            started_at=NOW,
        )

    def test_save_and_fetch(self):
        store = InMemorySagaStore()
        saga = self._bare_saga()
        store.save(saga)
        fetched = store.fetch("saga-1")
        assert fetched.id == "saga-1"

    def test_fetch_missing_raises_key_error(self):
        store = InMemorySagaStore()
        with pytest.raises(KeyError):
            store.fetch("nonexistent")

    def test_exists(self):
        store = InMemorySagaStore()
        assert not store.exists("saga-1")
        store.save(self._bare_saga())
        assert store.exists("saga-1")

    def test_save_returns_copy(self):
        store = InMemorySagaStore()
        saga = self._bare_saga()
        returned = store.save(saga)
        assert returned is not saga

    def test_fetch_returns_copy(self):
        store = InMemorySagaStore()
        store.save(self._bare_saga())
        a = store.fetch("saga-1")
        b = store.fetch("saga-1")
        assert a is not b

    def test_abc_enforcement(self):
        class Incomplete(SagaStore):
            pass
        with pytest.raises(TypeError):
            Incomplete()

    def test_len(self):
        store = InMemorySagaStore()
        assert len(store) == 0
        store.save(self._bare_saga(id="s1"))
        store.save(self._bare_saga(id="s2"))
        assert len(store) == 2


# ── TestCreateSaga ────────────────────────────────────────────────────────────

class TestCreateSaga:
    def test_creates_in_executing_state(self):
        store = InMemorySagaStore()
        saga = _saga(store)
        assert saga.status == IntentStatus.EXECUTING

    def test_current_step_starts_at_zero(self):
        store = InMemorySagaStore()
        saga = _saga(store)
        assert saga.current_step == 0

    def test_attempt_count_starts_at_zero(self):
        store = InMemorySagaStore()
        saga = _saga(store)
        assert saga.attempt_count == 0

    def test_steps_stored(self):
        store = InMemorySagaStore()
        saga = _saga(store, steps=["a", "b", "c"])
        assert saga.steps == ["a", "b", "c"]

    def test_persisted_in_store(self):
        store = InMemorySagaStore()
        _saga(store)
        assert store.exists("saga-1")

    def test_empty_steps_raises(self):
        store = InMemorySagaStore()
        with pytest.raises(ValueError, match="at least one step"):
            create_saga(
                store,
                id="saga-x",
                root_intent_id="intent-1",
                steps=[],
                timeout_policy=SagaTimeoutPolicy.FIXED,
                timeout_deadline_ms=60_000,
                compensation_strategy=CompensationStrategy.NONE,
                max_compensation_attempts=3,
            )

    def test_optional_fields_preserved(self):
        store = InMemorySagaStore()
        saga = _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.STEP_ADAPTIVE,
            step_timeout_ms=5_000,
            heartbeat_interval_ms=2_000,
            external_dependency_timeout_ms=10_000,
        )
        assert saga.step_timeout_ms == 5_000
        assert saga.heartbeat_interval_ms == 2_000
        assert saga.external_dependency_timeout_ms == 10_000

    def test_started_at_defaults_to_utcnow(self):
        store = InMemorySagaStore()
        before = datetime.now(timezone.utc)
        saga = create_saga(
            store,
            id="saga-x",
            root_intent_id="intent-1",
            steps=["s1"],
            timeout_policy=SagaTimeoutPolicy.FIXED,
            timeout_deadline_ms=60_000,
            compensation_strategy=CompensationStrategy.NONE,
            max_compensation_attempts=3,
        )
        after = datetime.now(timezone.utc)
        assert before <= saga.started_at <= after

    def test_started_at_explicit(self):
        store = InMemorySagaStore()
        saga = _saga(store, started_at=NOW)
        assert saga.started_at == NOW


# ── TestAdvanceSagaStep ───────────────────────────────────────────────────────

class TestAdvanceSagaStep:
    def test_advances_current_step(self):
        store = InMemorySagaStore()
        _saga(store, steps=["s1", "s2", "s3"])
        updated = advance_saga_step(store, "saga-1")
        assert updated.current_step == 1

    def test_persists_new_step(self):
        store = InMemorySagaStore()
        _saga(store, steps=["s1", "s2", "s3"])
        advance_saga_step(store, "saga-1")
        assert store.fetch("saga-1").current_step == 1

    def test_second_advance(self):
        store = InMemorySagaStore()
        _saga(store, steps=["s1", "s2", "s3"])
        advance_saga_step(store, "saga-1")
        updated = advance_saga_step(store, "saga-1")
        assert updated.current_step == 2

    def test_advance_at_last_step_raises(self):
        store = InMemorySagaStore()
        _saga(store, steps=["s1", "s2"])
        advance_saga_step(store, "saga-1")  # step → 1 (last)
        with pytest.raises(ValueError, match="last step"):
            advance_saga_step(store, "saga-1")

    def test_advance_non_executing_raises(self):
        store = InMemorySagaStore()
        _saga(store, steps=["s1", "s2"])
        complete_saga(store, "saga-1")  # now COMMITTED
        with pytest.raises(ValueError, match="not EXECUTING"):
            advance_saga_step(store, "saga-1")

    def test_advance_missing_raises_key_error(self):
        store = InMemorySagaStore()
        with pytest.raises(KeyError):
            advance_saga_step(store, "nonexistent")


# ── TestCompleteSaga ──────────────────────────────────────────────────────────

class TestCompleteSaga:
    def test_sets_committed_status(self):
        store = InMemorySagaStore()
        _saga(store)
        result = complete_saga(store, "saga-1")
        assert result.status == IntentStatus.COMMITTED

    def test_persists_committed(self):
        store = InMemorySagaStore()
        _saga(store)
        complete_saga(store, "saga-1")
        assert store.fetch("saga-1").status == IntentStatus.COMMITTED

    def test_complete_non_executing_raises(self):
        store = InMemorySagaStore()
        _saga(store)
        complete_saga(store, "saga-1")
        with pytest.raises(ValueError, match="EXECUTING"):
            complete_saga(store, "saga-1")

    def test_complete_failed_raises(self):
        store = InMemorySagaStore()
        _saga(store)
        fail_saga(store, "saga-1")
        with pytest.raises(ValueError, match="EXECUTING"):
            complete_saga(store, "saga-1")

    def test_complete_missing_raises_key_error(self):
        store = InMemorySagaStore()
        with pytest.raises(KeyError):
            complete_saga(store, "nonexistent")


# ── TestFailSaga ──────────────────────────────────────────────────────────────

class TestFailSaga:
    def test_sets_failed_status(self):
        store = InMemorySagaStore()
        _saga(store)
        result = fail_saga(store, "saga-1")
        assert result.status == IntentStatus.FAILED

    def test_persists_failed(self):
        store = InMemorySagaStore()
        _saga(store)
        fail_saga(store, "saga-1")
        assert store.fetch("saga-1").status == IntentStatus.FAILED

    def test_fail_non_executing_raises(self):
        store = InMemorySagaStore()
        _saga(store)
        complete_saga(store, "saga-1")
        with pytest.raises(ValueError, match="EXECUTING"):
            fail_saga(store, "saga-1")

    def test_fail_missing_raises_key_error(self):
        store = InMemorySagaStore()
        with pytest.raises(KeyError):
            fail_saga(store, "nonexistent")


# ── TestIsTimedOut ────────────────────────────────────────────────────────────

class TestIsTimedOut:
    # FIXED policy
    def test_fixed_not_timed_out(self):
        store = InMemorySagaStore()
        saga = _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.FIXED,
            timeout_deadline_ms=60_000,
            started_at=NOW - timedelta(seconds=5),  # 5 s elapsed
        )
        assert not is_saga_timed_out(saga, now=NOW)

    def test_fixed_exactly_at_deadline(self):
        store = InMemorySagaStore()
        saga = _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.FIXED,
            timeout_deadline_ms=5_000,
            started_at=NOW - timedelta(seconds=5),  # exactly 5 s
        )
        assert is_saga_timed_out(saga, now=NOW)

    def test_fixed_past_deadline(self):
        store = InMemorySagaStore()
        saga = _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.FIXED,
            timeout_deadline_ms=1_000,
            started_at=NOW - timedelta(seconds=10),  # 10 s elapsed
        )
        assert is_saga_timed_out(saga, now=NOW)

    def test_fixed_missing_started_at_returns_false(self):
        """started_at=None means we cannot determine timeout → safe default."""
        store = InMemorySagaStore()
        saga = _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.FIXED,
            timeout_deadline_ms=1,
            started_at=None,
        )
        # Force started_at to None on the returned saga
        from dataclasses import replace as dc_replace
        saga = dc_replace(saga, started_at=None)
        assert not is_saga_timed_out(saga, now=NOW)

    # STEP_ADAPTIVE policy
    def test_step_adaptive_not_timed_out(self):
        store = InMemorySagaStore()
        saga = _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.STEP_ADAPTIVE,
            step_timeout_ms=10_000,
        )
        step_start = NOW - timedelta(seconds=5)
        assert not is_saga_timed_out(saga, now=NOW, last_step_started_at=step_start)

    def test_step_adaptive_timed_out(self):
        store = InMemorySagaStore()
        saga = _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.STEP_ADAPTIVE,
            step_timeout_ms=3_000,
        )
        step_start = NOW - timedelta(seconds=5)
        assert is_saga_timed_out(saga, now=NOW, last_step_started_at=step_start)

    def test_step_adaptive_missing_step_start_returns_false(self):
        store = InMemorySagaStore()
        saga = _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.STEP_ADAPTIVE,
            step_timeout_ms=1,
        )
        assert not is_saga_timed_out(saga, now=NOW)  # no last_step_started_at

    def test_step_adaptive_missing_step_timeout_ms_returns_false(self):
        store = InMemorySagaStore()
        saga = _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.STEP_ADAPTIVE,
            step_timeout_ms=None,
        )
        step_start = NOW - timedelta(seconds=100)
        assert not is_saga_timed_out(saga, now=NOW, last_step_started_at=step_start)

    # HEARTBEAT policy
    def test_heartbeat_not_timed_out(self):
        store = InMemorySagaStore()
        saga = _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.HEARTBEAT,
            heartbeat_interval_ms=10_000,
        )
        last_hb = NOW - timedelta(seconds=5)
        assert not is_saga_timed_out(saga, now=NOW, last_heartbeat_at=last_hb)

    def test_heartbeat_timed_out(self):
        store = InMemorySagaStore()
        saga = _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.HEARTBEAT,
            heartbeat_interval_ms=3_000,
        )
        last_hb = NOW - timedelta(seconds=5)
        assert is_saga_timed_out(saga, now=NOW, last_heartbeat_at=last_hb)

    def test_heartbeat_missing_last_hb_returns_false(self):
        store = InMemorySagaStore()
        saga = _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.HEARTBEAT,
            heartbeat_interval_ms=1,
        )
        assert not is_saga_timed_out(saga, now=NOW)

    # EXTERNAL_GATED policy
    def test_external_gated_not_timed_out(self):
        store = InMemorySagaStore()
        saga = _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.EXTERNAL_GATED,
            external_dependency_timeout_ms=30_000,
        )
        step_start = NOW - timedelta(seconds=5)
        assert not is_saga_timed_out(saga, now=NOW, last_step_started_at=step_start)

    def test_external_gated_timed_out(self):
        store = InMemorySagaStore()
        saga = _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.EXTERNAL_GATED,
            external_dependency_timeout_ms=3_000,
        )
        step_start = NOW - timedelta(seconds=5)
        assert is_saga_timed_out(saga, now=NOW, last_step_started_at=step_start)

    def test_external_gated_missing_step_start_returns_false(self):
        store = InMemorySagaStore()
        saga = _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.EXTERNAL_GATED,
            external_dependency_timeout_ms=1,
        )
        assert not is_saga_timed_out(saga, now=NOW)


# ── TestEnforceTimeout ────────────────────────────────────────────────────────

class TestEnforceTimeout:
    def test_times_out_fails_saga(self):
        store = InMemorySagaStore()
        _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.FIXED,
            timeout_deadline_ms=1_000,
            started_at=NOW - timedelta(seconds=10),
        )
        result = enforce_timeout(store, "saga-1", now=NOW)
        assert result is not None
        assert result.status == IntentStatus.FAILED

    def test_persists_failed_saga(self):
        store = InMemorySagaStore()
        _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.FIXED,
            timeout_deadline_ms=1_000,
            started_at=NOW - timedelta(seconds=10),
        )
        enforce_timeout(store, "saga-1", now=NOW)
        assert store.fetch("saga-1").status == IntentStatus.FAILED

    def test_no_timeout_returns_none(self):
        store = InMemorySagaStore()
        _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.FIXED,
            timeout_deadline_ms=60_000,
            started_at=NOW - timedelta(seconds=1),
        )
        result = enforce_timeout(store, "saga-1", now=NOW)
        assert result is None

    def test_no_timeout_saga_remains_executing(self):
        store = InMemorySagaStore()
        _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.FIXED,
            timeout_deadline_ms=60_000,
            started_at=NOW - timedelta(seconds=1),
        )
        enforce_timeout(store, "saga-1", now=NOW)
        assert store.fetch("saga-1").status == IntentStatus.EXECUTING

    def test_enforce_missing_raises_key_error(self):
        store = InMemorySagaStore()
        with pytest.raises(KeyError):
            enforce_timeout(store, "nonexistent", now=NOW)

    def test_heartbeat_timeout_via_enforce(self):
        store = InMemorySagaStore()
        _saga(
            store,
            timeout_policy=SagaTimeoutPolicy.HEARTBEAT,
            heartbeat_interval_ms=3_000,
        )
        last_hb = NOW - timedelta(seconds=10)
        result = enforce_timeout(store, "saga-1", now=NOW, last_heartbeat_at=last_hb)
        assert result is not None
        assert result.status == IntentStatus.FAILED


# ── TestCompensationResult ────────────────────────────────────────────────────

class TestCompensationResult:
    def test_frozen(self):
        r = CompensationResult(success=True)
        with pytest.raises(Exception):
            r.success = False  # type: ignore[misc]

    def test_defaults(self):
        r = CompensationResult(success=True)
        assert r.error_code is None
        assert r.reason is None
        assert r.attempts_used == 0

    def test_failure_fields(self):
        r = CompensationResult(
            success=False,
            error_code="SAGA_POISONED",
            reason="too many attempts",
            attempts_used=3,
        )
        assert r.success is False
        assert r.error_code == "SAGA_POISONED"
        assert r.reason == "too many attempts"
        assert r.attempts_used == 3


# ── TestIsPoisoned ────────────────────────────────────────────────────────────

class TestIsPoisoned:
    def test_not_poisoned_when_below_max(self):
        store = InMemorySagaStore()
        saga = _saga(store, max_compensation_attempts=3)
        assert not is_saga_poisoned(saga)

    def test_poisoned_at_exactly_max(self):
        store = InMemorySagaStore()
        saga = _saga(store, max_compensation_attempts=3)
        from dataclasses import replace as dc_replace
        saga = dc_replace(saga, attempt_count=3)
        assert is_saga_poisoned(saga)

    def test_poisoned_above_max(self):
        store = InMemorySagaStore()
        saga = _saga(store, max_compensation_attempts=2)
        from dataclasses import replace as dc_replace
        saga = dc_replace(saga, attempt_count=5)
        assert is_saga_poisoned(saga)

    def test_not_poisoned_with_one_attempt_used(self):
        store = InMemorySagaStore()
        saga = _saga(store, max_compensation_attempts=3)
        from dataclasses import replace as dc_replace
        saga = dc_replace(saga, attempt_count=1)
        assert not is_saga_poisoned(saga)


# ── TestCompensateSaga ────────────────────────────────────────────────────────

class TestCompensateSagaNone:
    def test_none_strategy_always_succeeds(self):
        store = InMemorySagaStore()
        _saga(store, compensation_strategy=CompensationStrategy.NONE)
        result = compensate_saga(store, "saga-1")
        assert result.success is True

    def test_none_strategy_sets_compensated(self):
        store = InMemorySagaStore()
        _saga(store, compensation_strategy=CompensationStrategy.NONE)
        compensate_saga(store, "saga-1")
        assert store.fetch("saga-1").status == IntentStatus.COMPENSATED

    def test_none_strategy_increments_attempt(self):
        store = InMemorySagaStore()
        _saga(store, compensation_strategy=CompensationStrategy.NONE)
        result = compensate_saga(store, "saga-1")
        assert result.attempts_used == 1

    def test_none_strategy_no_callables_needed(self):
        store = InMemorySagaStore()
        _saga(store, compensation_strategy=CompensationStrategy.NONE)
        # No compensator or saga_handler passed — should not raise
        result = compensate_saga(store, "saga-1")
        assert result.success is True


class TestCompensateSagaManualOnly:
    def test_manual_only_always_fails(self):
        store = InMemorySagaStore()
        _saga(store, compensation_strategy=CompensationStrategy.MANUAL_ONLY)
        result = compensate_saga(store, "saga-1")
        assert result.success is False

    def test_manual_only_error_code(self):
        store = InMemorySagaStore()
        _saga(store, compensation_strategy=CompensationStrategy.MANUAL_ONLY)
        result = compensate_saga(store, "saga-1")
        assert result.error_code == "COMPENSATION_FAILED"

    def test_manual_only_increments_attempt(self):
        store = InMemorySagaStore()
        _saga(store, compensation_strategy=CompensationStrategy.MANUAL_ONLY)
        result = compensate_saga(store, "saga-1")
        assert result.attempts_used == 1

    def test_manual_only_saga_remains_executing(self):
        """Saga status is NOT changed on failed compensation."""
        store = InMemorySagaStore()
        _saga(store, compensation_strategy=CompensationStrategy.MANUAL_ONLY)
        compensate_saga(store, "saga-1")
        # Status remains EXECUTING (failed compensation doesn't auto-fail the saga)
        assert store.fetch("saga-1").status == IntentStatus.EXECUTING


class TestCompensateSagaInverseAction:
    def test_inverse_action_success(self):
        store = InMemorySagaStore()
        _saga(store, steps=["s1", "s2", "s3"],
              compensation_strategy=CompensationStrategy.INVERSE_ACTION)
        compensated = []
        result = compensate_saga(
            store, "saga-1",
            compensator=lambda step_id: not compensated.append(step_id),
        )
        assert result.success is True

    def test_inverse_action_sets_compensated(self):
        store = InMemorySagaStore()
        _saga(store, steps=["s1", "s2"],
              compensation_strategy=CompensationStrategy.INVERSE_ACTION)
        compensate_saga(store, "saga-1", compensator=lambda _: True)
        assert store.fetch("saga-1").status == IntentStatus.COMPENSATED

    def test_inverse_action_compensates_in_reverse(self):
        store = InMemorySagaStore()
        _saga(store, steps=["s1", "s2", "s3"],
              compensation_strategy=CompensationStrategy.INVERSE_ACTION)
        # Advance to step 2 (s3 is current)
        advance_saga_step(store, "saga-1")
        advance_saga_step(store, "saga-1")
        order = []
        compensate_saga(
            store, "saga-1",
            compensator=lambda step_id: not order.append(step_id),
        )
        assert order == ["s3", "s2", "s1"]

    def test_inverse_action_partial_failure(self):
        store = InMemorySagaStore()
        _saga(store, steps=["s1", "s2"],
              compensation_strategy=CompensationStrategy.INVERSE_ACTION)
        result = compensate_saga(
            store, "saga-1",
            compensator=lambda step_id: step_id != "s1",  # s1 fails
        )
        assert result.success is False
        assert result.error_code == "COMPENSATION_FAILED"

    def test_inverse_action_missing_compensator_raises(self):
        store = InMemorySagaStore()
        _saga(store, compensation_strategy=CompensationStrategy.INVERSE_ACTION)
        with pytest.raises(ValueError, match="compensator callable"):
            compensate_saga(store, "saga-1")


class TestCompensateSagaHandler:
    def test_saga_handler_success(self):
        store = InMemorySagaStore()
        _saga(store, compensation_strategy=CompensationStrategy.SAGA_HANDLER)
        result = compensate_saga(store, "saga-1", saga_handler=lambda: True)
        assert result.success is True

    def test_saga_handler_sets_compensated(self):
        store = InMemorySagaStore()
        _saga(store, compensation_strategy=CompensationStrategy.SAGA_HANDLER)
        compensate_saga(store, "saga-1", saga_handler=lambda: True)
        assert store.fetch("saga-1").status == IntentStatus.COMPENSATED

    def test_saga_handler_failure(self):
        store = InMemorySagaStore()
        _saga(store, compensation_strategy=CompensationStrategy.SAGA_HANDLER)
        result = compensate_saga(store, "saga-1", saga_handler=lambda: False)
        assert result.success is False
        assert result.error_code == "COMPENSATION_FAILED"

    def test_saga_handler_missing_callable_raises(self):
        store = InMemorySagaStore()
        _saga(store, compensation_strategy=CompensationStrategy.SAGA_HANDLER)
        with pytest.raises(ValueError, match="saga_handler callable"):
            compensate_saga(store, "saga-1")

    def test_saga_handler_increments_attempt(self):
        store = InMemorySagaStore()
        _saga(store, compensation_strategy=CompensationStrategy.SAGA_HANDLER)
        result = compensate_saga(store, "saga-1", saga_handler=lambda: True)
        assert result.attempts_used == 1


class TestCompensateSagaPoison:
    def test_poison_guard_fires_before_attempt(self):
        store = InMemorySagaStore()
        _saga(store, max_compensation_attempts=2,
              compensation_strategy=CompensationStrategy.NONE)
        # Exhaust attempts
        compensate_saga(store, "saga-1")  # attempt 1
        compensate_saga(store, "saga-1")  # attempt 2 → attempt_count == 2 == max
        # Now poisoned
        result = compensate_saga(store, "saga-1")
        assert result.success is False
        assert result.error_code == "SAGA_POISONED"

    def test_poisoned_attempt_count_not_incremented(self):
        store = InMemorySagaStore()
        _saga(store, max_compensation_attempts=1,
              compensation_strategy=CompensationStrategy.NONE)
        compensate_saga(store, "saga-1")  # attempt_count → 1 == max
        result = compensate_saga(store, "saga-1")
        # attempts_used should reflect the stored count (1), not 2
        assert result.attempts_used == 1

    def test_multiple_successes_increment_count(self):
        """NONE strategy: each call increments attempt_count even on success."""
        store = InMemorySagaStore()
        _saga(store, max_compensation_attempts=5,
              compensation_strategy=CompensationStrategy.NONE)
        for expected_count in range(1, 4):
            # Reset to EXECUTING each time to allow re-compensation
            from dataclasses import replace as dc_replace
            saga = store.fetch("saga-1")
            store.save(dc_replace(saga, status=IntentStatus.EXECUTING))
            result = compensate_saga(store, "saga-1")
            assert result.attempts_used == expected_count

    def test_poison_missing_raises_key_error(self):
        store = InMemorySagaStore()
        with pytest.raises(KeyError):
            compensate_saga(store, "nonexistent")
