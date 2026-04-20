"""Tests for CONCORD Phase 4 — budget_kernel.py.

Covers:
- MUTATING_FAMILIES / HIGH_RISK_LEVELS classification
- BudgetCheckResult field contracts
- check_gateway_budget(): circuit open, cooldown active, burst limit, allowed
- check_intent_budget(): circuit open, cooldown, rate limit, mutating quota,
  high-risk quota, cost-units ceiling, allowed path
- record_action(): counter increments (actions, mutating, high-risk, cost units)
- evaluate_circuit(): OPEN / THROTTLED / CLOSED thresholds + boundary conditions
- compute_cooldown_ms(): all five CooldownPolicy behaviours including exponential cap
"""

from datetime import datetime, timedelta, timezone

import pytest

from dawn.concord.budget_kernel import (
    HIGH_RISK_LEVELS,
    MUTATING_FAMILIES,
    BudgetCheckResult,
    check_gateway_budget,
    check_intent_budget,
    compute_cooldown_ms,
    evaluate_circuit,
    record_action,
)
from dawn.concord.types.entities import BudgetLedger, BudgetProfile, CircuitBreakerThresholds
from dawn.concord.types.enums import (
    ActionFamily,
    CircuitState,
    CooldownPolicy,
    RiskLevel,
    TripRecoveryPolicy,
)

NOW = datetime.now(timezone.utc)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_thresholds(
    stale_version_failure_rate=0.3,
    budget_exceeded_rate=0.2,
    error_rate=0.1,
    evaluation_window_ms=60_000,
    trip_recovery_policy=TripRecoveryPolicy.AUTO_AFTER_COOLDOWN,
) -> CircuitBreakerThresholds:
    return CircuitBreakerThresholds(
        stale_version_failure_rate=stale_version_failure_rate,
        budget_exceeded_rate=budget_exceeded_rate,
        error_rate=error_rate,
        evaluation_window_ms=evaluation_window_ms,
        trip_recovery_policy=trip_recovery_policy,
    )


def make_profile(
    max_actions_per_minute=60,
    max_mutating_actions_per_hour=24,
    max_high_risk_per_day=3,
    max_cost_units_per_session=40.0,
    burst_limit=10,
    cooldown_policy=CooldownPolicy.CONTENTION_SCALED,
) -> BudgetProfile:
    return BudgetProfile(
        id="bp-test",
        max_actions_per_minute=max_actions_per_minute,
        max_mutating_actions_per_hour=max_mutating_actions_per_hour,
        max_high_risk_per_day=max_high_risk_per_day,
        max_cost_units_per_session=max_cost_units_per_session,
        burst_limit=burst_limit,
        circuit_breaker_thresholds=make_thresholds(),
        cooldown_policy=cooldown_policy,
    )


def make_ledger(
    actions_consumed=0,
    mutating_actions_consumed=0,
    high_risk_actions_consumed=0,
    cost_units_consumed=0.0,
    circuit_state=CircuitState.CLOSED,
    cooldown_until=None,
    parallel_leases_in_use=0,
    queue_slots_in_use=0,
) -> BudgetLedger:
    return BudgetLedger(
        ledger_id="ledger-1",
        session_id="session-1",
        agent_class_id="ac-1",
        budget_profile_id="bp-test",
        window_start=NOW,
        window_end=NOW + timedelta(hours=1),
        actions_consumed=actions_consumed,
        mutating_actions_consumed=mutating_actions_consumed,
        high_risk_actions_consumed=high_risk_actions_consumed,
        cost_units_consumed=cost_units_consumed,
        parallel_leases_in_use=parallel_leases_in_use,
        queue_slots_in_use=queue_slots_in_use,
        circuit_state=circuit_state,
        cooldown_until=cooldown_until,
    )


# ── Classification sets ───────────────────────────────────────────────────────


