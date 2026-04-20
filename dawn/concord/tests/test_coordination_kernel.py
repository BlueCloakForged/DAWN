"""Tests for CONCORD Phase 5 — coordination_kernel.py.

Covers:
- LeaseAcquireResult / TokenAcquireResult / AdmissionResult field contracts
- InMemoryLeaseStore: save, fetch, exists, fetch_active_for_resource
- is_lease_active(): active vs expired-status vs past-expiry
- grant_lease(): success, LEASE_HELD (other session), same-session re-grant
- release_lease(): success, wrong-session rejection, non-active rejection
- revoke_lease(): success, non-active rejection
- renew_lease(): success, wrong-session rejection, non-active case
- InMemoryTokenStore: save, fetch, exists
- is_token_available(): active+slots vs exhausted vs suspended
- acquire_token(): success, idempotent, exhausted, non-active
- acquire_token(): transitions to EXHAUSTED at zero capacity
- release_token(): success, restore-to-ACTIVE from EXHAUSTED, not-a-holder, capacity-overflow
- admit_intent(): admitted clean; denied at each pipeline stage in order
- IntentQueue: enqueue, dequeue, position, remove, depth, peek
- IntentQueue: priority ordering, FIFO within priority, max_depth enforcement
- QueueFullError raised at max_depth
"""

from datetime import datetime, timedelta, timezone

import pytest

from dawn.concord.coordination_kernel import (
    AdmissionResult,
    InMemoryLeaseStore,
    InMemoryTokenStore,
    IntentQueue,
    LeaseAcquireResult,
    LeaseStore,
    QueueFullError,
    TokenAcquireResult,
    TokenStore,
    acquire_token,
    admit_intent,
    grant_lease,
    is_lease_active,
    is_token_available,
    release_lease,
    release_token,
    renew_lease,
    revoke_lease,
)
from dawn.concord.types.entities import (
    AgentClass,
    BudgetLedger,
    BudgetProfile,
    CapabilitySet,
    CircuitBreakerThresholds,
    Intent,
    Lease,
    Token,
)
from dawn.concord.types.contracts import ActionContract
from dawn.concord.types.enums import (
    ActionFamily,
    CircuitState,
    CompensationStrategy,
    ConflictResolutionStrategy,
    ConsistencyProfile,
    CooldownPolicy,
    IntentStatus,
    LeaseStatus,
    LeaseType,
    RiskLevel,
    SessionMode,
    TokenStatus,
    TokenType,
    TripRecoveryPolicy,
    TrustTier,
)

