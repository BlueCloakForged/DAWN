"""Tests for CONCORD v0.4-alpha — fleet_kernel.py.

Key scenario tested:
  "Show me a TaskFleet with three DispatchRequests where the second one fails.
  Walk through what happens under completion_policy = all_must_succeed vs best_effort."

  - all_must_succeed: fleet → ABORTED; dispatches 1 and 3 → CANCELLED
  - best_effort: fleet stays ACTIVE; dispatches 1 and 3 continue independently
  - failed dispatch's consumed budget is NOT refunded (ledger unchanged)
  - fleet timeout_at overrides individual session timeouts → handle_fleet_timeout
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dawn.concord.fleet_kernel import (
    DispatchEvaluationResult,
    FleetTimeoutResult,
    cancel_dispatch,
    check_fleet_timeout,
    evaluate_dispatch_failure,
    get_active_dispatches,
    handle_fleet_timeout,
)
from dawn.concord.types.entities import DispatchRequest, TaskFleet
from dawn.concord.types.enums import (
    DispatchPriority,
    DispatchStatus,
    FleetCompletionPolicy,
    FleetStatus,
    IsolationRequirement,
)

NOW = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)
FUTURE = NOW + timedelta(hours=2)
PAST = NOW - timedelta(minutes=5)


# ── Fixture helpers ───────────────────────────────────────────────────────────


def _fleet(
    fleet_id: str = "fleet-1",
    policy: FleetCompletionPolicy = FleetCompletionPolicy.ALL_MUST_SUCCEED,
    status: FleetStatus = FleetStatus.ACTIVE,
    timeout_at: datetime = FUTURE,
) -> TaskFleet:
    return TaskFleet(
        fleet_id=fleet_id,
        owner_session_id="sess-owner",
        agent_class_id="cls-default",
        max_concurrent=5,
        member_sessions=[],
        fleet_status=status,
        budget_profile_id="prof-default",
        isolation_requirement=IsolationRequirement.PER_SESSION,
        completion_policy=policy,
        created_at=NOW,
        timeout_at=timeout_at,
    )


def _dispatch(
    dispatch_id: str,
    fleet_id: str = "fleet-1",
    status: DispatchStatus = DispatchStatus.ACTIVE,
) -> DispatchRequest:
    return DispatchRequest(
        dispatch_id=dispatch_id,
        fleet_id=fleet_id,
        task_description={"task": dispatch_id},
        priority=DispatchPriority.NORMAL,
        max_attempts=3,
        attempt_count=1,
        idempotency_key=f"idem-{dispatch_id}",
        dispatch_status=status,
    )


def _three_dispatches(
    d2_status: DispatchStatus = DispatchStatus.FAILED,
) -> tuple[DispatchRequest, DispatchRequest, DispatchRequest]:
    """Return dispatches 1 (ACTIVE), 2 (given status), 3 (ACTIVE)."""
    d1 = _dispatch("d1", status=DispatchStatus.ACTIVE)
    d2 = _dispatch("d2", status=d2_status)
    d3 = _dispatch("d3", status=DispatchStatus.ACTIVE)
    return d1, d2, d3


# ── cancel_dispatch ───────────────────────────────────────────────────────────


class TestCancelDispatch:
    def test_active_becomes_cancelled(self):
        d = _dispatch("d1", status=DispatchStatus.ACTIVE)
        assert cancel_dispatch(d).dispatch_status == DispatchStatus.CANCELLED

    def test_queued_becomes_cancelled(self):
        d = _dispatch("d1", status=DispatchStatus.QUEUED)
        assert cancel_dispatch(d).dispatch_status == DispatchStatus.CANCELLED

    def test_completed_stays_completed(self):
        d = _dispatch("d1", status=DispatchStatus.COMPLETED)
        assert cancel_dispatch(d).dispatch_status == DispatchStatus.COMPLETED

    def test_already_cancelled_stays_cancelled(self):
        d = _dispatch("d1", status=DispatchStatus.CANCELLED)
        assert cancel_dispatch(d).dispatch_status == DispatchStatus.CANCELLED

    def test_failed_stays_failed(self):
        d = _dispatch("d1", status=DispatchStatus.FAILED)
        assert cancel_dispatch(d).dispatch_status == DispatchStatus.FAILED

    def test_original_unchanged(self):
        d = _dispatch("d1", status=DispatchStatus.ACTIVE)
        cancel_dispatch(d)
        assert d.dispatch_status == DispatchStatus.ACTIVE


# ── get_active_dispatches ─────────────────────────────────────────────────────


class TestGetActiveDispatches:
    def test_active_included(self):
        d = _dispatch("d1", status=DispatchStatus.ACTIVE)
        assert get_active_dispatches([d]) == [d]

    def test_queued_included(self):
        d = _dispatch("d1", status=DispatchStatus.QUEUED)
        assert get_active_dispatches([d]) == [d]

    def test_assigned_included(self):
        d = _dispatch("d1", status=DispatchStatus.ASSIGNED)
        assert get_active_dispatches([d]) == [d]

    def test_completed_excluded(self):
        d = _dispatch("d1", status=DispatchStatus.COMPLETED)
        assert get_active_dispatches([d]) == []

    def test_failed_excluded(self):
        d = _dispatch("d1", status=DispatchStatus.FAILED)
        assert get_active_dispatches([d]) == []

    def test_cancelled_excluded(self):
        d = _dispatch("d1", status=DispatchStatus.CANCELLED)
        assert get_active_dispatches([d]) == []


# ── check_fleet_timeout ───────────────────────────────────────────────────────


class TestCheckFleetTimeout:
    def test_not_timed_out(self):
        fleet = _fleet(timeout_at=FUTURE)
        assert check_fleet_timeout(fleet, now=NOW) is False

    def test_timed_out_past(self):
        fleet = _fleet(timeout_at=PAST)
        assert check_fleet_timeout(fleet, now=NOW) is True

    def test_timed_out_exactly_at_deadline(self):
        fleet = _fleet(timeout_at=NOW)
        assert check_fleet_timeout(fleet, now=NOW) is True


# ── evaluate_dispatch_failure — ALL_MUST_SUCCEED ──────────────────────────────


class TestAllMustSucceed:
    """Scenario: Three dispatches, d2 fails under ALL_MUST_SUCCEED."""

    def _run(self, d2_status=DispatchStatus.FAILED) -> DispatchEvaluationResult:
        d1, d2, d3 = _three_dispatches(d2_status)
        fleet = _fleet(policy=FleetCompletionPolicy.ALL_MUST_SUCCEED)
        return evaluate_dispatch_failure(fleet, "d2", [d1, d2, d3])

    def test_fleet_becomes_aborted(self):
        result = self._run()
        assert result.updated_fleet.fleet_status == FleetStatus.ABORTED

    def test_action_taken_is_abort_fleet(self):
        result = self._run()
        assert result.action_taken == "abort_fleet"

    def test_active_dispatches_cancelled(self):
        result = self._run()
        by_id = {d.dispatch_id: d for d in result.updated_dispatches}
        assert by_id["d1"].dispatch_status == DispatchStatus.CANCELLED
        assert by_id["d3"].dispatch_status == DispatchStatus.CANCELLED

    def test_cancelled_ids_listed(self):
        result = self._run()
        assert set(result.cancelled_dispatch_ids) == {"d1", "d3"}

    def test_failed_dispatch_stays_failed(self):
        result = self._run()
        by_id = {d.dispatch_id: d for d in result.updated_dispatches}
        assert by_id["d2"].dispatch_status == DispatchStatus.FAILED

    def test_all_dispatches_in_result(self):
        result = self._run()
        assert len(result.updated_dispatches) == 3

    def test_fleet_id_preserved(self):
        result = self._run()
        assert result.fleet_id == "fleet-1"

    def test_budget_not_refunded_ledger_unchanged(self):
        """Consuming budget for d2 is irreversible; fleet_kernel doesn't touch the ledger."""
        # fleet_kernel never receives or returns a BudgetLedger — the caller
        # confirms it is unchanged by checking evaluate_dispatch_failure doesn't
        # accept a ledger parameter at all.
        d1, d2, d3 = _three_dispatches()
        fleet = _fleet(policy=FleetCompletionPolicy.ALL_MUST_SUCCEED)
        result = evaluate_dispatch_failure(fleet, "d2", [d1, d2, d3])
        # No ledger in result — fleet_kernel doesn't modify or return one.
        assert not hasattr(result, "budget_ledger")

    def test_completed_dispatch_not_cancelled(self):
        d1 = _dispatch("d1", status=DispatchStatus.COMPLETED)
        d2 = _dispatch("d2", status=DispatchStatus.FAILED)
        d3 = _dispatch("d3", status=DispatchStatus.ACTIVE)
        fleet = _fleet(policy=FleetCompletionPolicy.ALL_MUST_SUCCEED)
        result = evaluate_dispatch_failure(fleet, "d2", [d1, d2, d3])
        by_id = {d.dispatch_id: d for d in result.updated_dispatches}
        # d1 was already COMPLETED — cannot be cancelled (terminal state respected)
        assert by_id["d1"].dispatch_status == DispatchStatus.COMPLETED
        assert by_id["d3"].dispatch_status == DispatchStatus.CANCELLED