class TestClassificationSets:
    def test_mutate_is_mutating(self):
        assert ActionFamily.MUTATE in MUTATING_FAMILIES

    def test_approve_is_mutating(self):
        assert ActionFamily.APPROVE in MUTATING_FAMILIES

    def test_deploy_is_mutating(self):
        assert ActionFamily.DEPLOY in MUTATING_FAMILIES

    def test_compensate_is_mutating(self):
        assert ActionFamily.COMPENSATE in MUTATING_FAMILIES

    def test_admin_is_mutating(self):
        assert ActionFamily.ADMIN in MUTATING_FAMILIES

    def test_read_is_not_mutating(self):
        assert ActionFamily.READ not in MUTATING_FAMILIES

    def test_plan_is_not_mutating(self):
        assert ActionFamily.PLAN not in MUTATING_FAMILIES

    def test_high_is_high_risk(self):
        assert RiskLevel.HIGH in HIGH_RISK_LEVELS

    def test_critical_is_high_risk(self):
        assert RiskLevel.CRITICAL in HIGH_RISK_LEVELS

    def test_low_is_not_high_risk(self):
        assert RiskLevel.LOW not in HIGH_RISK_LEVELS

    def test_moderate_is_not_high_risk(self):
        assert RiskLevel.MODERATE not in HIGH_RISK_LEVELS


# ── BudgetCheckResult ─────────────────────────────────────────────────────────


class TestBudgetCheckResult:
    def test_allowed_result(self):
        r = BudgetCheckResult(allowed=True)
        assert r.error_code is None
        assert r.reason is None
        assert r.retry_delay_hint_ms is None

    def test_denied_result(self):
        r = BudgetCheckResult(
            allowed=False,
            error_code="BUDGET_EXCEEDED",
            reason="limit hit",
            retry_delay_hint_ms=60_000,
        )
        assert r.allowed is False
        assert r.error_code == "BUDGET_EXCEEDED"

    def test_is_frozen(self):
        r = BudgetCheckResult(allowed=True)
        with pytest.raises((AttributeError, TypeError)):
            r.allowed = False  # type: ignore


# ── check_gateway_budget ──────────────────────────────────────────────────────


class TestCheckGatewayBudget:
    def test_allowed_when_all_clear(self):
        profile = make_profile()
        ledger = make_ledger(actions_consumed=0)
        result = check_gateway_budget(profile, ledger)
        assert result.allowed is True

    def test_denied_circuit_open(self):
        profile = make_profile()
        ledger = make_ledger(circuit_state=CircuitState.OPEN)
        result = check_gateway_budget(profile, ledger)
        assert result.allowed is False
        assert result.error_code == "CIRCUIT_OPEN"

    def test_throttled_circuit_still_allowed(self):
        profile = make_profile()
        ledger = make_ledger(circuit_state=CircuitState.THROTTLED)
        result = check_gateway_budget(profile, ledger)
        assert result.allowed is True

    def test_denied_cooldown_active(self):
        profile = make_profile()
        future = datetime.now(timezone.utc) + timedelta(seconds=30)
        ledger = make_ledger(cooldown_until=future)
        result = check_gateway_budget(profile, ledger)
        assert result.allowed is False
        assert result.error_code == "BUDGET_EXCEEDED"
        assert result.retry_delay_hint_ms is not None

    def test_allowed_when_cooldown_in_past(self):
        profile = make_profile()
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        ledger = make_ledger(cooldown_until=past)
        result = check_gateway_budget(profile, ledger)
        assert result.allowed is True

    def test_denied_at_burst_limit(self):
        profile = make_profile(burst_limit=10)
        ledger = make_ledger(actions_consumed=10)
        result = check_gateway_budget(profile, ledger)
        assert result.allowed is False
        assert result.error_code == "BUDGET_EXCEEDED"
        assert "burst" in result.reason.lower()

    def test_allowed_one_below_burst_limit(self):
        profile = make_profile(burst_limit=10)
        ledger = make_ledger(actions_consumed=9)
        result = check_gateway_budget(profile, ledger)
        assert result.allowed is True

    def test_circuit_open_checked_before_burst(self):
        profile = make_profile(burst_limit=0)
        ledger = make_ledger(actions_consumed=0, circuit_state=CircuitState.OPEN)
        result = check_gateway_budget(profile, ledger)
        assert result.error_code == "CIRCUIT_OPEN"


# ── check_intent_budget ───────────────────────────────────────────────────────


