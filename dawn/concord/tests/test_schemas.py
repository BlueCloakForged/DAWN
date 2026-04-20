"""Tests for CONCORD v0.3 Pydantic schemas.

Covers:
- ActionContractSchema: required fields, saga/compensation, ASYNC_PROJECTION tolerance,
  mutating idempotency, round-trip serialization
- StateContractSchema: StateObject-based states, undeclared state references rejected,
  transition action_ref and guards fields
- OperationContextSchema: authoritative_for_mutation always False
- TokenSchema: available_count <= capacity
- BudgetLedgerSchema: window_end after window_start
- CircuitBreakerThresholdsSchema: rate ranges
- BudgetProfileSchema: limits > 0
- GuardPredicateSchema: guard_type values
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from dawn.concord.types.enums import (
    ActionFamily,
    CircuitState,
    CompensationStrategy,
    ConflictResolutionStrategy,
    ConsistencyProfile,
    CooldownPolicy,
    FreshnessStatus,
    IdempotencyScope,
    LeaseStatus,
    LeaseType,
    RiskLevel,
    SessionStatus,
    TokenStatus,
    TokenType,
    TripRecoveryPolicy,
    TrustTier,
)
from dawn.concord.types.schemas import (
    ActionContractSchema,
    BudgetLedgerSchema,
    BudgetProfileSchema,
    CircuitBreakerThresholdsSchema,
    GuardPredicateSchema,
    LeaseSchema,
    OperationContextSchema,
    ResourceSchema,
    SideEffectSchema,
    StateContractSchema,
    StateObjectSchema,
    StateTransitionSchema,
    TokenSchema,
)

NOW = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)
FUTURE = datetime(2026, 3, 5, 13, 0, 0, tzinfo=timezone.utc)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def minimal_action_contract(**overrides) -> dict:
    base = dict(
        action_name="update",
        description="Update a change request in draft state",
        resource_type="change_request",
        action_family=ActionFamily.MUTATE,
        input_schema_ref="schemas/update_input.json",
        output_schema_ref="schemas/update_output.json",
        required_capabilities=["change_request_modify"],
        required_trust_tier=TrustTier.T2_BOUNDED,
        consistency_profile=ConsistencyProfile.STRONG,
        idempotency_required=True,
        risk_level=RiskLevel.LOW,
        conflict_resolution_strategy=ConflictResolutionStrategy.DEFAULT,
        compensation_strategy=CompensationStrategy.NONE,
        participates_in_saga=False,
    )
    base.update(overrides)
    return base


def minimal_resource() -> dict:
    return dict(
        id="res-1",
        resource_type="change_request",
        business_state={"status": "draft"},
        coordination_state={},
        version=1,
        created_at=NOW,
        updated_at=NOW,
    )


def minimal_operation_context(**overrides) -> dict:
    base = dict(
        resource_id="res-1",
        resource=minimal_resource(),
        allowed_actions=["update"],
        blocked_actions=[],
        blocked_reasons=[],
        budget_remaining={"actions_remaining": 55},
        freshness_status=FreshnessStatus.FRESH,
        context_assembled_at=NOW,
        context_ttl_ms=5000,
    )
    base.update(overrides)
    return base


def change_request_states() -> list[dict]:
    return [
        dict(name="draft"),
        dict(name="submitted"),
        dict(name="under_review"),
        dict(name="approved", is_terminal=True),
        dict(name="rejected", is_terminal=True),
    ]


def change_request_transitions() -> list[dict]:
    return [
        dict(name="submit", from_state="draft", to_state="submitted",
             action_ref="submit_change_request"),
        dict(name="start_review", from_state="submitted", to_state="under_review",
             action_ref="request_review_token"),
        dict(name="approve", from_state="under_review", to_state="approved",
             action_ref="approve_change_request"),
        dict(name="reject", from_state="under_review", to_state="rejected",
             action_ref="reject_change_request"),
    ]


# ── ActionContractSchema ──────────────────────────────────────────────────────


class TestActionContractSchema:
    def test_valid_mutating_contract(self):
        c = ActionContractSchema(**minimal_action_contract())
        assert c.action_name == "update"
        assert c.idempotency_required is True
        assert c.idempotency_scope == IdempotencyScope.SESSION

    def test_missing_idempotency_required_raises(self):
        data = minimal_action_contract()
        del data["idempotency_required"]
        with pytest.raises(ValidationError) as exc_info:
            ActionContractSchema(**data)
        assert "idempotency_required" in str(exc_info.value)

    def test_mutating_action_without_idempotency_raises(self):
        data = minimal_action_contract(idempotency_required=False)
        with pytest.raises(ValidationError) as exc_info:
            ActionContractSchema(**data)
        assert "idempotency_required" in str(exc_info.value)

    def test_saga_without_compensation_raises(self):
        data = minimal_action_contract(
            participates_in_saga=True,
            compensation_strategy=CompensationStrategy.NONE,
        )
        with pytest.raises(ValidationError) as exc_info:
            ActionContractSchema(**data)
        assert "compensation_strategy" in str(exc_info.value)

    def test_saga_with_compensation_valid(self):
        data = minimal_action_contract(
            participates_in_saga=True,
            compensation_strategy=CompensationStrategy.INVERSE_ACTION,
        )
        c = ActionContractSchema(**data)
        assert c.participates_in_saga is True

    def test_async_projection_without_tolerance_raises(self):
        data = minimal_action_contract(
            consistency_profile=ConsistencyProfile.ASYNC_PROJECTION,
            action_family=ActionFamily.READ,
            idempotency_required=False,
        )
        with pytest.raises(ValidationError) as exc_info:
            ActionContractSchema(**data)
        assert "projection_tolerance_ms" in str(exc_info.value)

    def test_async_projection_with_tolerance_valid(self):
        data = minimal_action_contract(
            consistency_profile=ConsistencyProfile.ASYNC_PROJECTION,
            action_family=ActionFamily.READ,
            idempotency_required=False,
            projection_tolerance_ms=500,
        )
        c = ActionContractSchema(**data)
        assert c.projection_tolerance_ms == 500

    def test_non_mutating_read_allows_idempotency_false(self):
        data = minimal_action_contract(
            action_family=ActionFamily.READ,
            idempotency_required=False,
        )
        c = ActionContractSchema(**data)
        assert c.action_family == ActionFamily.READ

    def test_guard_predicates_parsed(self):
        data = minimal_action_contract(
            guard_predicates=[
                dict(name="must_be_draft", guard_type="state",
                     parameters={"expected_state": "draft"}, evaluation_order=1)
            ]
        )
        c = ActionContractSchema(**data)
        assert len(c.guard_predicates) == 1
        assert c.guard_predicates[0].name == "must_be_draft"

    def test_side_effects_parsed(self):
        data = minimal_action_contract(
            side_effects=[
                dict(effect_type="event_emit", reversible=False,
                     description="Emits update event", target_system="event_bus")
            ]
        )
        c = ActionContractSchema(**data)
        assert c.side_effects[0].effect_type == "event_emit"

    def test_budget_cost_units_default(self):
        c = ActionContractSchema(**minimal_action_contract())
        assert c.budget_cost_units == 1.0

    def test_budget_cost_units_zero_raises(self):
        with pytest.raises(ValidationError):
            ActionContractSchema(**minimal_action_contract(budget_cost_units=0))

    def test_model_dump_round_trip(self):
        data = minimal_action_contract()
        c = ActionContractSchema(**data)
        c2 = ActionContractSchema(**c.model_dump())
        assert c2.action_name == c.action_name


# ── StateContractSchema ───────────────────────────────────────────────────────


class TestStateContractSchema:
    def _valid(self) -> dict:
        return dict(
            resource_type="change_request",
            initial_state="draft",
            terminal_states=["approved", "rejected"],
            states=change_request_states(),
            transitions=change_request_transitions(),
        )

    def test_valid_state_contract(self):
        sc = StateContractSchema(**self._valid())
        assert sc.initial_state == "draft"
        assert "approved" in sc.terminal_states
        assert len(sc.states) == 5

    def test_states_are_objects_not_strings(self):
        sc = StateContractSchema(**self._valid())
        assert all(isinstance(s, StateObjectSchema) for s in sc.states)
        assert sc.states[0].name == "draft"

    def test_terminal_states_have_is_terminal_true(self):
        sc = StateContractSchema(**self._valid())
        terminal = {s.name: s.is_terminal for s in sc.states}
        assert terminal["approved"] is True
        assert terminal["rejected"] is True
        assert terminal["draft"] is False

    def test_transitions_use_action_ref(self):
        sc = StateContractSchema(**self._valid())
        assert sc.transitions[0].action_ref == "submit_change_request"
        assert sc.transitions[0].name == "submit"

    def test_undeclared_initial_state_raises(self):
        data = self._valid()
        data["initial_state"] = "nonexistent"
        with pytest.raises(ValidationError) as exc_info:
            StateContractSchema(**data)
        assert "initial_state" in str(exc_info.value)

    def test_undeclared_terminal_state_raises(self):
        data = self._valid()
        data["terminal_states"] = ["approved", "ghost_state"]
        with pytest.raises(ValidationError) as exc_info:
            StateContractSchema(**data)
        assert "ghost_state" in str(exc_info.value)

    def test_transition_referencing_undeclared_from_state_raises(self):
        data = self._valid()
        data["transitions"].append(
            dict(name="ghost_trans", from_state="imaginary", to_state="draft",
                 action_ref="reset")
        )
        with pytest.raises(ValidationError) as exc_info:
            StateContractSchema(**data)
        assert "imaginary" in str(exc_info.value)

    def test_transition_referencing_undeclared_to_state_raises(self):
        data = self._valid()
        data["transitions"].append(
            dict(name="vanish", from_state="draft", to_state="limbo",
                 action_ref="disappear")
        )
        with pytest.raises(ValidationError) as exc_info:
            StateContractSchema(**data)
        assert "limbo" in str(exc_info.value)

    def test_model_dump_round_trip(self):
        data = self._valid()
        sc = StateContractSchema(**data)
        sc2 = StateContractSchema(**sc.model_dump())
        assert sc2.resource_type == sc.resource_type
        assert len(sc2.states) == len(sc.states)

    def test_transition_with_guards(self):
        data = self._valid()
        data["transitions"][0]["guards"] = [
            dict(name="required_fields_complete", guard_type="state")
        ]
        sc = StateContractSchema(**data)
        assert sc.transitions[0].guards[0].name == "required_fields_complete"

    def test_rollback_rules_optional(self):
        data = self._valid()
        data["rollback_rules"] = [{"state": "draft", "handler": "revert_submit"}]
        sc = StateContractSchema(**data)
        assert len(sc.rollback_rules) == 1


# ── OperationContextSchema ────────────────────────────────────────────────────


class TestOperationContextSchema:
    def test_authoritative_for_mutation_always_false(self):
        ctx = OperationContextSchema(**minimal_operation_context())
        assert ctx.authoritative_for_mutation is False

    def test_authoritative_for_mutation_in_dump(self):
        ctx = OperationContextSchema(**minimal_operation_context())
        dumped = ctx.model_dump()
        assert dumped["authoritative_for_mutation"] is False

    def test_blocked_reasons_structured(self):
        data = minimal_operation_context(
            blocked_reasons=[
                dict(reason_code="LEASE_HELD", unblock_condition="Wait for lease release",
                     estimated_wait_ms=1500)
            ]
        )
        ctx = OperationContextSchema(**data)
        assert ctx.blocked_reasons[0].reason_code == "LEASE_HELD"
        assert ctx.blocked_reasons[0].estimated_wait_ms == 1500

    def test_active_leases_default_empty(self):
        ctx = OperationContextSchema(**minimal_operation_context())
        assert ctx.active_leases == []

    def test_pending_intents_default_empty(self):
        ctx = OperationContextSchema(**minimal_operation_context())
        assert ctx.pending_intents == []

    def test_recommended_next_action_optional(self):
        data = minimal_operation_context(recommended_next_action="request_review_token")
        ctx = OperationContextSchema(**data)
        assert ctx.recommended_next_action == "request_review_token"

    def test_trust_constraints_optional(self):
        data = minimal_operation_context(
            trust_constraints=["deploy_change_request requires T4/governed_critical"]
        )
        ctx = OperationContextSchema(**data)
        assert len(ctx.trust_constraints) == 1


# ── TokenSchema ───────────────────────────────────────────────────────────────


class TestTokenSchema:
    def test_valid_token(self):
        t = TokenSchema(
            id="tok-1",
            token_type=TokenType.QUORUM,
            resource_id="res-1",
            capacity=3,
            available_count=2,
            holders=["sess-a"],
            issuance_rule="quorum_policy_v1",
            status=TokenStatus.ACTIVE,
        )
        assert t.available_count == 2

    def test_available_count_exceeds_capacity_raises(self):
        with pytest.raises(ValidationError):
            TokenSchema(
                id="tok-2",
                token_type=TokenType.CAPACITY,
                resource_id="res-1",
                capacity=2,
                available_count=5,  # > capacity
                holders=[],
                issuance_rule="policy",
                status=TokenStatus.ACTIVE,
            )

    def test_available_count_equals_capacity_ok(self):
        t = TokenSchema(
            id="tok-3",
            token_type=TokenType.CAPACITY,
            resource_id="res-1",
            capacity=5,
            available_count=5,
            holders=[],
            issuance_rule="policy",
            status=TokenStatus.ACTIVE,
        )
        assert t.available_count == t.capacity


# ── BudgetLedgerSchema ────────────────────────────────────────────────────────


class TestBudgetLedgerSchema:
    def _valid(self) -> dict:
        return dict(
            ledger_id="ledger-1",
            session_id="sess-1",
            agent_class_id="ac-1",
            budget_profile_id="bp-1",
            window_start=NOW,
            window_end=FUTURE,
            actions_consumed=10,
            mutating_actions_consumed=3,
            high_risk_actions_consumed=0,
            cost_units_consumed=7.5,
            parallel_leases_in_use=1,
            queue_slots_in_use=0,
            circuit_state=CircuitState.CLOSED,
        )

    def test_valid_ledger(self):
        bl = BudgetLedgerSchema(**self._valid())
        assert bl.ledger_id == "ledger-1"
        assert bl.circuit_state == CircuitState.CLOSED

    def test_window_end_before_start_raises(self):
        data = self._valid()
        data["window_end"] = NOW  # equal, not after
        with pytest.raises(ValidationError):
            BudgetLedgerSchema(**data)


# ── CircuitBreakerThresholdsSchema ────────────────────────────────────────────


class TestCircuitBreakerThresholdsSchema:
    def test_valid_thresholds(self):
        cb = CircuitBreakerThresholdsSchema(
            stale_version_failure_rate=0.2,
            budget_exceeded_rate=0.1,
            error_rate=0.3,
            evaluation_window_ms=60000,
            trip_recovery_policy=TripRecoveryPolicy.AUTO_AFTER_COOLDOWN,
        )
        assert cb.evaluation_window_ms == 60000

    def test_rate_out_of_range_raises(self):
        with pytest.raises(ValidationError):
            CircuitBreakerThresholdsSchema(
                stale_version_failure_rate=1.5,
                budget_exceeded_rate=0.1,
                error_rate=0.3,
                evaluation_window_ms=60000,
                trip_recovery_policy=TripRecoveryPolicy.MANUAL_RESET,
            )

    def test_zero_evaluation_window_raises(self):
        with pytest.raises(ValidationError):
            CircuitBreakerThresholdsSchema(
                stale_version_failure_rate=0.2,
                budget_exceeded_rate=0.1,
                error_rate=0.3,
                evaluation_window_ms=0,
                trip_recovery_policy=TripRecoveryPolicy.GRADUAL_RAMP,
            )


# ── BudgetProfileSchema ───────────────────────────────────────────────────────


def _cb_thresholds() -> CircuitBreakerThresholdsSchema:
    return CircuitBreakerThresholdsSchema(
        stale_version_failure_rate=0.2,
        budget_exceeded_rate=0.1,
        error_rate=0.3,
        evaluation_window_ms=60000,
        trip_recovery_policy=TripRecoveryPolicy.AUTO_AFTER_COOLDOWN,
    )


class TestBudgetProfileSchema:
    def test_valid_budget_profile(self):
        bp = BudgetProfileSchema(
            id="bp-1",
            max_actions_per_minute=60,
            max_mutating_actions_per_hour=24,
            max_high_risk_per_day=3,
            max_cost_units_per_session=40.0,
            burst_limit=10,
            circuit_breaker_thresholds=_cb_thresholds(),
            cooldown_policy=CooldownPolicy.CONTENTION_SCALED,
        )
        assert bp.max_actions_per_minute == 60
        assert bp.max_parallel_leases == 1  # default

    def test_zero_max_actions_raises(self):
        with pytest.raises(ValidationError):
            BudgetProfileSchema(
                id="bp-2",
                max_actions_per_minute=0,
                max_mutating_actions_per_hour=24,
                max_high_risk_per_day=3,
                max_cost_units_per_session=40.0,
                burst_limit=10,
                circuit_breaker_thresholds=_cb_thresholds(),
                cooldown_policy=CooldownPolicy.FIXED_BACKOFF,
            )

    def test_zero_burst_limit_raises(self):
        with pytest.raises(ValidationError):
            BudgetProfileSchema(
                id="bp-3",
                max_actions_per_minute=60,
                max_mutating_actions_per_hour=24,
                max_high_risk_per_day=3,
                max_cost_units_per_session=40.0,
                burst_limit=0,
                circuit_breaker_thresholds=_cb_thresholds(),
                cooldown_policy=CooldownPolicy.FIXED_BACKOFF,
            )


# ── GuardPredicateSchema ──────────────────────────────────────────────────────


class TestGuardPredicateSchema:
    def test_valid_guard_types(self):
        for gt in ("permission", "state", "resource_tag", "custom"):
            gp = GuardPredicateSchema(name="g", guard_type=gt)
            assert gp.guard_type == gt

    def test_invalid_guard_type_raises(self):
        with pytest.raises(ValidationError):
            GuardPredicateSchema(name="g", guard_type="unknown_type")
