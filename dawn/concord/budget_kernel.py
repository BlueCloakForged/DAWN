"""CONCORD Phase 4 — Budget + policy layer.

Provides:
- MUTATING_FAMILIES / HIGH_RISK_LEVELS   — action classification sets
- BudgetCheckResult                       — frozen result type
- check_gateway_budget()                  — burst + circuit gate (fast, pre-intent)
- check_intent_budget()                   — all quota dimensions (intent admission)
- record_action()                         — returns updated BudgetLedger after action
- evaluate_circuit()                      — maps error rates → CircuitState
- compute_cooldown_ms()                   — cooldown duration from CooldownPolicy

Normative rules enforced:
  Gateway layer (check_gateway_budget):
  - If circuit_state == OPEN → CIRCUIT_OPEN; no admission.
  - If cooldown_until is set and in the future → BUDGET_EXCEEDED.
  - If actions_consumed >= burst_limit → BUDGET_EXCEEDED.

  Intent layer (check_intent_budget):
  - All gateway conditions apply.
  - If actions_consumed >= max_actions_per_minute → BUDGET_EXCEEDED.
  - Mutating action and mutating_actions_consumed >= max_mutating_actions_per_hour → BUDGET_EXCEEDED.
  - High-risk action and high_risk_actions_consumed >= max_high_risk_per_day → BUDGET_EXCEEDED.
  - cost_units_consumed + cost_units > max_cost_units_per_session → BUDGET_EXCEEDED.

  Circuit breaker (evaluate_circuit):
  - Any rate >= its configured threshold → OPEN.
  - Any rate >= 50% of its threshold (and none at threshold) → THROTTLED.
  - All rates below 50% of threshold → CLOSED.
  - THROTTLED circuit does not block; gateway/intent checks still proceed normally.

  Cooldown (compute_cooldown_ms):
  - fixed_backoff:         exactly base_ms.
  - exponential_backoff:   base_ms × 2^(trip_count−1), capped at 300_000 ms (5 min).
  - contention_scaled:     int(base_ms × contention_factor), minimum 0.
  - risk_scaled:           base_ms × risk_multiplier (low=1×, moderate=2×, high=4×, critical=8×).
  - manual_resume_required: returns None — no automatic cooldown; operator must intervene.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Optional

from dawn.concord.types.entities import BudgetLedger, BudgetProfile
from dawn.concord.types.enums import (
    ActionFamily,
    CircuitState,
    CooldownPolicy,
    RiskLevel,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Action classification ─────────────────────────────────────────────────────

MUTATING_FAMILIES: frozenset[ActionFamily] = frozenset({
    ActionFamily.MUTATE,
    ActionFamily.APPROVE,
    ActionFamily.DEPLOY,
    ActionFamily.COMPENSATE,
    ActionFamily.ADMIN,
})

HIGH_RISK_LEVELS: frozenset[RiskLevel] = frozenset({
    RiskLevel.HIGH,
    RiskLevel.CRITICAL,
})

_RISK_COOLDOWN_MULTIPLIER: dict[RiskLevel, float] = {
    RiskLevel.LOW:      1.0,
    RiskLevel.MODERATE: 2.0,
    RiskLevel.HIGH:     4.0,
    RiskLevel.CRITICAL: 8.0,
}

_EXPONENTIAL_CAP_MS: int = 300_000  # 5 minutes


# ── Result type ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BudgetCheckResult:
    """Result of a budget enforcement check.

    Attributes:
        allowed:            True when the action may proceed.
        error_code:         BUDGET_EXCEEDED or CIRCUIT_OPEN when denied; None when allowed.
        reason:             Human-readable description of the limit that was hit.
        retry_delay_hint_ms: Advisory retry delay from the error registry, or None.
    """

    allowed: bool
    error_code: Optional[str] = None
    reason: Optional[str] = None
    retry_delay_hint_ms: Optional[int] = None


# ── Internal helpers ──────────────────────────────────────────────────────────


def _check_circuit_and_cooldown(
    profile: BudgetProfile,
    ledger: BudgetLedger,
    *,
    now: Optional[datetime] = None,
) -> Optional[BudgetCheckResult]:
    """Return a denial result if circuit is open or cooldown is active, else None."""
    if ledger.circuit_state == CircuitState.OPEN:
        return BudgetCheckResult(
            allowed=False,
            error_code="CIRCUIT_OPEN",
            reason=(
                f"Circuit breaker is OPEN for agent class '{ledger.agent_class_id}'. "
                "Wait for circuit recovery or manual reset."
            ),
            retry_delay_hint_ms=30_000,
        )

    _now = now if now is not None else _utcnow()
    if ledger.cooldown_until is not None and _now < ledger.cooldown_until:
        remaining_ms = int(
            (ledger.cooldown_until - _now).total_seconds() * 1000
        )
        return BudgetCheckResult(
            allowed=False,
            error_code="BUDGET_EXCEEDED",
            reason=(
                f"Agent class '{ledger.agent_class_id}' is in cooldown. "
                f"Retry after cooldown expires (~{remaining_ms} ms remaining)."
            ),
            retry_delay_hint_ms=max(remaining_ms, 0),
        )

    return None


# ── Public budget checks ──────────────────────────────────────────────────────


def check_gateway_budget(
    profile: BudgetProfile,
    ledger: BudgetLedger,
    *,
    now: Optional[datetime] = None,
) -> BudgetCheckResult:
    """Fast pre-intent burst + circuit gate.

    Checks (in order):
    1. Circuit state — OPEN blocks immediately.
    2. Cooldown — active cooldown blocks.
    3. Burst limit — actions_consumed >= burst_limit blocks.

    Args:
        profile: The BudgetProfile for the agent class.
        ledger:  The current BudgetLedger for the session/window.
        now:     Optional reference time for cooldown comparison (default: utcnow).

    Returns:
        BudgetCheckResult with allowed=True, or denial with error_code.
    """
    gate = _check_circuit_and_cooldown(profile, ledger, now=now)
    if gate is not None:
        return gate

    if ledger.actions_consumed >= profile.burst_limit:
        return BudgetCheckResult(
            allowed=False,
            error_code="BUDGET_EXCEEDED",
            reason=(
                f"Burst limit reached: {ledger.actions_consumed} / {profile.burst_limit} "
                f"actions consumed for agent class '{ledger.agent_class_id}'."
            ),
            retry_delay_hint_ms=60_000,
        )

    return BudgetCheckResult(allowed=True)


def check_intent_budget(
    profile: BudgetProfile,
    ledger: BudgetLedger,
    *,
    cost_units: float,
    action_family: ActionFamily,
    risk_level: RiskLevel,
) -> BudgetCheckResult:
    """Full intent-layer quota check.

    Checks (in order):
    1. Circuit + cooldown (same as gateway).
    2. Actions-per-minute rate limit.
    3. Mutating-actions-per-hour (if action is mutating).
    4. High-risk-per-day (if action is high-risk).
    5. Session cost units ceiling.

    Args:
        profile:       BudgetProfile for the agent class.
        ledger:        Current BudgetLedger snapshot.
        cost_units:    Cost units this action will consume (from ActionContract).
        action_family: ActionFamily of the action being admitted.
        risk_level:    RiskLevel of the action being admitted.

    Returns:
        BudgetCheckResult with allowed=True, or denial with error_code.
    """
    gate = _check_circuit_and_cooldown(profile, ledger)
    if gate is not None:
        return gate

    # Rate: actions per minute
    if ledger.actions_consumed >= profile.max_actions_per_minute:
        return BudgetCheckResult(
            allowed=False,
            error_code="BUDGET_EXCEEDED",
            reason=(
                f"Actions-per-minute limit reached: "
                f"{ledger.actions_consumed} / {profile.max_actions_per_minute} "
                f"for agent class '{ledger.agent_class_id}'."
            ),
            retry_delay_hint_ms=60_000,
        )

    # Quota: mutating actions per hour
    if action_family in MUTATING_FAMILIES:
        if ledger.mutating_actions_consumed >= profile.max_mutating_actions_per_hour:
            return BudgetCheckResult(
                allowed=False,
                error_code="BUDGET_EXCEEDED",
                reason=(
                    f"Mutating-actions-per-hour limit reached: "
                    f"{ledger.mutating_actions_consumed} / "
                    f"{profile.max_mutating_actions_per_hour} "
                    f"for agent class '{ledger.agent_class_id}'."
                ),
                retry_delay_hint_ms=60_000,
            )

    # Quota: high-risk actions per day
    if risk_level in HIGH_RISK_LEVELS:
        if ledger.high_risk_actions_consumed >= profile.max_high_risk_per_day:
            return BudgetCheckResult(
                allowed=False,
                error_code="BUDGET_EXCEEDED",
                reason=(
                    f"High-risk-actions-per-day limit reached: "
                    f"{ledger.high_risk_actions_consumed} / "
                    f"{profile.max_high_risk_per_day} "
                    f"for agent class '{ledger.agent_class_id}'."
                ),
                retry_delay_hint_ms=60_000,
            )

    # Quota: session cost units
    projected = ledger.cost_units_consumed + cost_units
    if projected > profile.max_cost_units_per_session:
        return BudgetCheckResult(
            allowed=False,
            error_code="BUDGET_EXCEEDED",
            reason=(
                f"Session cost-units ceiling would be exceeded: "
                f"{ledger.cost_units_consumed:.2f} + {cost_units:.2f} = "
                f"{projected:.2f} > {profile.max_cost_units_per_session:.2f} "
                f"for agent class '{ledger.agent_class_id}'."
            ),
            retry_delay_hint_ms=60_000,
        )

    return BudgetCheckResult(allowed=True)


# ── Ledger mutation ───────────────────────────────────────────────────────────


def record_action(
    ledger: BudgetLedger,
    *,
    cost_units: float,
    action_family: ActionFamily,
    risk_level: RiskLevel,
) -> BudgetLedger:
    """Return a new BudgetLedger with counters advanced after a successful action.

    Always increments actions_consumed.
    Increments mutating_actions_consumed if action_family is mutating.
    Increments high_risk_actions_consumed if risk_level is high or critical.
    Adds cost_units to cost_units_consumed.

    The original ledger is not modified.
    """
    is_mutating = action_family in MUTATING_FAMILIES
    is_high_risk = risk_level in HIGH_RISK_LEVELS

    return replace(
        ledger,
        actions_consumed=ledger.actions_consumed + 1,
        mutating_actions_consumed=(
            ledger.mutating_actions_consumed + 1 if is_mutating
            else ledger.mutating_actions_consumed
        ),
        high_risk_actions_consumed=(
            ledger.high_risk_actions_consumed + 1 if is_high_risk
            else ledger.high_risk_actions_consumed
        ),
        cost_units_consumed=ledger.cost_units_consumed + cost_units,
    )


# ── Circuit breaker evaluation ────────────────────────────────────────────────


def evaluate_circuit(
    thresholds: "CircuitBreakerThresholds",  # noqa: F821 — import below
    *,
    stale_version_rate: float,
    budget_exceeded_rate: float,
    error_rate: float,
) -> CircuitState:
    """Map observed error rates to a CircuitState.

    Rules:
    - OPEN:      any rate >= its configured threshold.
    - THROTTLED: any rate >= 50% of its threshold (and none at threshold).
    - CLOSED:    all rates below 50% of threshold.

    Args:
        thresholds:          CircuitBreakerThresholds from the BudgetProfile.
        stale_version_rate:  Fraction of recent requests returning STALE_VERSION.
        budget_exceeded_rate: Fraction of recent requests returning BUDGET_EXCEEDED.
        error_rate:          Fraction of recent requests returning any non-conflict error.

    Returns:
        The new CircuitState.
    """
    pairs = [
        (stale_version_rate,   thresholds.stale_version_failure_rate),
        (budget_exceeded_rate, thresholds.budget_exceeded_rate),
        (error_rate,           thresholds.error_rate),
    ]

    if any(rate >= threshold for rate, threshold in pairs):
        return CircuitState.OPEN

    if any(rate >= threshold * 0.5 for rate, threshold in pairs):
        return CircuitState.THROTTLED

    return CircuitState.CLOSED


# Import here to avoid circular at module level (entities imports enums, not kernel)
from dawn.concord.types.entities import CircuitBreakerThresholds  # noqa: E402


# ── Cooldown computation ──────────────────────────────────────────────────────


def compute_cooldown_ms(
    policy: CooldownPolicy,
    base_ms: int,
    *,
    trip_count: int = 1,
    contention_factor: float = 1.0,
    risk_level: Optional[RiskLevel] = None,
) -> Optional[int]:
    """Compute cooldown duration in milliseconds for a given CooldownPolicy.

    Args:
        policy:            The CooldownPolicy from the BudgetProfile.
        base_ms:           Baseline cooldown duration (e.g., evaluation_window_ms).
        trip_count:        Number of times the circuit has tripped (for exponential).
        contention_factor: Scaling factor derived from concurrent agent count (for contention_scaled).
        risk_level:        RiskLevel of the action that triggered the cooldown (for risk_scaled).

    Returns:
        Cooldown duration in ms, or None for manual_resume_required.

    Policy behaviours:
        fixed_backoff:          base_ms (unchanged).
        exponential_backoff:    base_ms × 2^(trip_count−1), capped at 300,000 ms.
        contention_scaled:      int(base_ms × contention_factor), minimum 0.
        risk_scaled:            base_ms × risk_multiplier[risk_level] (default multiplier=1 for None).
        manual_resume_required: None — operator must intervene.
    """
    if policy == CooldownPolicy.MANUAL_RESUME_REQUIRED:
        return None

    if policy == CooldownPolicy.FIXED_BACKOFF:
        return base_ms

    if policy == CooldownPolicy.EXPONENTIAL_BACKOFF:
        exponent = max(trip_count - 1, 0)
        return min(base_ms * (2 ** exponent), _EXPONENTIAL_CAP_MS)

    if policy == CooldownPolicy.CONTENTION_SCALED:
        return max(int(base_ms * contention_factor), 0)

    if policy == CooldownPolicy.RISK_SCALED:
        multiplier = (
            _RISK_COOLDOWN_MULTIPLIER.get(risk_level, 1.0)
            if risk_level is not None
            else 1.0
        )
        return int(base_ms * multiplier)

    raise ValueError(f"Unhandled CooldownPolicy: {policy!r}")  # pragma: no cover