class TestCheckIntentBudget:
    def _allowed(self, ledger=None, profile=None, cost=1.0,
                 family=ActionFamily.READ, risk=RiskLevel.LOW):
        return check_intent_budget(
            profile or make_profile(),
            ledger or make_ledger(),
            cost_units=cost,
            action_family=family,
            risk_level=risk,
        )

    def test_allowed_clean_ledger(self):
        assert self._allowed().allowed is True

    def test_denied_circuit_open(self):
        result = self._allowed(ledger=make_ledger(circuit_state=CircuitState.OPEN))
        assert result.error_code == "CIRCUIT_OPEN"

    def test_denied_at_rate_limit(self):
        profile = make_profile(max_actions_per_minute=10)
        ledger = make_ledger(actions_consumed=10)
        result = self._allowed(ledger=ledger, profile=profile)
        assert result.allowed is False
        assert result.error_code == "BUDGET_EXCEEDED"
        assert "per-minute" in result.reason.lower()

    def test_allowed_one_below_rate_limit(self):
        profile = make_profile(max_actions_per_minute=10)
        ledger = make_ledger(actions_consumed=9)
        result = self._allowed(ledger=ledger, profile=profile)
        assert result.allowed is True

    def test_denied_mutating_quota(self):
        profile = make_profile(max_mutating_actions_per_hour=5)
        ledger = make_ledger(mutating_actions_consumed=5)
        result = self._allowed(ledger=ledger, profile=profile, family=ActionFamily.MUTATE)
        assert result.allowed is False
        assert "mutating" in result.reason.lower()

    def test_non_mutating_not_checked_against_mutating_quota(self):
        profile = make_profile(max_mutating_actions_per_hour=0)
        ledger = make_ledger(mutating_actions_consumed=0)
        result = self._allowed(ledger=ledger, profile=profile, family=ActionFamily.READ)
        assert result.allowed is True

    def test_denied_high_risk_quota(self):
        profile = make_profile(max_high_risk_per_day=2)
        ledger = make_ledger(high_risk_actions_consumed=2)
        result = self._allowed(ledger=ledger, profile=profile, risk=RiskLevel.HIGH)
        assert result.allowed is False
        assert "high-risk" in result.reason.lower()

    def test_low_risk_not_checked_against_high_risk_quota(self):
        profile = make_profile(max_high_risk_per_day=0)
        result = self._allowed(ledger=make_ledger(), profile=profile, risk=RiskLevel.LOW)
        assert result.allowed is True

    def test_denied_cost_units_ceiling(self):
        profile = make_profile(max_cost_units_per_session=10.0)
        ledger = make_ledger(cost_units_consumed=9.5)
        result = self._allowed(ledger=ledger, profile=profile, cost=1.0)
        assert result.allowed is False
        assert "cost" in result.reason.lower()

    def test_allowed_exactly_at_cost_ceiling_minus_epsilon(self):
        profile = make_profile(max_cost_units_per_session=10.0)
        ledger = make_ledger(cost_units_consumed=9.0)
        result = self._allowed(ledger=ledger, profile=profile, cost=1.0)
        assert result.allowed is True  # 9.0 + 1.0 = 10.0, not > 10.0

    def test_denied_when_cost_exceeds_ceiling(self):
        profile = make_profile(max_cost_units_per_session=10.0)
        ledger = make_ledger(cost_units_consumed=9.0)
        result = self._allowed(ledger=ledger, profile=profile, cost=1.5)
        assert result.allowed is False

    def test_approve_counts_as_mutating(self):
        profile = make_profile(max_mutating_actions_per_hour=1)
        ledger = make_ledger(mutating_actions_consumed=1)
        result = self._allowed(ledger=ledger, profile=profile, family=ActionFamily.APPROVE)
        assert result.allowed is False

    def test_critical_risk_blocked_by_high_risk_quota(self):
        profile = make_profile(max_high_risk_per_day=1)
        ledger = make_ledger(high_risk_actions_consumed=1)
        result = self._allowed(ledger=ledger, profile=profile, risk=RiskLevel.CRITICAL)
        assert result.allowed is False


# ── record_action ─────────────────────────────────────────────────────────────


