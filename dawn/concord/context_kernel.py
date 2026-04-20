"""CONCORD Phase 7 — OperationContext assembler.

Provides:
- assemble_context()   — composite read from all prior kernels → OperationContext
- compute_freshness()  — map consistency profile + projection lag → FreshnessStatus
- compute_budget_remaining() — summarise BudgetLedger/BudgetProfile into advisory dict
- is_context_stale()   — True when context_ttl_ms has elapsed since assembly

Normative rules enforced:
  - authoritative_for_mutation is ALWAYS False (enforced in OperationContext entity).
  - assemble_context never raises on partial information; it degrades gracefully.
  - allowed_actions: intersection of StateContract transitions from current state
    and registered ActionContracts.  Falls back to [] if no StateContract present.
  - blocked_actions: registered actions NOT in allowed_actions for this state.
  - blocked_reasons: one BlockedReason per blocked action, referencing a catalog
    error code when the reason is deterministic, otherwise "POLICY_BLOCKED".
  - Lease conflict on a resource adds "LEASE_HELD" BlockedReason for mutating actions.
  - Pending non-terminal intents from another session add "DUPLICATE_INTENT" hint.
  - recommended_next_action: first entry of allowed_actions, or None.
  - safe_parallel_actions: allowed read-family actions (ActionFamily.READ / PLAN).
  - requires_authoritative_recheck: True when freshness_status is STALE or any
    active lease belongs to a different session than the requesting one.
  - consistency_profile and projection_lag_ms: forwarded from ReadResult when
    the profile is ASYNC_PROJECTION.

  Freshness (compute_freshness):
  - STRONG:              always FRESH.
  - SESSION_MONOTONIC:   FRESH if version >= session_watermark; STALE otherwise.
  - READ_YOUR_WRITES:    FRESH if version >= min_version; WARNING otherwise.
  - EVENTUAL:            WARNING.
  - ASYNC_PROJECTION:    FRESH if projection_lag_ms <= tolerance; WARNING otherwise.
    Emits STALE_READ_WARNING when lag > tolerance.

  Budget summary (compute_budget_remaining):
  - cost_units:              max_cost_units_per_session − cost_units_consumed.
  - actions_per_minute:      max_actions_per_minute − actions_consumed.
  - mutating_actions_per_hour: max_mutating_actions_per_hour − mutating_actions_consumed.
  - high_risk_actions_today: max_high_risk_per_day − high_risk_actions_consumed.
  All values are floor-clamped to 0.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from dawn.concord.budget_kernel import MUTATING_FAMILIES, check_gateway_budget
from dawn.concord.contracts_kernel import ContractRegistry
from dawn.concord.identity_kernel import INTENT_TERMINAL_STATUSES
from dawn.concord.resource_kernel import ResourceRepository, read_with_profile
from dawn.concord.types.entities import (
    BlockedReason,
    BudgetLedger,
    BudgetProfile,
    Intent,
    Lease,
    OperationContext,
    Resource,
)
from dawn.concord.types.enums import (
    ActionFamily,
    ConsistencyProfile,
    FreshnessStatus,
    IntentStatus,
    LeaseStatus,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Freshness calculator ───────────────────────────────────────────────────────


def compute_freshness(
    profile: ConsistencyProfile,
    resource: Resource,
    *,
    session_watermark: Optional[int] = None,
    min_version: Optional[int] = None,
    projection_lag_ms: Optional[int] = None,
    projection_tolerance_ms: Optional[int] = None,
) -> FreshnessStatus:
    """Map a consistency profile + resource state to a FreshnessStatus.

    Args:
        profile:               Consistency requirement from the action contract.
        resource:              The resource snapshot just read.
        session_watermark:     Required for SESSION_MONOTONIC.
        min_version:           Required for READ_YOUR_WRITES.
        projection_lag_ms:     Observed projection lag for ASYNC_PROJECTION.
        projection_tolerance_ms: Tolerance threshold for ASYNC_PROJECTION; lag
                               above this → WARNING.

    Returns:
        FreshnessStatus.FRESH, WARNING, or STALE.
    """
    if profile == ConsistencyProfile.STRONG:
        return FreshnessStatus.FRESH

    if profile == ConsistencyProfile.SESSION_MONOTONIC:
        if session_watermark is not None and resource.version < session_watermark:
            return FreshnessStatus.STALE
        return FreshnessStatus.FRESH

    if profile == ConsistencyProfile.READ_YOUR_WRITES:
        if min_version is not None and resource.version < min_version:
            return FreshnessStatus.WARNING
        return FreshnessStatus.FRESH

    if profile == ConsistencyProfile.EVENTUAL:
        return FreshnessStatus.WARNING

    if profile == ConsistencyProfile.ASYNC_PROJECTION:
        if projection_lag_ms is not None and projection_tolerance_ms is not None:
            if projection_lag_ms > projection_tolerance_ms:
                return FreshnessStatus.WARNING
        return FreshnessStatus.FRESH

    return FreshnessStatus.WARNING  # pragma: no cover


# ── Budget summary ─────────────────────────────────────────────────────────────


def compute_budget_remaining(
    profile: BudgetProfile,
    ledger: BudgetLedger,
) -> dict[str, float]:
    """Summarise remaining quota from a BudgetProfile/BudgetLedger pair.

    Returns:
        Dict with keys:
            cost_units               — remaining session cost units (≥ 0)
            actions_per_minute       — remaining actions in current minute (≥ 0)
            mutating_actions_per_hour — remaining mutating actions today (≥ 0)
            high_risk_actions_today  — remaining high-risk actions today (≥ 0)
    """
    return {
        "cost_units": max(
            profile.max_cost_units_per_session - ledger.cost_units_consumed, 0.0
        ),
        "actions_per_minute": max(
            float(profile.max_actions_per_minute - ledger.actions_consumed), 0.0
        ),
        "mutating_actions_per_hour": max(
            float(
                profile.max_mutating_actions_per_hour
                - ledger.mutating_actions_consumed
            ),
            0.0,
        ),
        "high_risk_actions_today": max(
            float(profile.max_high_risk_per_day - ledger.high_risk_actions_consumed),
            0.0,
        ),
    }


# ── Context staleness check ────────────────────────────────────────────────────


def is_context_stale(context: OperationContext, *, now: Optional[datetime] = None) -> bool:
    """Return True when the context has exceeded its TTL since assembly.

    Args:
        context: The OperationContext to evaluate.
        now:     Reference time (defaults to utcnow).
    """
    now = now or _utcnow()
    elapsed_ms = max(int((now - context.context_assembled_at).total_seconds() * 1000), 0)
    return elapsed_ms >= context.context_ttl_ms


# ── Core assembler ────────────────────────────────────────────────────────────


def assemble_context(
    repo: ResourceRepository,
    registry: ContractRegistry,
    *,
    resource_id: str,
    resource_type: str,
    requesting_session_id: str,
    budget_profile: BudgetProfile,
    budget_ledger: BudgetLedger,
    active_leases: list[Lease],
    existing_intents: list[Intent],
    consistency_profile: ConsistencyProfile = ConsistencyProfile.STRONG,
    session_watermark: Optional[int] = None,
    min_version: Optional[int] = None,
    projection_lag_ms: Optional[int] = None,
    projection_tolerance_ms: Optional[int] = None,
    context_ttl_ms: int = 5_000,
    now: Optional[datetime] = None,
) -> OperationContext:
    """Assemble an advisory OperationContext from all prior kernels.

    Performs a composite read and analysis pass:
    1. Reads the resource via read_with_profile.
    2. Computes freshness_status.
    3. Determines allowed/blocked actions from the contract registry.
    4. Builds structured BlockedReason entries per blocked action.
    5. Evaluates active lease conflicts.
    6. Summarises budget_remaining.
    7. Computes recommended_next_action and safe_parallel_actions.

    This output is ALWAYS advisory (authoritative_for_mutation = False always).
    Agents MUST run full admission before any mutation.

    Args:
        repo:                  ResourceRepository to read from.
        registry:              ContractRegistry for action/state contracts.
        resource_id:           ID of the resource to assemble context for.
        resource_type:         Resource type key (for contract lookup).
        requesting_session_id: Session requesting the context.
        budget_profile:        BudgetProfile for the requesting agent class.
        budget_ledger:         Current BudgetLedger for the session window.
        active_leases:         All active Lease objects on this resource.
        existing_intents:      All non-terminal Intents on this resource.
        consistency_profile:   How freshness is evaluated.
        session_watermark:     Session version watermark (SESSION_MONOTONIC).
        min_version:           Minimum required version (READ_YOUR_WRITES).
        projection_lag_ms:     Observed projection lag (ASYNC_PROJECTION).
        projection_tolerance_ms: Lag tolerance threshold (ASYNC_PROJECTION).
        context_ttl_ms:        Advisory freshness TTL in milliseconds.
        now:                   Reference timestamp (defaults to utcnow).

    Returns:
        A fully populated OperationContext (advisory only).

    Raises:
        KeyError: if resource_id is not found in the repository.
    """
    now = now or _utcnow()

    # ── 1. Read resource ──────────────────────────────────────────────────────
    read_result = read_with_profile(
        repo,
        resource_id,
        consistency_profile,
        session_watermark=session_watermark,
        min_version=min_version,
        projection_lag_ms=projection_lag_ms,
    )
    resource = read_result.resource

    # ── 2. Freshness ──────────────────────────────────────────────────────────
    freshness = compute_freshness(
        consistency_profile,
        resource,
        session_watermark=session_watermark,
        min_version=min_version,
        projection_lag_ms=projection_lag_ms,
        projection_tolerance_ms=projection_tolerance_ms,
    )

    # ── 3. Allowed / blocked actions from state machine ───────────────────────
    current_state: Optional[str] = resource.business_state.get("status")

    allowed_actions: list[str] = []
    all_registered: list[str] = []

    try:
        all_registered = registry.registered_actions(resource_type)
    except Exception:
        pass

    if current_state and all_registered:
        try:
            # Union of transition-derived refs (mutating actions) and
            # StateObject.allowed_action_refs (includes read-only actions with
            # no state transition), both filtered to registered contracts.
            transition_allowed = set(
                registry.get_allowed_actions_for_state(resource_type, current_state)
            )
            sc = registry.lookup_state(resource_type)
            state_obj_refs: set[str] = set()
            for so in sc.states:
                if so.name == current_state:
                    state_obj_refs = set(so.allowed_action_refs)
                    break
            registered_set = set(all_registered)
            allowed_actions = sorted(
                (transition_allowed | state_obj_refs) & registered_set
            )
        except Exception:
            allowed_actions = list(all_registered)
    else:
        allowed_actions = list(all_registered)

    # Filter out actions denied by gateway budget (circuit open / cooldown)
    gw = check_gateway_budget(budget_profile, budget_ledger, now=now)
    if not gw.allowed:
        # Budget gate blocks all actions
        allowed_actions = []

    blocked_actions = [a for a in all_registered if a not in allowed_actions]

    # ── 4. BlockedReason entries ──────────────────────────────────────────────
    blocked_reasons: list[BlockedReason] = []

    # Budget gate blocking everything
    if not gw.allowed:
        for action in blocked_actions:
            blocked_reasons.append(
                BlockedReason(
                    reason_code=gw.error_code or "BUDGET_EXCEEDED",
                    unblock_condition=(
                        gw.reason or "Wait for budget window reset or circuit recovery."
                    ),
                    estimated_wait_ms=gw.retry_delay_hint_ms,
                )
            )
    else:
        # State-machine blocks (action not reachable from current state)
        state_allowed_set = set(allowed_actions)
        for action in blocked_actions:
            blocked_reasons.append(
                BlockedReason(
                    reason_code="POLICY_BLOCKED",
                    unblock_condition=(
                        f"Action '{action}' is not permitted from state "
                        f"'{current_state}'."
                    ),
                    estimated_wait_ms=None,
                )
            )

    # ── 5. Lease conflict analysis ────────────────────────────────────────────
    other_session_leases = [
        lease
        for lease in active_leases
        if lease.status == LeaseStatus.ACTIVE
        and lease.session_id != requesting_session_id
    ]

    queue_position: Optional[int] = None
    if other_session_leases:
        # Mutating actions are additionally blocked by the held lease
        for action in allowed_actions[:]:  # iterate copy
            try:
                ac = registry.lookup_action(resource_type, action)
                if ac.action_family in MUTATING_FAMILIES:
                    blocked_reasons.append(
                        BlockedReason(
                            reason_code="LEASE_HELD",
                            unblock_condition=(
                                f"A lease is held by another session on resource "
                                f"'{resource_id}'. Wait for release or join the queue."
                            ),
                            estimated_wait_ms=1_500,
                        )
                    )
                    break  # one entry suffices for the resource
            except KeyError:
                pass

    # ── 6. Pending-intent hint ────────────────────────────────────────────────
    other_session_pending = [
        intent
        for intent in existing_intents
        if intent.session_id != requesting_session_id
        and intent.status not in INTENT_TERMINAL_STATUSES
    ]
    pending_intent_ids = [i.id for i in other_session_pending]

    # ── 7. Budget remaining ───────────────────────────────────────────────────
    budget_remaining = compute_budget_remaining(budget_profile, budget_ledger)

    # ── 8. Derived fields ─────────────────────────────────────────────────────
    recommended_next_action = allowed_actions[0] if allowed_actions else None

    # Safe parallel actions: read/plan family only, always safe
    safe_parallel_actions: list[str] = []
    for action in allowed_actions:
        try:
            ac = registry.lookup_action(resource_type, action)
            if ac.action_family in (ActionFamily.READ, ActionFamily.PLAN):
                safe_parallel_actions.append(action)
        except KeyError:
            pass

    requires_authoritative_recheck = (
        freshness in (FreshnessStatus.STALE, FreshnessStatus.WARNING)
        or bool(other_session_leases)
    )

    return OperationContext(
        resource_id=resource_id,
        resource=resource,
        allowed_actions=allowed_actions,
        blocked_actions=blocked_actions,
        blocked_reasons=blocked_reasons,
        active_leases=list(active_leases),
        pending_intents=pending_intent_ids,
        budget_remaining=budget_remaining,
        freshness_status=freshness,
        context_assembled_at=now,
        context_ttl_ms=context_ttl_ms,
        queue_position=queue_position,
        recommended_next_action=recommended_next_action,
        safe_parallel_actions=safe_parallel_actions,
        requires_authoritative_recheck=requires_authoritative_recheck,
        consistency_profile=consistency_profile,
        projection_lag_ms=projection_lag_ms,
    )