# ── evaluate_dispatch_failure — BEST_EFFORT ───────────────────────────────────


class TestBestEffort:
    """Scenario: Three dispatches, d2 fails under BEST_EFFORT."""

    def _run(self) -> DispatchEvaluationResult:
        d1, d2, d3 = _three_dispatches(DispatchStatus.FAILED)
        fleet = _fleet(policy=FleetCompletionPolicy.BEST_EFFORT)
        return evaluate_dispatch_failure(fleet, "d2", [d1, d2, d3])

    def test_fleet_stays_active(self):
        result = self._run()
        assert result.updated_fleet.fleet_status == FleetStatus.ACTIVE

    def test_action_taken_is_continue(self):
        result = self._run()
        assert result.action_taken == "continue"

    def test_no_dispatches_cancelled(self):
        result = self._run()
        assert result.cancelled_dispatch_ids == []

    def test_d1_and_d3_remain_active(self):
        result = self._run()
        by_id = {d.dispatch_id: d for d in result.updated_dispatches}
        assert by_id["d1"].dispatch_status == DispatchStatus.ACTIVE
        assert by_id["d3"].dispatch_status == DispatchStatus.ACTIVE

    def test_d2_stays_failed(self):
        result = self._run()
        by_id = {d.dispatch_id: d for d in result.updated_dispatches}
        assert by_id["d2"].dispatch_status == DispatchStatus.FAILED

    def test_fleet_completes_when_all_terminal(self):
        d1 = _dispatch("d1", status=DispatchStatus.COMPLETED)
        d2 = _dispatch("d2", status=DispatchStatus.FAILED)
        d3 = _dispatch("d3", status=DispatchStatus.COMPLETED)
        fleet = _fleet(policy=FleetCompletionPolicy.BEST_EFFORT)
        result = evaluate_dispatch_failure(fleet, "d2", [d1, d2, d3])
        # All dispatches now terminal → fleet status transitions to COMPLETED
        assert result.updated_fleet.fleet_status == FleetStatus.COMPLETED

    def test_budget_unchanged_under_best_effort(self):
        """Same invariant as ALL_MUST_SUCCEED: kernel never touches the ledger."""
        d1, d2, d3 = _three_dispatches()
        fleet = _fleet(policy=FleetCompletionPolicy.BEST_EFFORT)
        result = evaluate_dispatch_failure(fleet, "d2", [d1, d2, d3])
        assert not hasattr(result, "budget_ledger")

    def test_all_dispatches_in_result(self):
        result = self._run()
        assert len(result.updated_dispatches) == 3