class TestRecordAction:
    def test_increments_actions_consumed(self):
        ledger = make_ledger(actions_consumed=5)
        updated = record_action(ledger, cost_units=1.0,
                                action_family=ActionFamily.READ, risk_level=RiskLevel.LOW)
        assert updated.actions_consumed == 6

    def test_increments_mutating_for_mutating_family(self):
        ledger = make_ledger(mutating_actions_consumed=3)
        updated = record_action(ledger, cost_units=1.0,
                                action_family=ActionFamily.MUTATE, risk_level=RiskLevel.LOW)
        assert updated.mutating_actions_consumed == 4

    def test_no_mutating_increment_for_read(self):
        ledger = make_ledger(mutating_actions_consumed=3)
        updated = record_action(ledger, cost_units=1.0,
                                action_family=ActionFamily.READ, risk_level=RiskLevel.LOW)
        assert updated.mutating_actions_consumed == 3

    def test_increments_high_risk_for_high_level(self):
        ledger = make_ledger(high_risk_actions_consumed=1)
        updated = record_action(ledger, cost_units=1.0,
                                action_family=ActionFamily.READ, risk_level=RiskLevel.HIGH)
        assert updated.high_risk_actions_consumed == 2

    def test_increments_high_risk_for_critical(self):
        ledger = make_ledger(high_risk_actions_consumed=0)
        updated = record_action(ledger, cost_units=5.0,
                                action_family=ActionFamily.DEPLOY, risk_level=RiskLevel.CRITICAL)
        assert updated.high_risk_actions_consumed == 1

    def test_no_high_risk_increment_for_low(self):
        ledger = make_ledger(high_risk_actions_consumed=0)
        updated = record_action(ledger, cost_units=1.0,
                                action_family=ActionFamily.READ, risk_level=RiskLevel.LOW)
        assert updated.high_risk_actions_consumed == 0

    def test_adds_cost_units(self):
        ledger = make_ledger(cost_units_consumed=5.0)
        updated = record_action(ledger, cost_units=2.5,
                                action_family=ActionFamily.READ, risk_level=RiskLevel.LOW)
        assert abs(updated.cost_units_consumed - 7.5) < 1e-9

    def test_all_counters_increment_for_high_risk_mutate(self):
        ledger = make_ledger(actions_consumed=10, mutating_actions_consumed=5,
                             high_risk_actions_consumed=2, cost_units_consumed=20.0)
        updated = record_action(ledger, cost_units=3.0,
                                action_family=ActionFamily.MUTATE, risk_level=RiskLevel.HIGH)
        assert updated.actions_consumed == 11
        assert updated.mutating_actions_consumed == 6
        assert updated.high_risk_actions_consumed == 3
        assert abs(updated.cost_units_consumed - 23.0) < 1e-9

    def test_original_ledger_unchanged(self):
        ledger = make_ledger(actions_consumed=5)
        record_action(ledger, cost_units=1.0,
                      action_family=ActionFamily.READ, risk_level=RiskLevel.LOW)
        assert ledger.actions_consumed == 5

    def test_circuit_state_preserved(self):
        ledger = make_ledger(circuit_state=CircuitState.THROTTLED)
        updated = record_action(ledger, cost_units=1.0,
                                action_family=ActionFamily.READ, risk_level=RiskLevel.LOW)
        assert updated.circuit_state == CircuitState.THROTTLED


# ── evaluate_circuit ──────────────────────────────────────────────────────────


class TestEvaluateCircuit:
    def _eval(self, sv=0.0, be=0.0, er=0.0):
        thresholds = make_thresholds(
            stale_version_failure_rate=0.3,
            budget_exceeded_rate=0.2,
            error_rate=0.1,
        )
        return evaluate_circuit(thresholds, stale_version_rate=sv,
                                budget_exceeded_rate=be, error_rate=er)

    def test_closed_when_all_zero(self):
        assert self._eval() == CircuitState.CLOSED

    def test_closed_when_all_below_half_threshold(self):
        # stale threshold=0.3, so 50%=0.15; below that
        assert self._eval(sv=0.14) == CircuitState.CLOSED

    def test_throttled_when_rate_at_half_threshold(self):
        # stale threshold=0.3, 50% = 0.15
        assert self._eval(sv=0.15) == CircuitState.THROTTLED

    def test_throttled_when_between_half_and_full_threshold(self):
        assert self._eval(sv=0.25) == CircuitState.THROTTLED

    def test_open_when_rate_meets_threshold(self):
        assert self._eval(sv=0.3) == CircuitState.OPEN

    def test_open_when_rate_exceeds_threshold(self):
        assert self._eval(sv=0.5) == CircuitState.OPEN

    def test_open_on_budget_exceeded_threshold(self):
        assert self._eval(be=0.2) == CircuitState.OPEN

    def test_open_on_error_rate_threshold(self):
        assert self._eval(er=0.1) == CircuitState.OPEN

    def test_throttled_on_error_rate_at_half(self):
        assert self._eval(er=0.05) == CircuitState.THROTTLED

    def test_open_takes_priority_over_throttled(self):
        # stale at threshold (open), budget at half (throttled) → OPEN
        assert self._eval(sv=0.3, be=0.1) == CircuitState.OPEN

    def test_all_at_zero_is_closed_not_throttled(self):
        assert self._eval(sv=0.0, be=0.0, er=0.0) == CircuitState.CLOSED


