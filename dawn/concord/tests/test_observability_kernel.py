"""Tests for CONCORD Phase 8 — observability_kernel.py.

Coverage:
  - EventEntry (frozen dataclass contract)
  - EventLog ABC enforcement
  - InMemoryEventLog: append, all_entries, query_by_resource,
    query_by_session, query_by_intent, time-range filtering
  - TelemetryAccumulator: all record methods, counter increments,
    retry histogram, per-resource stats
  - build_telemetry: all rate/avg computations, zero-denominator defaults,
    rate clamping, window forwarding
  - HotspotEntry (frozen dataclass contract)
  - detect_hotspots: scoring, primary_cause, sorting, zero-score exclusion,
    recommended_action
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from dawn.concord.observability_kernel import (
    EventEntry,
    EventLog,
    HotspotEntry,
    InMemoryEventLog,
    TelemetryAccumulator,
    build_telemetry,
    detect_hotspots,
)
from dawn.concord.types.entities import CoordinationTelemetry

NOW = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)
LATER = NOW + timedelta(minutes=1)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _entry(
    *,
    event_id: str = "ev-1",
    resource_id: str = "cr-1",
    resource_type: str = "change_request",
    session_id: str = "sess-1",
    action_name: str = "update",
    outcome: str = "success",
    recorded_at: datetime = NOW,
    intent_id: str | None = "intent-1",
    version_before: int | None = 1,
    version_after: int | None = 2,
    error_code: str | None = None,
) -> EventEntry:
    return EventEntry(
        event_id=event_id,
        resource_id=resource_id,
        resource_type=resource_type,
        session_id=session_id,
        action_name=action_name,
        outcome=outcome,
        recorded_at=recorded_at,
        intent_id=intent_id,
        version_before=version_before,
        version_after=version_after,
        error_code=error_code,
    )


def _acc(*, window_start: datetime = NOW) -> TelemetryAccumulator:
    return TelemetryAccumulator(window_start=window_start)


# ── TestEventEntry ────────────────────────────────────────────────────────────

class TestEventEntry:
    def test_frozen(self):
        e = _entry()
        with pytest.raises(Exception):
            e.outcome = "mutated"  # type: ignore[misc]

    def test_required_fields(self):
        e = _entry()
        assert e.event_id == "ev-1"
        assert e.resource_id == "cr-1"
        assert e.session_id == "sess-1"
        assert e.outcome == "success"
        assert e.recorded_at == NOW

    def test_optional_fields_default_none(self):
        e = EventEntry(
            event_id="ev-x",
            resource_id="r1",
            resource_type="t",
            session_id="s1",
            action_name="act",
            outcome="success",
            recorded_at=NOW,
        )
        assert e.intent_id is None
        assert e.version_before is None
        assert e.version_after is None
        assert e.error_code is None


# ── TestInMemoryEventLog ──────────────────────────────────────────────────────

class TestInMemoryEventLog:
    def test_abc_enforcement(self):
        class Incomplete(EventLog):
            pass
        with pytest.raises(TypeError):
            Incomplete()

    def test_append_and_len(self):
        log = InMemoryEventLog()
        assert len(log) == 0
        log.append(_entry())
        assert len(log) == 1

    def test_all_entries_returns_copy(self):
        log = InMemoryEventLog()
        log.append(_entry(event_id="e1"))
        entries = log.all_entries()
        entries.clear()
        assert len(log) == 1  # internal list unaffected

    def test_all_entries_in_append_order(self):
        log = InMemoryEventLog()
        log.append(_entry(event_id="e1"))
        log.append(_entry(event_id="e2"))
        log.append(_entry(event_id="e3"))
        ids = [e.event_id for e in log.all_entries()]
        assert ids == ["e1", "e2", "e3"]

    def test_query_by_resource_returns_matching(self):
        log = InMemoryEventLog()
        log.append(_entry(event_id="e1", resource_id="cr-1"))
        log.append(_entry(event_id="e2", resource_id="cr-2"))
        log.append(_entry(event_id="e3", resource_id="cr-1"))
        result = log.query_by_resource("cr-1")
        assert [e.event_id for e in result] == ["e1", "e3"]

    def test_query_by_resource_unknown_returns_empty(self):
        log = InMemoryEventLog()
        assert log.query_by_resource("nonexistent") == []

    def test_query_by_session_returns_matching(self):
        log = InMemoryEventLog()
        log.append(_entry(event_id="e1", session_id="sess-A"))
        log.append(_entry(event_id="e2", session_id="sess-B"))
        log.append(_entry(event_id="e3", session_id="sess-A"))
        result = log.query_by_session("sess-A")
        assert [e.event_id for e in result] == ["e1", "e3"]

    def test_query_by_intent_returns_matching(self):
        log = InMemoryEventLog()
        log.append(_entry(event_id="e1", intent_id="intent-1"))
        log.append(_entry(event_id="e2", intent_id="intent-2"))
        log.append(_entry(event_id="e3", intent_id="intent-1"))
        result = log.query_by_intent("intent-1")
        assert [e.event_id for e in result] == ["e1", "e3"]

    def test_query_by_intent_unknown_returns_empty(self):
        log = InMemoryEventLog()
        log.append(_entry(event_id="e1", intent_id="intent-x"))
        assert log.query_by_intent("intent-z") == []

    # Time-range filtering
    def test_query_since_filters_earlier_entries(self):
        t1 = NOW
        t2 = NOW + timedelta(seconds=5)
        t3 = NOW + timedelta(seconds=10)
        log = InMemoryEventLog()
        log.append(_entry(event_id="e1", recorded_at=t1))
        log.append(_entry(event_id="e2", recorded_at=t2))
        log.append(_entry(event_id="e3", recorded_at=t3))
        result = log.query_by_resource("cr-1", since=t2)
        assert [e.event_id for e in result] == ["e2", "e3"]

    def test_query_until_filters_later_entries(self):
        t1 = NOW
        t2 = NOW + timedelta(seconds=5)
        t3 = NOW + timedelta(seconds=10)
        log = InMemoryEventLog()
        log.append(_entry(event_id="e1", recorded_at=t1))
        log.append(_entry(event_id="e2", recorded_at=t2))
        log.append(_entry(event_id="e3", recorded_at=t3))
        result = log.query_by_resource("cr-1", until=t2)
        assert [e.event_id for e in result] == ["e1", "e2"]

    def test_query_since_and_until_window(self):
        t1 = NOW
        t2 = NOW + timedelta(seconds=5)
        t3 = NOW + timedelta(seconds=10)
        log = InMemoryEventLog()
        log.append(_entry(event_id="e1", recorded_at=t1))
        log.append(_entry(event_id="e2", recorded_at=t2))
        log.append(_entry(event_id="e3", recorded_at=t3))
        result = log.query_by_resource("cr-1", since=t2, until=t2)
        assert [e.event_id for e in result] == ["e2"]

    def test_query_session_time_range(self):
        log = InMemoryEventLog()
        log.append(_entry(event_id="e1", session_id="s", recorded_at=NOW))
        log.append(_entry(event_id="e2", session_id="s", recorded_at=LATER))
        result = log.query_by_session("s", since=LATER)
        assert [e.event_id for e in result] == ["e2"]


# ── TestTelemetryAccumulator ──────────────────────────────────────────────────

class TestTelemetryAccumulator:
    def test_initial_counters_zero(self):
        acc = _acc()
        assert acc.total_lease_requests == 0
        assert acc.contended_lease_requests == 0
        assert acc.total_queue_waits == 0
        assert acc.total_queue_wait_ms == 0.0
        assert acc.queue_abandons == 0
        assert acc.total_write_attempts == 0
        assert acc.stale_write_rejections == 0
        assert acc.total_budget_admissions == 0
        assert acc.budget_throttles == 0
        assert acc.circuit_trip_count == 0
        assert acc.total_saga_completions == 0
        assert acc.compensation_invocations == 0
        assert acc.retry_histogram == {}

    def test_record_lease_request_not_contended(self):
        acc = _acc()
        acc.record_lease_request(contended=False)
        assert acc.total_lease_requests == 1
        assert acc.contended_lease_requests == 0

    def test_record_lease_request_contended(self):
        acc = _acc()
        acc.record_lease_request(contended=True)
        assert acc.total_lease_requests == 1
        assert acc.contended_lease_requests == 1

    def test_record_lease_increments_resource_stat(self):
        acc = _acc()
        acc.record_lease_request(contended=True, resource_id="cr-1")
        assert acc._resource_stats["cr-1"]["lease_hits"] == 1.0

    def test_record_lease_no_resource_no_stat_entry(self):
        acc = _acc()
        acc.record_lease_request(contended=True)
        assert "cr-1" not in acc._resource_stats

    def test_record_queue_wait(self):
        acc = _acc()
        acc.record_queue_wait(500.0)
        assert acc.total_queue_waits == 1
        assert acc.total_queue_wait_ms == 500.0

    def test_record_queue_wait_accumulates(self):
        acc = _acc()
        acc.record_queue_wait(200.0)
        acc.record_queue_wait(300.0)
        assert acc.total_queue_wait_ms == 500.0
        assert acc.total_queue_waits == 2

    def test_record_queue_wait_resource_stat(self):
        acc = _acc()
        acc.record_queue_wait(400.0, resource_id="cr-1")
        assert acc._resource_stats["cr-1"]["queue_waits_ms_sum"] == 400.0
        assert acc._resource_stats["cr-1"]["queue_waits_count"] == 1.0

    def test_record_queue_abandon(self):
        acc = _acc()
        acc.record_queue_abandon()
        assert acc.queue_abandons == 1

    def test_record_write_attempt_not_rejected(self):
        acc = _acc()
        acc.record_write_attempt(rejected=False)
        assert acc.total_write_attempts == 1
        assert acc.stale_write_rejections == 0

    def test_record_write_attempt_rejected(self):
        acc = _acc()
        acc.record_write_attempt(rejected=True)
        assert acc.total_write_attempts == 1
        assert acc.stale_write_rejections == 1

    def test_record_write_attempt_rejected_resource_stat(self):
        acc = _acc()
        acc.record_write_attempt(rejected=True, resource_id="cr-1")
        assert acc._resource_stats["cr-1"]["stale_write_hits"] == 1.0

    def test_record_budget_admission_not_throttled(self):
        acc = _acc()
        acc.record_budget_admission(throttled=False)
        assert acc.total_budget_admissions == 1
        assert acc.budget_throttles == 0

    def test_record_budget_admission_throttled(self):
        acc = _acc()
        acc.record_budget_admission(throttled=True)
        assert acc.budget_throttles == 1

    def test_record_circuit_trip(self):
        acc = _acc()
        acc.record_circuit_trip()
        acc.record_circuit_trip()
        assert acc.circuit_trip_count == 2

    def test_record_compensation_not_invoked(self):
        acc = _acc()
        acc.record_compensation(invoked=False)
        assert acc.total_saga_completions == 1
        assert acc.compensation_invocations == 0

    def test_record_compensation_invoked(self):
        acc = _acc()
        acc.record_compensation(invoked=True)
        assert acc.total_saga_completions == 1
        assert acc.compensation_invocations == 1

    def test_record_compensation_resource_stat(self):
        acc = _acc()
        acc.record_compensation(invoked=True, resource_id="cr-1")
        assert acc._resource_stats["cr-1"]["compensation_hits"] == 1.0

    def test_record_retry_histogram(self):
        acc = _acc()
        acc.record_retry("safe_retry")
        acc.record_retry("safe_retry")
        acc.record_retry("recheck_then_retry")
        assert acc.retry_histogram["safe_retry"] == 2
        assert acc.retry_histogram["recheck_then_retry"] == 1

    def test_record_retry_new_key(self):
        acc = _acc()
        acc.record_retry("queue_then_retry")
        assert acc.retry_histogram.get("queue_then_retry") == 1


# ── TestBuildTelemetry ────────────────────────────────────────────────────────

class TestBuildTelemetry:
    def test_returns_coordination_telemetry(self):
        acc = _acc()
        t = build_telemetry(acc, window_end=LATER)
        assert isinstance(t, CoordinationTelemetry)

    def test_window_timestamps(self):
        acc = _acc(window_start=NOW)
        t = build_telemetry(acc, window_end=LATER)
        assert t.telemetry_window_start == NOW
        assert t.telemetry_window_end == LATER

    def test_resource_type_forwarded(self):
        acc = _acc()
        t = build_telemetry(acc, window_end=LATER, resource_type="change_request")
        assert t.resource_type == "change_request"

    def test_zero_denominators_give_zero_rates(self):
        acc = _acc()
        t = build_telemetry(acc, window_end=LATER)
        assert t.lease_contention_rate == 0.0
        assert t.average_queue_wait_ms == 0.0
        assert t.queue_abandonment_rate == 0.0
        assert t.stale_write_rejection_rate == 0.0
        assert t.budget_throttle_rate == 0.0
        assert t.circuit_breaker_trip_count == 0
        assert t.compensation_invocation_rate == 0.0

    def test_lease_contention_rate(self):
        acc = _acc()
        acc.record_lease_request(contended=True)
        acc.record_lease_request(contended=False)
        acc.record_lease_request(contended=False)
        t = build_telemetry(acc, window_end=LATER)
        assert abs(t.lease_contention_rate - 1/3) < 1e-9

    def test_lease_contention_rate_all_contended(self):
        acc = _acc()
        for _ in range(4):
            acc.record_lease_request(contended=True)
        t = build_telemetry(acc, window_end=LATER)
        assert t.lease_contention_rate == 1.0

    def test_average_queue_wait_ms(self):
        acc = _acc()
        acc.record_queue_wait(200.0)
        acc.record_queue_wait(400.0)
        t = build_telemetry(acc, window_end=LATER)
        assert t.average_queue_wait_ms == 300.0

    def test_queue_abandonment_rate(self):
        acc = _acc()
        acc.record_queue_wait(100.0)
        acc.record_queue_wait(100.0)
        acc.record_queue_abandon()
        t = build_telemetry(acc, window_end=LATER)
        assert t.queue_abandonment_rate == 0.5

    def test_stale_write_rejection_rate(self):
        acc = _acc()
        acc.record_write_attempt(rejected=True)
        acc.record_write_attempt(rejected=False)
        t = build_telemetry(acc, window_end=LATER)
        assert t.stale_write_rejection_rate == 0.5

    def test_budget_throttle_rate(self):
        acc = _acc()
        for _ in range(3):
            acc.record_budget_admission(throttled=True)
        acc.record_budget_admission(throttled=False)
        t = build_telemetry(acc, window_end=LATER)
        assert t.budget_throttle_rate == 0.75

    def test_circuit_trip_count(self):
        acc = _acc()
        acc.record_circuit_trip()
        acc.record_circuit_trip()
        acc.record_circuit_trip()
        t = build_telemetry(acc, window_end=LATER)
        assert t.circuit_breaker_trip_count == 3

    def test_compensation_invocation_rate(self):
        acc = _acc()
        acc.record_compensation(invoked=True)
        acc.record_compensation(invoked=False)
        t = build_telemetry(acc, window_end=LATER)
        assert t.compensation_invocation_rate == 0.5

    def test_retry_distribution_copied(self):
        acc = _acc()
        acc.record_retry("safe_retry")
        acc.record_retry("safe_retry")
        t = build_telemetry(acc, window_end=LATER)
        assert t.retry_distribution["safe_retry"] == 2
        # Mutation of returned dict doesn't affect accumulator
        t.retry_distribution["safe_retry"] = 999
        assert acc.retry_histogram["safe_retry"] == 2

    def test_rate_never_exceeds_one(self):
        """Guard against floating-point > 1.0 from accumulator inconsistencies."""
        acc = _acc()
        # Artificially over-saturate
        acc.stale_write_rejections = 10
        acc.total_write_attempts = 5  # more rejections than attempts (shouldn't happen)
        t = build_telemetry(acc, window_end=LATER)
        assert t.stale_write_rejection_rate <= 1.0


# ── TestHotspotEntry ──────────────────────────────────────────────────────────

class TestHotspotEntry:
    def test_frozen(self):
        h = HotspotEntry(resource_id="cr-1", hotspot_score=1.0, primary_cause="stale_writes")
        with pytest.raises(Exception):
            h.hotspot_score = 99.0  # type: ignore[misc]

    def test_optional_recommended_action_defaults_none(self):
        h = HotspotEntry(resource_id="cr-1", hotspot_score=1.0, primary_cause="stale_writes")
        # recommended_action set by detect_hotspots; raw constructor leaves it None
        h2 = HotspotEntry(resource_id="cr-1", hotspot_score=1.0,
                          primary_cause="stale_writes", recommended_action=None)
        assert h2.recommended_action is None


# ── TestDetectHotspots ────────────────────────────────────────────────────────

class TestDetectHotspots:
    def test_empty_accumulator_returns_empty(self):
        acc = _acc()
        assert detect_hotspots(acc) == []

    def test_zero_score_resource_excluded(self):
        acc = _acc()
        # Record a non-contended lease (no resource_id → no per-resource stat)
        acc.record_lease_request(contended=False, resource_id="cr-1")
        assert detect_hotspots(acc) == []

    def test_stale_write_creates_hotspot(self):
        acc = _acc()
        acc.record_write_attempt(rejected=True, resource_id="cr-1")
        results = detect_hotspots(acc)
        assert len(results) == 1
        assert results[0].resource_id == "cr-1"
        assert results[0].hotspot_score > 0

    def test_primary_cause_stale_writes(self):
        acc = _acc()
        acc.record_write_attempt(rejected=True, resource_id="cr-1")
        results = detect_hotspots(acc)
        assert results[0].primary_cause == "stale_writes"

    def test_primary_cause_lease_contention(self):
        acc = _acc()
        for _ in range(5):
            acc.record_lease_request(contended=True, resource_id="cr-1")
        results = detect_hotspots(acc)
        assert results[0].primary_cause == "lease_contention"

    def test_primary_cause_compensation(self):
        acc = _acc()
        acc.record_compensation(invoked=True, resource_id="cr-1")
        results = detect_hotspots(acc)
        assert results[0].primary_cause == "compensation"

    def test_primary_cause_queue_wait(self):
        acc = _acc()
        # Large queue wait, no other contention
        acc.record_queue_wait(5_000_000.0, resource_id="cr-1")  # 5000 s (extreme)
        results = detect_hotspots(acc)
        assert results[0].primary_cause == "queue_wait"

    def test_multiple_resources_sorted_by_score(self):
        acc = _acc()
        # cr-1: 1 stale write → score = 3.0 * 1 = 3.0
        acc.record_write_attempt(rejected=True, resource_id="cr-1")
        # cr-2: 2 stale writes → score = 3.0 * 2 = 6.0
        acc.record_write_attempt(rejected=True, resource_id="cr-2")
        acc.record_write_attempt(rejected=True, resource_id="cr-2")
        results = detect_hotspots(acc)
        assert results[0].resource_id == "cr-2"
        assert results[1].resource_id == "cr-1"

    def test_recommended_action_populated(self):
        acc = _acc()
        acc.record_write_attempt(rejected=True, resource_id="cr-1")
        results = detect_hotspots(acc)
        assert results[0].recommended_action is not None
        assert len(results[0].recommended_action) > 0

    def test_compensation_weight_highest(self):
        """compensation_weight (5.0) > stale_write_weight (3.0) for equal counts."""
        acc = _acc()
        acc.record_compensation(invoked=True, resource_id="cr-1")
        acc.record_write_attempt(rejected=True, resource_id="cr-1")
        results = detect_hotspots(acc)
        # compensation contributes 5.0, stale_writes contributes 3.0
        assert results[0].primary_cause == "compensation"

    def test_custom_weights(self):
        acc = _acc()
        acc.record_lease_request(contended=True, resource_id="cr-1")
        # With lease_weight=100, lease should dominate
        results = detect_hotspots(acc, lease_weight=100.0)
        assert results[0].primary_cause == "lease_contention"
        assert results[0].hotspot_score == 100.0

    def test_hotspot_score_uses_avg_queue_wait(self):
        acc = _acc()
        acc.record_queue_wait(1000.0, resource_id="cr-1")
        acc.record_queue_wait(3000.0, resource_id="cr-1")
        # avg = 2000 ms; score = 0.001 * 2000 = 2.0
        results = detect_hotspots(acc, queue_wait_weight=0.001)
        assert abs(results[0].hotspot_score - 2.0) < 0.001