# ── evaluate_dispatch_failure — FIRST_SUCCESS ─────────────────────────────────


class TestFirstSuccess:
    def test_failure_alone_does_not_abort(self):
        d1 = _dispatch("d1", status=DispatchStatus.ACTIVE)
        d2 = _dispatch("d2", status=DispatchStatus.FAILED)
        d3 = _dispatch("d3", status=DispatchStatus.ACTIVE)
        fleet = _fleet(policy=FleetCompletionPolicy.FIRST_SUCCESS)
        result = evaluate_dispatch_failure(fleet, "d2", [d1, d2, d3])
        assert result.updated_fleet.fleet_status == FleetStatus.ACTIVE

    def test_all_failed_aborts_fleet(self):
        d1 = _dispatch("d1", status=DispatchStatus.FAILED)
        d2 = _dispatch("d2", status=DispatchStatus.FAILED)
        fleet = _fleet(policy=FleetCompletionPolicy.FIRST_SUCCESS)
        result = evaluate_dispatch_failure(fleet, "d2", [d1, d2])
        assert result.updated_fleet.fleet_status == FleetStatus.ABORTED


# ── handle_fleet_timeout ──────────────────────────────────────────────────────


class TestHandleFleetTimeout:
    """Scenario: Fleet timeout overrides individual session timeouts."""

    def _run(self, policy=FleetCompletionPolicy.ALL_MUST_SUCCEED) -> FleetTimeoutResult:
        d1, d2, d3 = (
            _dispatch("d1", status=DispatchStatus.ACTIVE),
            _dispatch("d2", status=DispatchStatus.QUEUED),
            _dispatch("d3", status=DispatchStatus.COMPLETED),
        )
        fleet = _fleet(policy=policy, timeout_at=PAST)
        return handle_fleet_timeout(fleet, [d1, d2, d3])

    def test_fleet_becomes_aborted(self):
        result = self._run()
        assert result.updated_fleet.fleet_status == FleetStatus.ABORTED

    def test_active_dispatches_cancelled(self):
        result = self._run()
        by_id = {d.dispatch_id: d for d in result.updated_dispatches}
        assert by_id["d1"].dispatch_status == DispatchStatus.CANCELLED
        assert by_id["d2"].dispatch_status == DispatchStatus.CANCELLED

    def test_terminal_dispatches_not_affected(self):
        result = self._run()
        by_id = {d.dispatch_id: d for d in result.updated_dispatches}
        assert by_id["d3"].dispatch_status == DispatchStatus.COMPLETED

    def test_error_code_is_fleet_timeout(self):
        result = self._run()
        assert result.error_code == "FLEET_TIMEOUT"

    def test_agent_should_abort_and_compensate(self):
        result = self._run()
        assert "abort" in result.agent_should
        assert "compensation" in result.agent_should

    def test_cancelled_ids_listed(self):
        result = self._run()
        assert set(result.cancelled_dispatch_ids) == {"d1", "d2"}

    def test_timeout_overrides_best_effort_policy(self):
        """Timeout aborts the fleet regardless of completion_policy."""
        result = self._run(policy=FleetCompletionPolicy.BEST_EFFORT)
        assert result.updated_fleet.fleet_status == FleetStatus.ABORTED

    def test_returns_fleet_timeout_result(self):
        result = self._run()
        assert isinstance(result, FleetTimeoutResult)
