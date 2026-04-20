"""Tests for CONCORD Phase 7 — context_kernel.py.

Coverage:
  - compute_freshness (all 5 consistency profiles + boundary conditions)
  - compute_budget_remaining (all four dimensions, floor-clamped)
  - is_context_stale (within / at / past TTL)
  - assemble_context:
      · resource read + freshness propagation
      · allowed/blocked action derivation from state machine
      · budget gateway blocking all actions when circuit open / cooldown
      · BlockedReason entries for state-blocked actions
      · BlockedReason entry for LEASE_HELD by other session
      · pending intents from other sessions surfaced
      · pending intents from same session excluded
      · recommended_next_action / safe_parallel_actions
      · requires_authoritative_recheck logic
      · authoritative_for_mutation always False
      · no StateContract → allowed_actions = all registered
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from dawn.concord.context_kernel import (
    assemble_context,
    compute_budget_remaining,
    compute_freshness,
    is_context_stale,
)
from dawn.concord.contracts_kernel import ContractRegistry, load_action_contract, load_state_contract
from dawn.concord.resource_kernel import InMemoryResourceRepository
from dawn.concord.types.entities import (
    BudgetLedger,
    BudgetProfile,
    CircuitBreakerThresholds,
    Intent,
    Lease,
    OperationContext,
    Resource,
)
from dawn.concord.types.enums import (
    CircuitState,
    ConsistencyProfile,
    CooldownPolicy,
    FreshnessStatus,
    IntentStatus,
    LeaseStatus,
    LeaseType,
    RiskLevel,
    TripRecoveryPolicy,
)

# ── Shared timestamps ─────────────────────────────────────────────────────────

NOW = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)
FUTURE = NOW + timedelta(hours=1)

# ── Canonical change_request action/state contract fixtures ───────────────────

def _ac(name: str, family: str, allowed_from: list[str], transitions_to: Optional[str]) -> dict:
    return {
        "resource_type": "change_request",
        "action_name": name,
        "action_family": family,
        "consistency_profile": "STRONG",
        "risk_level": "low",
        "idempotency_required": True,
        "participates_in_saga": False,
        "guard_predicates": [],
        "side_effects": [],
        "allowed_from_states": allowed_from,
        "transitions_to_state": transitions_to,
        "budget_cost_units": 1.0,
        "budget_dimensions_consumed": [],
        "compensation_strategy": "none",
        "retry_class": "safe_retry",
        "authoritative_recheck_required": False,
        "description": f"Action {name}",
        "input_schema_ref": f"#/{name}_input",
        "output_schema_ref": f"#/{name}_output",
        "required_capabilities": [],
        "conflict_resolution_strategy": "default",
    }


_CR_ACTIONS = [
    _ac("update",               "mutate",  ["draft"],        "draft"),
    _ac("submit",               "mutate",  ["draft"],        "submitted"),
    _ac("read_change_request",  "read",    ["draft", "submitted", "under_review"], None),
    _ac("approve",              "approve", ["under_review"], "approved"),
]

_CR_STATE_CONTRACT = {
    "resource_type": "change_request",
    "initial_state": "draft",
    "terminal_states": ["approved"],
    "states": [
        {"name": "draft",        "description": "Initial",    "is_terminal": False,
         "allowed_action_refs": ["update", "submit", "read_change_request"]},
        {"name": "submitted",    "description": "Submitted",  "is_terminal": False,
         "allowed_action_refs": ["read_change_request"]},
        {"name": "under_review", "description": "In review",  "is_terminal": False,
         "allowed_action_refs": ["approve", "read_change_request"]},
        {"name": "approved",     "description": "Approved",   "is_terminal": True,
         "allowed_action_refs": []},
    ],
    "transitions": [
        {"name": "to_submitted",   "from_state": "draft",        "to_state": "submitted",    "action_ref": "submit"},
        {"name": "stay_draft",     "from_state": "draft",        "to_state": "draft",         "action_ref": "update"},
        {"name": "to_approved",    "from_state": "under_review", "to_state": "approved",      "action_ref": "approve"},
    ],
    "rollback_rules": [], "entry_hooks": [], "exit_hooks": [],
}


def _make_registry(*, with_state_contract: bool = True) -> ContractRegistry:
    reg = ContractRegistry()
    for data in _CR_ACTIONS:
        reg.register_action(load_action_contract(data))
    if with_state_contract:
        reg.register_state(load_state_contract(_CR_STATE_CONTRACT))
    return reg


def _make_repo(*, state: str = "draft", version: int = 1) -> InMemoryResourceRepository:
    repo = InMemoryResourceRepository()
    repo.create(Resource(
        id="cr-1", resource_type="change_request",
        business_state={"status": state}, coordination_state={},
        version=version, created_at=NOW, updated_at=NOW,
    ))
    return repo


_CBT = CircuitBreakerThresholds(
    stale_version_failure_rate=0.5,
    budget_exceeded_rate=0.5,
    error_rate=0.5,
    evaluation_window_ms=60_000,
    trip_recovery_policy=TripRecoveryPolicy.AUTO_AFTER_COOLDOWN,
)


def _make_profile(
    *,
    burst_limit: int = 10,
    max_actions_per_minute: int = 60,
    max_mutating_actions_per_hour: int = 24,
    max_high_risk_per_day: int = 3,
    max_cost_units_per_session: float = 40.0,
) -> BudgetProfile:
    return BudgetProfile(
        id="prof-default",
        max_actions_per_minute=max_actions_per_minute,
        max_mutating_actions_per_hour=max_mutating_actions_per_hour,
        max_high_risk_per_day=max_high_risk_per_day,
        max_cost_units_per_session=max_cost_units_per_session,
        burst_limit=burst_limit,
        circuit_breaker_thresholds=_CBT,
        cooldown_policy=CooldownPolicy.FIXED_BACKOFF,
    )


def _make_ledger(
    *,
    actions_consumed: int = 0,
    mutating_actions_consumed: int = 0,
    high_risk_actions_consumed: int = 0,
    cost_units_consumed: float = 0.0,
    circuit_state: CircuitState = CircuitState.CLOSED,
    cooldown_until: Optional[datetime] = None,
) -> BudgetLedger:
    return BudgetLedger(
        ledger_id="ledger-1",
        session_id="sess-1",
        agent_class_id="cls-default",
        budget_profile_id="prof-default",
        window_start=NOW,
        window_end=FUTURE,
        actions_consumed=actions_consumed,
        mutating_actions_consumed=mutating_actions_consumed,
        high_risk_actions_consumed=high_risk_actions_consumed,
        cost_units_consumed=cost_units_consumed,
        parallel_leases_in_use=0,
        queue_slots_in_use=0,
        circuit_state=circuit_state,
        cooldown_until=cooldown_until,
    )


def _make_lease(
    *,
    session_id: str = "sess-other",
    status: LeaseStatus = LeaseStatus.ACTIVE,
) -> Lease:
    return Lease(
        id="lease-1", resource_id="cr-1", session_id=session_id,
        lease_type=LeaseType.EDIT, expires_at=FUTURE,
        granted_at=NOW, status=status,
    )


def _make_intent(
    *,
    id: str = "intent-1",
    session_id: str = "sess-other",
    status: IntentStatus = IntentStatus.EXECUTING,
) -> Intent:
    return Intent(
        id=id, session_id=session_id,
        resource_type="change_request", resource_id="cr-1",
        action_name="update", idempotency_key=f"idem-{id}",
        status=status,
        consistency_profile=ConsistencyProfile.STRONG,
        risk_level=RiskLevel.LOW,
        participates_in_saga=False,
        created_at=NOW,
    )


# ── TestComputeFreshness ──────────────────────────────────────────────────────

class TestComputeFreshness:
    def _res(self, version: int = 5) -> Resource:
        return Resource(
            id="r1", resource_type="t", business_state={},
            coordination_state={}, version=version,
            created_at=NOW, updated_at=NOW,
        )

    def test_strong_always_fresh(self):
        assert compute_freshness(ConsistencyProfile.STRONG, self._res()) == FreshnessStatus.FRESH

    def test_session_monotonic_fresh_when_version_meets_watermark(self):
        assert compute_freshness(
            ConsistencyProfile.SESSION_MONOTONIC, self._res(5), session_watermark=5
        ) == FreshnessStatus.FRESH

    def test_session_monotonic_fresh_when_version_exceeds_watermark(self):
        assert compute_freshness(
            ConsistencyProfile.SESSION_MONOTONIC, self._res(7), session_watermark=5
        ) == FreshnessStatus.FRESH

    def test_session_monotonic_stale_when_version_below_watermark(self):
        assert compute_freshness(
            ConsistencyProfile.SESSION_MONOTONIC, self._res(3), session_watermark=5
        ) == FreshnessStatus.STALE

    def test_session_monotonic_fresh_when_no_watermark(self):
        assert compute_freshness(
            ConsistencyProfile.SESSION_MONOTONIC, self._res(1)
        ) == FreshnessStatus.FRESH

    def test_read_your_writes_fresh_when_version_meets_min(self):
        assert compute_freshness(
            ConsistencyProfile.READ_YOUR_WRITES, self._res(5), min_version=5
        ) == FreshnessStatus.FRESH

    def test_read_your_writes_warning_when_version_below_min(self):
        assert compute_freshness(
            ConsistencyProfile.READ_YOUR_WRITES, self._res(3), min_version=5
        ) == FreshnessStatus.WARNING

    def test_read_your_writes_fresh_when_no_min_version(self):
        assert compute_freshness(
            ConsistencyProfile.READ_YOUR_WRITES, self._res(1)
        ) == FreshnessStatus.FRESH

    def test_eventual_always_warning(self):
        assert compute_freshness(ConsistencyProfile.EVENTUAL, self._res()) == FreshnessStatus.WARNING

    def test_async_projection_fresh_within_tolerance(self):
        assert compute_freshness(
            ConsistencyProfile.ASYNC_PROJECTION, self._res(),
            projection_lag_ms=100, projection_tolerance_ms=500,
        ) == FreshnessStatus.FRESH

    def test_async_projection_warning_when_lag_exceeds_tolerance(self):
        assert compute_freshness(
            ConsistencyProfile.ASYNC_PROJECTION, self._res(),
            projection_lag_ms=600, projection_tolerance_ms=500,
        ) == FreshnessStatus.WARNING

    def test_async_projection_fresh_when_no_lag_provided(self):
        assert compute_freshness(
            ConsistencyProfile.ASYNC_PROJECTION, self._res()
        ) == FreshnessStatus.FRESH

    def test_async_projection_exactly_at_tolerance_is_fresh(self):
        assert compute_freshness(
            ConsistencyProfile.ASYNC_PROJECTION, self._res(),
            projection_lag_ms=500, projection_tolerance_ms=500,
        ) == FreshnessStatus.FRESH


# ── TestComputeBudgetRemaining ────────────────────────────────────────────────

class TestComputeBudgetRemaining:
    def test_all_zero_consumed_returns_full(self):
        p = _make_profile(max_actions_per_minute=60, max_mutating_actions_per_hour=24,
                          max_high_risk_per_day=3, max_cost_units_per_session=40.0)
        r = compute_budget_remaining(p, _make_ledger())
        assert r["cost_units"] == 40.0
        assert r["actions_per_minute"] == 60.0
        assert r["mutating_actions_per_hour"] == 24.0
        assert r["high_risk_actions_today"] == 3.0

    def test_partially_consumed(self):
        p = _make_profile(max_cost_units_per_session=40.0, max_actions_per_minute=60,
                          max_mutating_actions_per_hour=24, max_high_risk_per_day=3)
        r = compute_budget_remaining(p, _make_ledger(
            cost_units_consumed=10.0, actions_consumed=5,
            mutating_actions_consumed=2, high_risk_actions_consumed=1,
        ))
        assert r["cost_units"] == 30.0
        assert r["actions_per_minute"] == 55.0
        assert r["mutating_actions_per_hour"] == 22.0
        assert r["high_risk_actions_today"] == 2.0

    def test_over_consumed_floors_to_zero(self):
        p = _make_profile(max_cost_units_per_session=5.0, max_actions_per_minute=2,
                          max_mutating_actions_per_hour=1, max_high_risk_per_day=0)
        r = compute_budget_remaining(p, _make_ledger(
            cost_units_consumed=10.0, actions_consumed=5,
            mutating_actions_consumed=3, high_risk_actions_consumed=1,
        ))
        assert r["cost_units"] == 0.0
        assert r["actions_per_minute"] == 0.0
        assert r["mutating_actions_per_hour"] == 0.0
        assert r["high_risk_actions_today"] == 0.0


# ── TestIsContextStale ────────────────────────────────────────────────────────

class TestIsContextStale:
    def _ctx(self, *, assembled_at: datetime, ttl_ms: int) -> OperationContext:
        return OperationContext(
            resource_id="cr-1",
            resource=Resource(
                id="cr-1", resource_type="cr", business_state={"status": "draft"},
                coordination_state={}, version=1, created_at=NOW, updated_at=NOW,
            ),
            allowed_actions=[], blocked_actions=[], blocked_reasons=[],
            active_leases=[], pending_intents=[], budget_remaining={},
            freshness_status=FreshnessStatus.FRESH,
            context_assembled_at=assembled_at, context_ttl_ms=ttl_ms,
        )

    def test_within_ttl_not_stale(self):
        ctx = self._ctx(assembled_at=NOW - timedelta(seconds=2), ttl_ms=5_000)
        assert not is_context_stale(ctx, now=NOW)

    def test_exactly_at_ttl_is_stale(self):
        ctx = self._ctx(assembled_at=NOW - timedelta(seconds=5), ttl_ms=5_000)
        assert is_context_stale(ctx, now=NOW)

    def test_past_ttl_is_stale(self):
        ctx = self._ctx(assembled_at=NOW - timedelta(seconds=10), ttl_ms=5_000)
        assert is_context_stale(ctx, now=NOW)

    def test_defaults_to_utcnow(self):
        ctx = self._ctx(assembled_at=datetime.now(timezone.utc), ttl_ms=10_000)
        assert not is_context_stale(ctx)


# ── TestAssembleContext ───────────────────────────────────────────────────────

def _assemble(
    *,
    state: str = "draft",
    session_id: str = "sess-1",
    leases: Optional[list] = None,
    intents: Optional[list] = None,
    circuit_state: CircuitState = CircuitState.CLOSED,
    cooldown_until: Optional[datetime] = None,
    actions_consumed: int = 0,
    burst_limit: int = 10,
    consistency_profile: ConsistencyProfile = ConsistencyProfile.STRONG,
    projection_lag_ms: Optional[int] = None,
    projection_tolerance_ms: Optional[int] = None,
    with_state_contract: bool = True,
    context_ttl_ms: int = 5_000,
):
    reg = _make_registry(with_state_contract=with_state_contract)
    repo = _make_repo(state=state)
    return assemble_context(
        repo, reg,
        resource_id="cr-1",
        resource_type="change_request",
        requesting_session_id=session_id,
        budget_profile=_make_profile(burst_limit=burst_limit),
        budget_ledger=_make_ledger(
            circuit_state=circuit_state,
            cooldown_until=cooldown_until,
            actions_consumed=actions_consumed,
        ),
        active_leases=leases or [],
        existing_intents=intents or [],
        consistency_profile=consistency_profile,
        projection_lag_ms=projection_lag_ms,
        projection_tolerance_ms=projection_tolerance_ms,
        context_ttl_ms=context_ttl_ms,
        now=NOW,
    )


class TestAssembleContextBasic:
    def test_returns_operation_context(self):
        assert isinstance(_assemble(), OperationContext)

    def test_authoritative_for_mutation_always_false(self):
        assert _assemble().authoritative_for_mutation is False

    def test_resource_id(self):
        assert _assemble().resource_id == "cr-1"

    def test_resource_type(self):
        assert _assemble().resource.resource_type == "change_request"

    def test_context_assembled_at_set(self):
        assert _assemble().context_assembled_at == NOW

    def test_context_ttl_ms_forwarded(self):
        assert _assemble(context_ttl_ms=10_000).context_ttl_ms == 10_000

    def test_missing_resource_raises_key_error(self):
        reg = _make_registry()
        repo = InMemoryResourceRepository()  # empty
        with pytest.raises(KeyError):
            assemble_context(
                repo, reg,
                resource_id="cr-1", resource_type="change_request",
                requesting_session_id="sess-1",
                budget_profile=_make_profile(),
                budget_ledger=_make_ledger(),
                active_leases=[], existing_intents=[],
                now=NOW,
            )


class TestAssembleContextAllowedBlocked:
    def test_draft_allows_update_submit_read(self):
        ctx = _assemble(state="draft")
        assert "update" in ctx.allowed_actions
        assert "submit" in ctx.allowed_actions
        assert "read_change_request" in ctx.allowed_actions

    def test_draft_blocks_approve(self):
        ctx = _assemble(state="draft")
        assert "approve" in ctx.blocked_actions
        assert "approve" not in ctx.allowed_actions

    def test_under_review_allows_approve(self):
        ctx = _assemble(state="under_review")
        assert "approve" in ctx.allowed_actions

    def test_under_review_blocks_update_and_submit(self):
        ctx = _assemble(state="under_review")
        assert "update" in ctx.blocked_actions
        assert "submit" in ctx.blocked_actions

    def test_no_state_contract_all_actions_allowed(self):
        ctx = _assemble(with_state_contract=False)
        assert set(ctx.allowed_actions) == {"update", "submit", "read_change_request", "approve"}
        assert ctx.blocked_actions == []

    def test_blocked_reasons_cite_policy_blocked(self):
        ctx = _assemble(state="draft")
        codes = {br.reason_code for br in ctx.blocked_reasons}
        assert "POLICY_BLOCKED" in codes

    def test_blocked_reason_has_non_empty_unblock_condition(self):
        ctx = _assemble(state="draft")
        for br in ctx.blocked_reasons:
            assert isinstance(br.unblock_condition, str) and len(br.unblock_condition) > 0


class TestAssembleContextBudgetGate:
    def test_circuit_open_blocks_all_actions(self):
        ctx = _assemble(circuit_state=CircuitState.OPEN)
        assert ctx.allowed_actions == []
        assert len(ctx.blocked_actions) > 0

    def test_circuit_open_blocked_reasons_cite_circuit_open(self):
        ctx = _assemble(circuit_state=CircuitState.OPEN)
        codes = {br.reason_code for br in ctx.blocked_reasons}
        assert "CIRCUIT_OPEN" in codes

    def test_cooldown_active_blocks_all_actions(self):
        ctx = _assemble(cooldown_until=FUTURE)
        assert ctx.allowed_actions == []

    def test_normal_budget_does_not_block(self):
        ctx = _assemble(burst_limit=100, actions_consumed=1)
        assert len(ctx.allowed_actions) > 0


class TestAssembleContextLease:
    def test_other_session_active_lease_adds_lease_held_reason(self):
        ctx = _assemble(
            session_id="sess-requesting",
            leases=[_make_lease(session_id="sess-other")],
        )
        codes = {br.reason_code for br in ctx.blocked_reasons}
        assert "LEASE_HELD" in codes

    def test_same_session_lease_no_lease_held_reason(self):
        ctx = _assemble(
            session_id="sess-1",
            leases=[_make_lease(session_id="sess-1")],
        )
        codes = {br.reason_code for br in ctx.blocked_reasons}
        assert "LEASE_HELD" not in codes

    def test_released_lease_not_flagged(self):
        ctx = _assemble(
            session_id="sess-1",
            leases=[_make_lease(session_id="sess-other", status=LeaseStatus.RELEASED)],
        )
        codes = {br.reason_code for br in ctx.blocked_reasons}
        assert "LEASE_HELD" not in codes

    def test_other_session_lease_triggers_authoritative_recheck(self):
        ctx = _assemble(
            session_id="sess-1",
            leases=[_make_lease(session_id="sess-other")],
        )
        assert ctx.requires_authoritative_recheck is True

    def test_active_leases_forwarded_to_context(self):
        lease = _make_lease(session_id="sess-1")
        ctx = _assemble(session_id="sess-1", leases=[lease])
        assert len(ctx.active_leases) == 1
        assert ctx.active_leases[0].id == "lease-1"


class TestAssembleContextPendingIntents:
    def test_other_session_executing_intent_in_pending(self):
        intent = _make_intent(session_id="sess-other", status=IntentStatus.EXECUTING)
        ctx = _assemble(session_id="sess-1", intents=[intent])
        assert "intent-1" in ctx.pending_intents

    def test_same_session_intent_excluded(self):
        intent = _make_intent(session_id="sess-1", status=IntentStatus.EXECUTING)
        ctx = _assemble(session_id="sess-1", intents=[intent])
        assert "intent-1" not in ctx.pending_intents

    def test_terminal_other_session_intent_excluded(self):
        intent = _make_intent(session_id="sess-other", status=IntentStatus.COMMITTED)
        ctx = _assemble(session_id="sess-1", intents=[intent])
        assert "intent-1" not in ctx.pending_intents

    def test_no_intents_empty_pending(self):
        ctx = _assemble()
        assert ctx.pending_intents == []

    def test_multiple_other_session_intents(self):
        intents = [
            _make_intent(id="i1", session_id="sess-other", status=IntentStatus.QUEUED),
            _make_intent(id="i2", session_id="sess-other", status=IntentStatus.ADMITTED),
        ]
        ctx = _assemble(session_id="sess-1", intents=intents)
        assert "i1" in ctx.pending_intents
        assert "i2" in ctx.pending_intents


class TestAssembleContextDerivedFields:
    def test_recommended_next_action_in_allowed(self):
        ctx = _assemble()
        assert ctx.recommended_next_action in ctx.allowed_actions

    def test_recommended_none_when_all_blocked(self):
        ctx = _assemble(circuit_state=CircuitState.OPEN)
        assert ctx.recommended_next_action is None

    def test_safe_parallel_actions_only_read_family(self):
        ctx = _assemble(state="draft")
        assert "read_change_request" in ctx.safe_parallel_actions
        assert "update" not in ctx.safe_parallel_actions
        assert "submit" not in ctx.safe_parallel_actions

    def test_recheck_false_when_strong_and_no_lease(self):
        ctx = _assemble(consistency_profile=ConsistencyProfile.STRONG)
        assert ctx.requires_authoritative_recheck is False

    def test_recheck_true_when_eventual(self):
        ctx = _assemble(consistency_profile=ConsistencyProfile.EVENTUAL)
        assert ctx.requires_authoritative_recheck is True

    def test_budget_remaining_has_all_keys(self):
        ctx = _assemble()
        assert "cost_units" in ctx.budget_remaining
        assert "actions_per_minute" in ctx.budget_remaining
        assert "mutating_actions_per_hour" in ctx.budget_remaining
        assert "high_risk_actions_today" in ctx.budget_remaining

    def test_consistency_profile_forwarded(self):
        ctx = _assemble(consistency_profile=ConsistencyProfile.EVENTUAL)
        assert ctx.consistency_profile == ConsistencyProfile.EVENTUAL

    def test_projection_lag_forwarded(self):
        ctx = _assemble(
            consistency_profile=ConsistencyProfile.ASYNC_PROJECTION,
            projection_lag_ms=120,
        )
        assert ctx.projection_lag_ms == 120

    def test_freshness_strong_is_fresh(self):
        ctx = _assemble(consistency_profile=ConsistencyProfile.STRONG)
        assert ctx.freshness_status == FreshnessStatus.FRESH

    def test_freshness_eventual_is_warning(self):
        ctx = _assemble(consistency_profile=ConsistencyProfile.EVENTUAL)
        assert ctx.freshness_status == FreshnessStatus.WARNING