NOW = datetime.now(timezone.utc)
FUTURE = NOW + timedelta(hours=1)
PAST = NOW - timedelta(seconds=1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_lease(
    id="lease-1",
    resource_id="cr-1",
    session_id="session-A",
    lease_type=LeaseType.EDIT,
    status=LeaseStatus.ACTIVE,
    expires_at=None,
) -> Lease:
    return Lease(
        id=id,
        resource_id=resource_id,
        session_id=session_id,
        lease_type=lease_type,
        expires_at=expires_at or FUTURE,
        granted_at=NOW,
        status=status,
    )


def make_token(
    id="token-1",
    resource_id="cr-1",
    capacity=3,
    available_count=3,
    holders=None,
    status=TokenStatus.ACTIVE,
) -> Token:
    return Token(
        id=id,
        token_type=TokenType.CAPACITY,
        resource_id=resource_id,
        capacity=capacity,
        available_count=available_count,
        holders=holders or [],
        issuance_rule="one_per_session",
        status=status,
    )


def make_agent_class(trust_tier=TrustTier.T2_BOUNDED) -> AgentClass:
    return AgentClass(
        id="ac-1", name="ac-1", trust_tier=trust_tier,
        budget_profile_id="bp-1",
    )


def make_capability_set() -> CapabilitySet:
    return CapabilitySet(
        id="cs-1",
        allowed_action_families=["mutate", "read", "approve", "deploy"],
        allowed_resource_types=["change_request"],
    )


def make_action_contract(
    action_family=ActionFamily.MUTATE,
    risk_level=RiskLevel.LOW,
    cost_units=1.0,
) -> ActionContract:
    return ActionContract(
        action_name="update",
        description="test",
        resource_type="change_request",
        action_family=action_family,
        input_schema_ref="s/in",
        output_schema_ref="s/out",
        required_capabilities=[],
        idempotency_required=True,
        risk_level=risk_level,
        consistency_profile=ConsistencyProfile.STRONG,
        conflict_resolution_strategy=ConflictResolutionStrategy.DEFAULT,
        compensation_strategy=CompensationStrategy.INVERSE_ACTION,
        participates_in_saga=False,
        budget_cost_units=cost_units,
    )


def make_profile(burst_limit=100, max_actions_per_minute=60,
                 max_mutating=24, max_high_risk=3, max_cost=100.0) -> BudgetProfile:
    thresholds = CircuitBreakerThresholds(
        stale_version_failure_rate=0.5,
        budget_exceeded_rate=0.5,
        error_rate=0.5,
        evaluation_window_ms=60_000,
        trip_recovery_policy=TripRecoveryPolicy.AUTO_AFTER_COOLDOWN,
    )
    return BudgetProfile(
        id="bp-1",
        max_actions_per_minute=max_actions_per_minute,
        max_mutating_actions_per_hour=max_mutating,
        max_high_risk_per_day=max_high_risk,
        max_cost_units_per_session=max_cost,
        burst_limit=burst_limit,
        circuit_breaker_thresholds=thresholds,
        cooldown_policy=CooldownPolicy.FIXED_BACKOFF,
    )


def make_ledger(circuit_state=CircuitState.CLOSED,
                actions_consumed=0, mutating_consumed=0,
                high_risk_consumed=0, cost_consumed=0.0) -> BudgetLedger:
    return BudgetLedger(
        ledger_id="l-1", session_id="session-A", agent_class_id="ac-1",
        budget_profile_id="bp-1",
        window_start=NOW, window_end=FUTURE,
        actions_consumed=actions_consumed,
        mutating_actions_consumed=mutating_consumed,
        high_risk_actions_consumed=high_risk_consumed,
        cost_units_consumed=cost_consumed,
        parallel_leases_in_use=0, queue_slots_in_use=0,
        circuit_state=circuit_state,
    )


def make_intent(
    id="intent-1",
    session_id="session-A",
    resource_id="cr-1",
    idempotency_key="idem-1",
    status=IntentStatus.PROPOSED,
) -> Intent:
    return Intent(
        id=id,
        session_id=session_id,
        resource_type="change_request",
        resource_id=resource_id,
        action_name="update",
        idempotency_key=idempotency_key,
        status=status,
        consistency_profile=ConsistencyProfile.STRONG,
        risk_level=RiskLevel.LOW,
        participates_in_saga=False,
        created_at=NOW,
    )


@pytest.fixture
def lease_store():
    return InMemoryLeaseStore()


@pytest.fixture
def token_store():
    return InMemoryTokenStore()


# ── Result types ──────────────────────────────────────────────────────────────


class TestResultTypes:
    def test_lease_acquire_result_frozen(self):
        r = LeaseAcquireResult(success=True)
        with pytest.raises((AttributeError, TypeError)):
            r.success = False  # type: ignore

    def test_token_acquire_result_frozen(self):
        r = TokenAcquireResult(success=True)
        with pytest.raises((AttributeError, TypeError)):
            r.success = False  # type: ignore

    def test_admission_result_frozen(self):
        r = AdmissionResult(admitted=True)
        with pytest.raises((AttributeError, TypeError)):
            r.admitted = False  # type: ignore

    def test_abc_lease_store_not_instantiable(self):
        with pytest.raises(TypeError):
            LeaseStore()  # type: ignore

    def test_abc_token_store_not_instantiable(self):
        with pytest.raises(TypeError):
            TokenStore()  # type: ignore


# ── InMemoryLeaseStore ────────────────────────────────────────────────────────


class TestInMemoryLeaseStore:
    def test_save_and_fetch(self, lease_store):
        lease = make_lease()
        lease_store.save(lease)
        fetched = lease_store.fetch("lease-1")
        assert fetched.id == "lease-1"

    def test_fetch_missing_raises(self, lease_store):
        with pytest.raises(KeyError):
            lease_store.fetch("ghost")

    def test_exists_true_after_save(self, lease_store):
        lease_store.save(make_lease())
        assert lease_store.exists("lease-1") is True

    def test_exists_false_before_save(self, lease_store):
        assert lease_store.exists("lease-1") is False

    def test_fetch_returns_deep_copy(self, lease_store):
        lease_store.save(make_lease())
        r1 = lease_store.fetch("lease-1")
        r2 = lease_store.fetch("lease-1")
        assert r1 is not r2

    def test_fetch_active_for_resource(self, lease_store):
        lease_store.save(make_lease(id="l1", resource_id="cr-1", status=LeaseStatus.ACTIVE))
        lease_store.save(make_lease(id="l2", resource_id="cr-1", status=LeaseStatus.RELEASED))
        lease_store.save(make_lease(id="l3", resource_id="cr-2", status=LeaseStatus.ACTIVE))
        active = lease_store.fetch_active_for_resource("cr-1")
        assert len(active) == 1
        assert active[0].id == "l1"

    def test_fetch_active_empty_when_none(self, lease_store):
        assert lease_store.fetch_active_for_resource("cr-1") == []

    def test_len_tracks_count(self, lease_store):
        assert len(lease_store) == 0
        lease_store.save(make_lease())
        assert len(lease_store) == 1


# ── is_lease_active ───────────────────────────────────────────────────────────


class TestIsLeaseActive:
    def test_active_with_future_expiry(self):
        assert is_lease_active(make_lease(status=LeaseStatus.ACTIVE, expires_at=FUTURE)) is True

    def test_active_with_past_expiry_is_false(self):
        assert is_lease_active(make_lease(status=LeaseStatus.ACTIVE, expires_at=PAST)) is False

    def test_released_is_not_active(self):
        assert is_lease_active(make_lease(status=LeaseStatus.RELEASED)) is False

    def test_revoked_is_not_active(self):
        assert is_lease_active(make_lease(status=LeaseStatus.REVOKED)) is False

    def test_expired_status_is_not_active(self):
        assert is_lease_active(make_lease(status=LeaseStatus.EXPIRED)) is False


# ── grant_lease ───────────────────────────────────────────────────────────────


class TestGrantLease:
    def test_grant_succeeds_on_empty_resource(self, lease_store):
        result = grant_lease(
            lease_store, lease_id="l1", resource_id="cr-1",
            session_id="session-A", lease_type=LeaseType.EDIT, duration_ms=60_000,
        )
        assert result.success is True
        assert result.lease.id == "l1"
        assert result.lease.status == LeaseStatus.ACTIVE

    def test_grant_persists_lease(self, lease_store):
        grant_lease(lease_store, lease_id="l1", resource_id="cr-1",
                    session_id="session-A", lease_type=LeaseType.EDIT, duration_ms=60_000)
        assert lease_store.exists("l1")

    def test_grant_blocked_by_other_session(self, lease_store):
        lease_store.save(make_lease(id="l-existing", session_id="session-B"))
        result = grant_lease(
            lease_store, lease_id="l-new", resource_id="cr-1",
            session_id="session-A", lease_type=LeaseType.EDIT, duration_ms=60_000,
        )
        assert result.success is False
        assert result.error_code == "LEASE_HELD"
        assert result.lease.session_id == "session-B"

    def test_grant_allowed_for_same_session(self, lease_store):
        lease_store.save(make_lease(id="l1", session_id="session-A"))
        result = grant_lease(
            lease_store, lease_id="l2", resource_id="cr-1",
            session_id="session-A", lease_type=LeaseType.REVIEW, duration_ms=60_000,
        )
        assert result.success is True

    def test_grant_ignores_released_lease(self, lease_store):
        lease_store.save(make_lease(id="l1", session_id="session-B",
                                    status=LeaseStatus.RELEASED))
        result = grant_lease(
            lease_store, lease_id="l2", resource_id="cr-1",
            session_id="session-A", lease_type=LeaseType.EDIT, duration_ms=60_000,
        )
        assert result.success is True

    def test_grant_sets_purpose(self, lease_store):
        result = grant_lease(
            lease_store, lease_id="l1", resource_id="cr-1",
            session_id="session-A", lease_type=LeaseType.EDIT,
            duration_ms=60_000, purpose="deploy gate",
        )
        assert result.lease.purpose == "deploy gate"


# ── release_lease ─────────────────────────────────────────────────────────────


class TestReleaseLease:
    def test_release_sets_released_status(self, lease_store):
        lease_store.save(make_lease())
        updated = release_lease(lease_store, "lease-1", "session-A")
        assert updated.status == LeaseStatus.RELEASED

    def test_release_wrong_session_raises(self, lease_store):
        lease_store.save(make_lease())
        with pytest.raises(ValueError, match="cannot release"):
            release_lease(lease_store, "lease-1", "session-B")

    def test_release_non_active_raises(self, lease_store):
        lease_store.save(make_lease(status=LeaseStatus.RELEASED))
        with pytest.raises(ValueError, match="not active"):
            release_lease(lease_store, "lease-1", "session-A")

    def test_release_missing_raises_key_error(self, lease_store):
        with pytest.raises(KeyError):
            release_lease(lease_store, "ghost", "session-A")


# ── revoke_lease ──────────────────────────────────────────────────────────────


class TestRevokeLease:
    def test_revoke_sets_revoked_status(self, lease_store):
        lease_store.save(make_lease())
        updated = revoke_lease(lease_store, "lease-1")
        assert updated.status == LeaseStatus.REVOKED

    def test_revoke_non_active_raises(self, lease_store):
        lease_store.save(make_lease(status=LeaseStatus.RELEASED))
        with pytest.raises(ValueError, match="not active"):
            revoke_lease(lease_store, "lease-1")

    def test_revoke_missing_raises_key_error(self, lease_store):
        with pytest.raises(KeyError):
            revoke_lease(lease_store, "ghost")


# ── renew_lease ───────────────────────────────────────────────────────────────


class TestRenewLease:
    def test_renew_extends_expiry(self, lease_store):
        lease_store.save(make_lease())
        result = renew_lease(lease_store, "lease-1", "session-A", 30_000)
        assert result.success is True
        assert result.lease.renewal_count == 1

    def test_renew_wrong_session_raises(self, lease_store):
        lease_store.save(make_lease())
        with pytest.raises(ValueError, match="cannot renew"):
            renew_lease(lease_store, "lease-1", "session-B", 30_000)

    def test_renew_non_active_returns_failure(self, lease_store):
        lease_store.save(make_lease(status=LeaseStatus.RELEASED))
        result = renew_lease(lease_store, "lease-1", "session-A", 30_000)
        assert result.success is False

    def test_renew_increments_renewal_count(self, lease_store):
        lease_store.save(make_lease())
        renew_lease(lease_store, "lease-1", "session-A", 30_000)
        result = renew_lease(lease_store, "lease-1", "session-A", 30_000)
        assert result.lease.renewal_count == 2


# ── Token store ───────────────────────────────────────────────────────────────


class TestInMemoryTokenStore:
    def test_save_and_fetch(self, token_store):
        token_store.save(make_token())
        t = token_store.fetch("token-1")
        assert t.id == "token-1"

    def test_fetch_missing_raises(self, token_store):
        with pytest.raises(KeyError):
            token_store.fetch("ghost")

    def test_exists(self, token_store):
        assert token_store.exists("token-1") is False
        token_store.save(make_token())
        assert token_store.exists("token-1") is True


# ── is_token_available ────────────────────────────────────────────────────────


class TestIsTokenAvailable:
    def test_active_with_slots(self):
        assert is_token_available(make_token(available_count=1)) is True

    def test_active_zero_slots(self):
        assert is_token_available(make_token(available_count=0)) is False

    def test_exhausted_status(self):
        assert is_token_available(make_token(status=TokenStatus.EXHAUSTED)) is False

    def test_suspended_status(self):
        assert is_token_available(make_token(status=TokenStatus.SUSPENDED)) is False


# ── acquire_token ─────────────────────────────────────────────────────────────


class TestAcquireToken:
    def test_acquire_success(self, token_store):
        token_store.save(make_token(available_count=3))
        result = acquire_token(token_store, "token-1", "session-A")
        assert result.success is True
        assert result.token.available_count == 2
        assert "session-A" in result.token.holders

    def test_acquire_decrements_available(self, token_store):
        token_store.save(make_token(available_count=2))
        acquire_token(token_store, "token-1", "session-A")
        t = token_store.fetch("token-1")
        assert t.available_count == 1

    def test_acquire_transitions_to_exhausted_at_zero(self, token_store):
        token_store.save(make_token(capacity=1, available_count=1))
        result = acquire_token(token_store, "token-1", "session-A")
        assert result.token.status == TokenStatus.EXHAUSTED
        assert result.token.available_count == 0

    def test_acquire_idempotent_if_already_holder(self, token_store):
        token_store.save(make_token(available_count=2, holders=["session-A"]))
        result = acquire_token(token_store, "token-1", "session-A")
        assert result.success is True
        t = token_store.fetch("token-1")
        assert t.available_count == 2  # not decremented again

    def test_acquire_fails_when_exhausted(self, token_store):
        token_store.save(make_token(available_count=0, status=TokenStatus.EXHAUSTED))
        result = acquire_token(token_store, "token-1", "session-A")
        assert result.success is False
        assert result.error_code == "CAPACITY_EXHAUSTED"

    def test_acquire_fails_when_non_active(self, token_store):
        token_store.save(make_token(status=TokenStatus.SUSPENDED))
        result = acquire_token(token_store, "token-1", "session-A")
        assert result.success is False
        assert result.error_code == "QUORUM_INCOMPLETE"

    def test_acquire_missing_raises_key_error(self, token_store):
        with pytest.raises(KeyError):
            acquire_token(token_store, "ghost", "session-A")


# ── release_token ─────────────────────────────────────────────────────────────


class TestReleaseToken:
    def test_release_increments_available(self, token_store):
        token_store.save(make_token(available_count=1, holders=["session-A"]))
        updated = release_token(token_store, "token-1", "session-A")
        assert updated.available_count == 2
        assert "session-A" not in updated.holders

    def test_release_from_exhausted_restores_active(self, token_store):
        token_store.save(make_token(
            capacity=1, available_count=0, holders=["session-A"],
            status=TokenStatus.EXHAUSTED,
        ))
        updated = release_token(token_store, "token-1", "session-A")
        assert updated.status == TokenStatus.ACTIVE
        assert updated.available_count == 1

    def test_release_not_holder_raises(self, token_store):
        token_store.save(make_token(available_count=2, holders=["session-B"]))
        with pytest.raises(ValueError, match="does not hold"):
            release_token(token_store, "token-1", "session-A")

    def test_release_would_exceed_capacity_raises(self, token_store):
        # Artificially corrupt state: available_count == capacity, but holder present
        token_store.save(make_token(capacity=2, available_count=2, holders=["session-A"]))
        with pytest.raises(ValueError, match="exceed capacity"):
            release_token(token_store, "token-1", "session-A")

    def test_release_missing_raises_key_error(self, token_store):
        with pytest.raises(KeyError):
            release_token(token_store, "ghost", "session-A")


# ── admit_intent ──────────────────────────────────────────────────────────────


class TestAdmitIntent:
    def _admit(
        self,
        intent=None,
        agent_class=None,
        cap_sets=None,
        contract=None,
        profile=None,
        ledger=None,
        active_leases=None,
        existing_intents=None,
    ) -> AdmissionResult:
        return admit_intent(
            intent or make_intent(),
            agent_class=agent_class or make_agent_class(),
            capability_sets=cap_sets or [make_capability_set()],
            action_contract=contract or make_action_contract(),
            profile=profile or make_profile(),
            ledger=ledger or make_ledger(),
            active_leases=active_leases or [],
            existing_intents=existing_intents or [],
        )

    def test_admitted_clean(self):
        result = self._admit()
        assert result.admitted is True
        assert result.error_code is None

    def test_denied_capability(self):
        no_cap = CapabilitySet(id="cs-empty",
                               allowed_action_families=["read"],
                               allowed_resource_types=["change_request"])
        result = self._admit(cap_sets=[no_cap])
        assert result.admitted is False
        assert result.error_code == "NOT_AUTHORIZED_FOR_AGENT_CLASS"

    def test_denied_circuit_open(self):
        ledger = make_ledger(circuit_state=CircuitState.OPEN)
        result = self._admit(ledger=ledger)
        assert result.admitted is False
        assert result.error_code == "CIRCUIT_OPEN"

    def test_denied_burst_limit(self):
        profile = make_profile(burst_limit=0)
        result = self._admit(profile=profile)
        assert result.admitted is False
        assert result.error_code == "BUDGET_EXCEEDED"

    def test_denied_rate_limit(self):
        profile = make_profile(max_actions_per_minute=5)
        ledger = make_ledger(actions_consumed=5)
        result = self._admit(profile=profile, ledger=ledger)
        assert result.admitted is False
        assert result.error_code == "BUDGET_EXCEEDED"

    def test_denied_duplicate_intent(self):
        existing = make_intent(id="intent-2", idempotency_key="idem-1",
                               status=IntentStatus.ADMITTED)
        result = self._admit(existing_intents=[existing])
        assert result.admitted is False
        assert result.error_code == "DUPLICATE_INTENT"

    def test_duplicate_terminal_intent_not_blocked(self):
        # Same key but terminal — not a duplicate
        existing = make_intent(id="intent-2", idempotency_key="idem-1",
                               status=IntentStatus.COMMITTED)
        result = self._admit(existing_intents=[existing])
        assert result.admitted is True

    def test_denied_lease_held_by_other_session(self):
        blocking_lease = make_lease(session_id="session-B")
        result = self._admit(active_leases=[blocking_lease])
        assert result.admitted is False
        assert result.error_code == "LEASE_HELD"
        assert result.requires_queue is True

    def test_lease_from_same_session_not_blocking(self):
        own_lease = make_lease(session_id="session-A")
        result = self._admit(active_leases=[own_lease])
        assert result.admitted is True

    def test_expired_lease_not_blocking(self):
        expired_lease = make_lease(session_id="session-B", expires_at=PAST)
        result = self._admit(active_leases=[expired_lease])
        assert result.admitted is True

    def test_capability_checked_before_budget(self):
        # Both capability and budget fail — capability should be reported
        no_cap = CapabilitySet(id="cs-empty", allowed_action_families=[],
                               allowed_resource_types=[])
        ledger = make_ledger(circuit_state=CircuitState.OPEN)
        result = self._admit(cap_sets=[no_cap], ledger=ledger)
        assert result.error_code == "NOT_AUTHORIZED_FOR_AGENT_CLASS"

    def test_budget_checked_before_lease(self):
        # Both budget and lease fail — budget reported first
        ledger = make_ledger(circuit_state=CircuitState.OPEN)
        blocking_lease = make_lease(session_id="session-B")
        result = self._admit(ledger=ledger, active_leases=[blocking_lease])
        assert result.error_code == "CIRCUIT_OPEN"


# ── IntentQueue ───────────────────────────────────────────────────────────────


class TestIntentQueue:
    def test_enqueue_returns_position_1(self):
        q = IntentQueue()
        pos = q.enqueue("i1", "cr-1")
        assert pos == 1

    def test_enqueue_two_same_resource(self):
        q = IntentQueue()
        q.enqueue("i1", "cr-1")
        pos = q.enqueue("i2", "cr-1")
        assert pos == 2

    def test_dequeue_returns_first_enqueued(self):
        q = IntentQueue()
        q.enqueue("i1", "cr-1")
        q.enqueue("i2", "cr-1")
        assert q.dequeue("cr-1") == "i1"

    def test_dequeue_empty_returns_none(self):
        q = IntentQueue()
        assert q.dequeue("cr-1") is None

    def test_depth_tracks_queue_length(self):
        q = IntentQueue()
        assert q.depth("cr-1") == 0
        q.enqueue("i1", "cr-1")
        assert q.depth("cr-1") == 1
        q.dequeue("cr-1")
        assert q.depth("cr-1") == 0

    def test_peek_returns_head_without_removing(self):
        q = IntentQueue()
        q.enqueue("i1", "cr-1")
        q.enqueue("i2", "cr-1")
        assert q.peek("cr-1") == "i1"
        assert q.depth("cr-1") == 2

    def test_peek_empty_returns_none(self):
        assert IntentQueue().peek("cr-1") is None

    def test_remove_intent(self):
        q = IntentQueue()
        q.enqueue("i1", "cr-1")
        q.enqueue("i2", "cr-1")
        assert q.remove("i2") is True
        assert q.depth("cr-1") == 1

    def test_remove_returns_false_if_not_queued(self):
        q = IntentQueue()
        assert q.remove("ghost") is False

    def test_position_returns_none_after_dequeue(self):
        q = IntentQueue()
        q.enqueue("i1", "cr-1")
        q.dequeue("cr-1")
        assert q.position("i1") is None

    def test_position_after_remove(self):
        q = IntentQueue()
        q.enqueue("i1", "cr-1")
        q.remove("i1")
        assert q.position("i1") is None

    def test_duplicate_enqueue_raises(self):
        q = IntentQueue()
        q.enqueue("i1", "cr-1")
        with pytest.raises(ValueError, match="already in the queue"):
            q.enqueue("i1", "cr-1")

    def test_max_depth_raises_queue_full(self):
        q = IntentQueue()
        q.enqueue("i1", "cr-1", max_depth=2)
        q.enqueue("i2", "cr-1", max_depth=2)
        with pytest.raises(QueueFullError):
            q.enqueue("i3", "cr-1", max_depth=2)

    def test_max_depth_none_is_unlimited(self):
        q = IntentQueue()
        for i in range(100):
            q.enqueue(f"i{i}", "cr-1", max_depth=None)
        assert q.depth("cr-1") == 100

    def test_priority_higher_dequeued_first(self):
        q = IntentQueue()
        q.enqueue("low", "cr-1", priority=0)
        q.enqueue("high", "cr-1", priority=10)
        assert q.dequeue("cr-1") == "high"

    def test_fifo_within_equal_priority(self):
        q = IntentQueue()
        q.enqueue("first", "cr-1", priority=5)
        q.enqueue("second", "cr-1", priority=5)
        assert q.dequeue("cr-1") == "first"

    def test_priority_position_reflects_order(self):
        q = IntentQueue()
        q.enqueue("low", "cr-1", priority=0)
        q.enqueue("high", "cr-1", priority=10)
        # high-priority intent should be at position 1
        assert q.position("high") == 1
        assert q.position("low") == 2

    def test_queues_are_per_resource(self):
        q = IntentQueue()
        q.enqueue("i1", "cr-1")
        q.enqueue("i2", "cr-2")
        assert q.depth("cr-1") == 1
        assert q.depth("cr-2") == 1
        assert q.dequeue("cr-1") == "i1"
        assert q.dequeue("cr-2") == "i2"

    def test_full_dequeue_sequence(self):
        q = IntentQueue()
        q.enqueue("i1", "cr-1", priority=0)
        q.enqueue("i2", "cr-1", priority=5)
        q.enqueue("i3", "cr-1", priority=5)
        assert q.dequeue("cr-1") == "i2"  # highest priority, first enqueued
        assert q.dequeue("cr-1") == "i3"
        assert q.dequeue("cr-1") == "i1"
        assert q.dequeue("cr-1") is None
