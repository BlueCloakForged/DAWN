"""CONCORD v0.4-alpha — TaskFleet coordination kernel.

Provides:
- DispatchEvaluationResult  — outcome of evaluating fleet state after a dispatch failure
- FleetTimeoutResult        — outcome of a fleet-timeout event
- evaluate_dispatch_failure()  — apply completion_policy on dispatch failure
- handle_fleet_timeout()       — abort fleet and cancel all active dispatches
- check_fleet_timeout()        — True when now >= fleet.timeout_at
- cancel_dispatch()            — return CANCELLED copy of a DispatchRequest
- get_active_dispatches()      — dispatches in QUEUED | ASSIGNED | ACTIVE status

Normative rules enforced:

  Completion policies:
  - ALL_MUST_SUCCEED: any member failure → fleet ABORTED; all non-terminal
    dispatches CANCELLED.  No further dispatches may start after the abort.
  - BEST_EFFORT: each dispatch is independent; a failure does not affect the
    rest.  Fleet status stays ACTIVE until all dispatches reach terminal status.
  - FIRST_SUCCESS: the first COMPLETED dispatch closes the fleet (COMPLETED);
    remaining active dispatches are CANCELLED.  Failures alone do not abort.
  - QUORUM_N: treated as BEST_EFFORT in this implementation (quorum threshold
    evaluation is delegated to the caller who sets FleetStatus externally).

  Budget accounting:
  - A failed dispatch's consumed budget is NOT refunded.  The BudgetLedger is
    never modified by this kernel; consumed counters remain as-is.  Callers
    wanting to inspect remaining budget should call compute_budget_remaining()
    from context_kernel with the unchanged ledger.

  Timeout:
  - timeout_at MUST override individual session timeouts (spec v0.4 §Gap-2).
  - handle_fleet_timeout() aborts the fleet and cancels all active dispatches
    regardless of completion_policy.
  - Error code: FLEET_TIMEOUT; agent_should =
    "abort_and_trigger_compensation_for_active_members".
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Optional

from dawn.concord.types.entities import DispatchRequest, TaskFleet
from dawn.concord.types.enums import DispatchStatus, FleetCompletionPolicy, FleetStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Non-terminal dispatch statuses — these may still be cancelled / affected.
_ACTIVE_DISPATCH_STATUSES: frozenset[DispatchStatus] = frozenset(
    {DispatchStatus.QUEUED, DispatchStatus.ASSIGNED, DispatchStatus.ACTIVE}
)
_TERMINAL_DISPATCH_STATUSES: frozenset[DispatchStatus] = frozenset(
    {DispatchStatus.COMPLETED, DispatchStatus.FAILED, DispatchStatus.CANCELLED}
)

# Error code constants from the v0.4 error registry.
_ERROR_FLEET_TIMEOUT = "FLEET_TIMEOUT"
_AGENT_SHOULD_TIMEOUT = "abort_and_trigger_compensation_for_active_members"


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DispatchEvaluationResult:
    """Outcome of evaluating the fleet after a single dispatch failure.

    Attributes:
        fleet_id:               Parent fleet identifier.
        updated_fleet:          New TaskFleet state after policy evaluation.
        updated_dispatches:     All dispatches with status updated per policy.
        action_taken:           'abort_fleet' when ALL_MUST_SUCCEED aborts the fleet;
                                'first_success_close' when FIRST_SUCCESS closes the fleet;
                                'continue' when BEST_EFFORT or QUORUM_N lets others proceed.
        cancelled_dispatch_ids: IDs of dispatches moved to CANCELLED by the policy.
        error_code:             Populated when the fleet is aborted (currently None for
                                policy-driven aborts; FLEET_TIMEOUT is reserved for timeout).
        agent_should:           Recommended action (None for BEST_EFFORT).
    """

    fleet_id: str
    updated_fleet: TaskFleet
    updated_dispatches: list[DispatchRequest]
    action_taken: str   # 'abort_fleet' | 'first_success_close' | 'continue'
    cancelled_dispatch_ids: list[str]
    error_code: Optional[str] = None
    agent_should: Optional[str] = None


@dataclass(frozen=True)
class FleetTimeoutResult:
    """Outcome of handle_fleet_timeout().

    Attributes:
        fleet_id:             Parent fleet identifier.
        updated_fleet:        Fleet with status=ABORTED.
        updated_dispatches:   All non-terminal dispatches moved to CANCELLED.
        cancelled_dispatch_ids: IDs of dispatches that were cancelled.
        error_code:           Always 'FLEET_TIMEOUT'.
        agent_should:         Always 'abort_and_trigger_compensation_for_active_members'.
    """

    fleet_id: str
    updated_fleet: TaskFleet
    updated_dispatches: list[DispatchRequest]
    cancelled_dispatch_ids: list[str]
    error_code: str
    agent_should: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def cancel_dispatch(dispatch: DispatchRequest) -> DispatchRequest:
    """Return a copy of *dispatch* with status=CANCELLED.

    No-ops (returns copy) if already in a terminal status.
    """
    if dispatch.dispatch_status in _TERMINAL_DISPATCH_STATUSES:
        return replace(dispatch)
    return replace(dispatch, dispatch_status=DispatchStatus.CANCELLED)


def get_active_dispatches(dispatches: list[DispatchRequest]) -> list[DispatchRequest]:
    """Return dispatches in QUEUED, ASSIGNED, or ACTIVE status."""
    return [d for d in dispatches if d.dispatch_status in _ACTIVE_DISPATCH_STATUSES]


# ── Core functions ────────────────────────────────────────────────────────────


def check_fleet_timeout(fleet: TaskFleet, *, now: Optional[datetime] = None) -> bool:
    """Return True when *now* >= fleet.timeout_at.

    Implements the v0.4 rule that fleet timeout_at MUST override individual
    session timeouts.  Callers should check this at each dispatch lifecycle event.

    Args:
        fleet: The TaskFleet to evaluate.
        now:   Reference time (defaults to utcnow).
    """
    now = now or _utcnow()
    return now >= fleet.timeout_at


def evaluate_dispatch_failure(
    fleet: TaskFleet,
    failed_dispatch_id: str,
    all_dispatches: list[DispatchRequest],
) -> DispatchEvaluationResult:
    """Apply the fleet's completion_policy after one dispatch fails.

    Policy behaviours:

    ALL_MUST_SUCCEED:
      Fleet → ABORTED.  All non-terminal dispatches (other than the failed one)
      → CANCELLED.  Budget already consumed by the failed dispatch is NOT refunded.

    BEST_EFFORT:
      Only the failed dispatch changes status (already FAILED by the caller).
      Other dispatches continue.  Fleet remains ACTIVE.

    FIRST_SUCCESS:
      Failures don't close the fleet.  Fleet remains ACTIVE if other dispatches
      are still running.  (Success closes the fleet — see note below; this
      function only handles the failure path.)

    QUORUM_N:
      Treated identically to BEST_EFFORT here.  Quorum threshold evaluation is
      left to the caller.

    Note: This function only handles the dispatch *failure* path.  The caller is
    responsible for marking the failing dispatch as FAILED before calling this.

    Args:
        fleet:              The TaskFleet being evaluated.
        failed_dispatch_id: dispatch_id of the dispatch that just failed.
        all_dispatches:     All DispatchRequests belonging to this fleet.

    Returns:
        DispatchEvaluationResult describing the policy outcome.
    """
    policy = fleet.completion_policy

    if policy == FleetCompletionPolicy.ALL_MUST_SUCCEED:
        # Abort the fleet and cancel all remaining active dispatches.
        updated_fleet = replace(fleet, fleet_status=FleetStatus.ABORTED)
        cancelled_ids: list[str] = []
        updated_dispatches: list[DispatchRequest] = []
        for d in all_dispatches:
            if d.dispatch_id != failed_dispatch_id and d.dispatch_status in _ACTIVE_DISPATCH_STATUSES:
                updated_dispatches.append(cancel_dispatch(d))
                cancelled_ids.append(d.dispatch_id)
            else:
                updated_dispatches.append(replace(d))

        return DispatchEvaluationResult(
            fleet_id=fleet.fleet_id,
            updated_fleet=updated_fleet,
            updated_dispatches=updated_dispatches,
            action_taken="abort_fleet",
            cancelled_dispatch_ids=cancelled_ids,
            error_code=None,   # policy abort — not a timeout
            agent_should="evaluate_remaining_dispatches_and_trigger_compensation",
        )

    if policy in (FleetCompletionPolicy.BEST_EFFORT, FleetCompletionPolicy.QUORUM_N):
        # Failed dispatch stays FAILED; others are unaffected.
        # Fleet stays ACTIVE unless all dispatches are now terminal.
        all_terminal = all(
            d.dispatch_status in _TERMINAL_DISPATCH_STATUSES for d in all_dispatches
        )
        new_fleet_status = FleetStatus.COMPLETED if all_terminal else fleet.fleet_status
        updated_fleet = replace(fleet, fleet_status=new_fleet_status)

        return DispatchEvaluationResult(
            fleet_id=fleet.fleet_id,
            updated_fleet=updated_fleet,
            updated_dispatches=[replace(d) for d in all_dispatches],
            action_taken="continue",
            cancelled_dispatch_ids=[],
        )

    if policy == FleetCompletionPolicy.FIRST_SUCCESS:
        # Failure path: no closure yet; fleet stays ACTIVE if other dispatches remain.
        active_remaining = [
            d for d in all_dispatches
            if d.dispatch_id != failed_dispatch_id
            and d.dispatch_status in _ACTIVE_DISPATCH_STATUSES
        ]
        new_fleet_status = fleet.fleet_status if active_remaining else FleetStatus.ABORTED
        updated_fleet = replace(fleet, fleet_status=new_fleet_status)

        return DispatchEvaluationResult(
            fleet_id=fleet.fleet_id,
            updated_fleet=updated_fleet,
            updated_dispatches=[replace(d) for d in all_dispatches],
            action_taken="continue",
            cancelled_dispatch_ids=[],
        )

    # Fallback (should not be reached with valid enum values).
    return DispatchEvaluationResult(
        fleet_id=fleet.fleet_id,
        updated_fleet=replace(fleet),
        updated_dispatches=[replace(d) for d in all_dispatches],
        action_taken="continue",
        cancelled_dispatch_ids=[],
    )


def handle_fleet_timeout(
    fleet: TaskFleet,
    all_dispatches: list[DispatchRequest],
) -> FleetTimeoutResult:
    """Abort the fleet due to timeout, cancelling all active dispatches.

    Implements the v0.4 rule that fleet timeout_at MUST override individual
    session timeouts.  This is completion-policy-agnostic: regardless of policy,
    a timeout always aborts.

    Args:
        fleet:          The TaskFleet that timed out.
        all_dispatches: All DispatchRequests belonging to this fleet.

    Returns:
        FleetTimeoutResult with fleet=ABORTED and all active dispatches=CANCELLED.
    """
    updated_fleet = replace(fleet, fleet_status=FleetStatus.ABORTED)
    cancelled_ids: list[str] = []
    updated_dispatches: list[DispatchRequest] = []

    for d in all_dispatches:
        if d.dispatch_status in _ACTIVE_DISPATCH_STATUSES:
            updated_dispatches.append(cancel_dispatch(d))
            cancelled_ids.append(d.dispatch_id)
        else:
            updated_dispatches.append(replace(d))

    return FleetTimeoutResult(
        fleet_id=fleet.fleet_id,
        updated_fleet=updated_fleet,
        updated_dispatches=updated_dispatches,
        cancelled_dispatch_ids=cancelled_ids,
        error_code=_ERROR_FLEET_TIMEOUT,
        agent_should=_AGENT_SHOULD_TIMEOUT,
    )