# ── compute_cooldown_ms ───────────────────────────────────────────────────────


class TestComputeCooldownMs:
    def test_fixed_backoff_returns_base(self):
        assert compute_cooldown_ms(CooldownPolicy.FIXED_BACKOFF, 5000) == 5000

    def test_fixed_backoff_ignores_trip_count(self):
        assert compute_cooldown_ms(CooldownPolicy.FIXED_BACKOFF, 5000, trip_count=10) == 5000

    def test_exponential_trip1_returns_base(self):
        assert compute_cooldown_ms(CooldownPolicy.EXPONENTIAL_BACKOFF, 1000, trip_count=1) == 1000

    def test_exponential_trip2_doubles(self):
        assert compute_cooldown_ms(CooldownPolicy.EXPONENTIAL_BACKOFF, 1000, trip_count=2) == 2000

    def test_exponential_trip3_quadruples(self):
        assert compute_cooldown_ms(CooldownPolicy.EXPONENTIAL_BACKOFF, 1000, trip_count=3) == 4000

    def test_exponential_cap_at_300000(self):
        result = compute_cooldown_ms(CooldownPolicy.EXPONENTIAL_BACKOFF, 1000, trip_count=100)
        assert result == 300_000

    def test_exponential_trip0_treated_as_trip1(self):
        # trip_count=0 → exponent=max(0-1,0)=0 → 2^0=1 → base_ms
        assert compute_cooldown_ms(CooldownPolicy.EXPONENTIAL_BACKOFF, 1000, trip_count=0) == 1000

    def test_contention_scaled_factor_1(self):
        assert compute_cooldown_ms(
            CooldownPolicy.CONTENTION_SCALED, 2000, contention_factor=1.0
        ) == 2000

    def test_contention_scaled_factor_2(self):
        assert compute_cooldown_ms(
            CooldownPolicy.CONTENTION_SCALED, 2000, contention_factor=2.0
        ) == 4000

    def test_contention_scaled_factor_0(self):
        assert compute_cooldown_ms(
            CooldownPolicy.CONTENTION_SCALED, 2000, contention_factor=0.0
        ) == 0

    def test_risk_scaled_low_is_1x(self):
        assert compute_cooldown_ms(
            CooldownPolicy.RISK_SCALED, 1000, risk_level=RiskLevel.LOW
        ) == 1000

    def test_risk_scaled_moderate_is_2x(self):
        assert compute_cooldown_ms(
            CooldownPolicy.RISK_SCALED, 1000, risk_level=RiskLevel.MODERATE
        ) == 2000

    def test_risk_scaled_high_is_4x(self):
        assert compute_cooldown_ms(
            CooldownPolicy.RISK_SCALED, 1000, risk_level=RiskLevel.HIGH
        ) == 4000

    def test_risk_scaled_critical_is_8x(self):
        assert compute_cooldown_ms(
            CooldownPolicy.RISK_SCALED, 1000, risk_level=RiskLevel.CRITICAL
        ) == 8000

    def test_risk_scaled_none_risk_is_1x(self):
        assert compute_cooldown_ms(
            CooldownPolicy.RISK_SCALED, 1000, risk_level=None
        ) == 1000

    def test_manual_resume_returns_none(self):
        result = compute_cooldown_ms(CooldownPolicy.MANUAL_RESUME_REQUIRED, 5000)
        assert result is None

    def test_manual_resume_ignores_all_params(self):
        result = compute_cooldown_ms(
            CooldownPolicy.MANUAL_RESUME_REQUIRED, 5000,
            trip_count=99, contention_factor=10.0, risk_level=RiskLevel.CRITICAL
        )
        assert result is None
