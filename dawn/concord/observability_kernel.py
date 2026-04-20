"""CONCORD Phase 8 — Observability + telemetry layer.

Provides:
- EventLog / InMemoryEventLog  — append-only event log, queryable by resource/session/time
- EventEntry                   — frozen record linking session, intent, resource version, outcome
- TelemetryAccumulator         — windowed counter accumulator
- build_telemetry()            — compute CoordinationTelemetry from accumulated counters
- HotspotEntry                 — frozen data class for a single resource hotspot
- detect_hotspots()            — rank resources by composite contention/failure score

Normative rules enforced:

  EventLog:
  - append() is the only mutation; all reads return copies.
  - Queries by resource_id, session_id, and time range are supported; any combination
    of these may be supplied (additive AND filter).
  - query_by_resource / query_by_session return entries in append order.

  TelemetryAccumulator:
  - All counters start at zero and are only incremented (never decremented).
  - record_lease_request(*, contended) — total +1; if contended, contended +1.
  - record_queue_wait(wait_ms)         — total waits +1; sum += wait_ms.
  - record_queue_abandon()             — total +1 (must also call record_queue_wait first).
  - record_write_attempt(*, rejected)  — total +1; if rejected, stale_rejections +1.
  - record_budget_admission(*, throttled) — total +1; if throttled, throttles +1.
  - record_circuit_trip()             — trip_count +1.
  - record_compensation(*, invoked)   — total saga completions +1; if invoked, invocations +1.
  - record_retry(retry_class)         — histogram[retry_class] +1.

  build_telemetry():
  - lease_contention_rate    = contended_leases / total_lease_requests (0 if no requests).
  - average_queue_wait_ms    = total_queue_wait_ms / total_queue_waits (0 if none).
  - queue_abandonment_rate   = queue_abandons / total_queue_waits (0 if none).
  - stale_write_rejection_rate = stale_write_rejections / total_write_attempts (0 if none).
  - budget_throttle_rate     = budget_throttles / total_budget_admissions (0 if none).
  - circuit_breaker_trip_count = raw count.
  - compensation_invocation_rate = compensation_invocations / total_saga_completions (0 if none).
  - retry_distribution       = dict copy of histogram.

  detect_hotspots():
  - hotspot_score = weighted sum: lease_contention_weight * lease_count
                  + stale_write_weight * stale_write_count
                  + queue_wait_weight  * avg_queue_wait_ms
                  + compensation_weight * compensation_count.
  - primary_cause = dimension with highest individual contribution.
  - Returns list sorted by hotspot_score descending.
  - Entries with score == 0 are excluded.
"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from dawn.concord.types.entities import CoordinationTelemetry


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Event log ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EventEntry:
    """An immutable event log record for a single action outcome.

    Attributes:
        event_id:        Unique identifier for this log entry.
        resource_id:     Resource that was affected.
        resource_type:   Type key of the resource.
        session_id:      Session that performed the action.
        intent_id:       Intent that drove the action (or None for system events).
        action_name:     Name of the action performed.
        version_before:  Resource version before the action (None for reads).
        version_after:   Resource version after the action (None for reads).
        outcome:         Human-readable outcome string (e.g. "success", "denied", "timed_out").
        recorded_at:     Wall-clock time when this entry was appended.
        error_code:      Error/conflict code if the action was denied or failed.
    """

    event_id: str
    resource_id: str
    resource_type: str
    session_id: str
    action_name: str
    outcome: str
    recorded_at: datetime
    intent_id: Optional[str] = None
    version_before: Optional[int] = None
    version_after: Optional[int] = None
    error_code: Optional[str] = None


class EventLog(ABC):
    """Abstract append-only event log interface."""

    @abstractmethod
    def append(self, entry: EventEntry) -> None:
        """Append *entry* to the log."""

    @abstractmethod
    def query_by_resource(
        self,
        resource_id: str,
        *,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> list[EventEntry]:
        """Return entries for *resource_id*, optionally filtered by time range.

        Raises nothing on an unknown resource_id — returns empty list.
        """

    @abstractmethod
    def query_by_session(
        self,
        session_id: str,
        *,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> list[EventEntry]:
        """Return entries for *session_id*, optionally filtered by time range."""

    @abstractmethod
    def query_by_intent(self, intent_id: str) -> list[EventEntry]:
        """Return all entries referencing *intent_id*."""

    @abstractmethod
    def all_entries(self) -> list[EventEntry]:
        """Return all entries in append order."""


class InMemoryEventLog(EventLog):
    """List-backed EventLog for testing and local development."""

    def __init__(self) -> None:
        self._entries: list[EventEntry] = []

    def append(self, entry: EventEntry) -> None:
        self._entries.append(entry)

    def _filter_time(
        self,
        entries: list[EventEntry],
        since: Optional[datetime],
        until: Optional[datetime],
    ) -> list[EventEntry]:
        result = entries
        if since is not None:
            result = [e for e in result if e.recorded_at >= since]
        if until is not None:
            result = [e for e in result if e.recorded_at <= until]
        return result

    def query_by_resource(
        self,
        resource_id: str,
        *,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> list[EventEntry]:
        matched = [e for e in self._entries if e.resource_id == resource_id]
        return self._filter_time(matched, since, until)

    def query_by_session(
        self,
        session_id: str,
        *,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> list[EventEntry]:
        matched = [e for e in self._entries if e.session_id == session_id]
        return self._filter_time(matched, since, until)

    def query_by_intent(self, intent_id: str) -> list[EventEntry]:
        return [e for e in self._entries if e.intent_id == intent_id]

    def all_entries(self) -> list[EventEntry]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


# ── Telemetry accumulator ─────────────────────────────────────────────────────


@dataclass
class TelemetryAccumulator:
    """Windowed counter state for computing CoordinationTelemetry snapshots.

    All counters are non-negative integers or floats.  The accumulator is
    *not* thread-safe; callers must synchronise externally when needed.
    """

    window_start: datetime
    # Lease counters
    total_lease_requests: int = 0
    contended_lease_requests: int = 0
    # Queue counters
    total_queue_waits: int = 0
    total_queue_wait_ms: float = 0.0
    queue_abandons: int = 0
    # Write counters
    total_write_attempts: int = 0
    stale_write_rejections: int = 0
    # Budget counters
    total_budget_admissions: int = 0
    budget_throttles: int = 0
    # Circuit counters
    circuit_trip_count: int = 0
    # Compensation counters
    total_saga_completions: int = 0
    compensation_invocations: int = 0
    # Retry histogram: retry_class_name → count
    retry_histogram: dict[str, int] = field(default_factory=dict)

    # Per-resource detail (for hotspot detection)
    # resource_id → {lease_hits, stale_write_hits, queue_waits_ms_sum, queue_waits_count, compensation_hits}
    _resource_stats: dict[str, dict[str, float]] = field(
        default_factory=dict, repr=False
    )

    def _resource(self, resource_id: str) -> dict[str, float]:
        if resource_id not in self._resource_stats:
            self._resource_stats[resource_id] = {
                "lease_hits": 0.0,
                "stale_write_hits": 0.0,
                "queue_waits_ms_sum": 0.0,
                "queue_waits_count": 0.0,
                "compensation_hits": 0.0,
            }
        return self._resource_stats[resource_id]

    # ── Record methods ────────────────────────────────────────────────────────

    def record_lease_request(
        self, *, contended: bool, resource_id: Optional[str] = None
    ) -> None:
        """Record a lease request, marking it contended if another session held a lease."""
        self.total_lease_requests += 1
        if contended:
            self.contended_lease_requests += 1
            if resource_id:
                self._resource(resource_id)["lease_hits"] += 1.0

    def record_queue_wait(
        self, wait_ms: float, *, resource_id: Optional[str] = None
    ) -> None:
        """Record a completed queue wait (including zero-wait dequeues)."""
        self.total_queue_waits += 1
        self.total_queue_wait_ms += wait_ms
        if resource_id:
            r = self._resource(resource_id)
            r["queue_waits_ms_sum"] += wait_ms
            r["queue_waits_count"] += 1.0

    def record_queue_abandon(self, *, resource_id: Optional[str] = None) -> None:
        """Record an intent that was abandoned while queued (without completing)."""
        self.queue_abandons += 1

    def record_write_attempt(
        self, *, rejected: bool, resource_id: Optional[str] = None
    ) -> None:
        """Record a CAS write attempt, marking it rejected (STALE_VERSION) if it failed."""
        self.total_write_attempts += 1
        if rejected:
            self.stale_write_rejections += 1
            if resource_id:
                self._resource(resource_id)["stale_write_hits"] += 1.0

    def record_budget_admission(self, *, throttled: bool) -> None:
        """Record a budget admission check, marking it throttled if it was denied."""
        self.total_budget_admissions += 1
        if throttled:
            self.budget_throttles += 1

    def record_circuit_trip(self) -> None:
        """Record a circuit breaker trip event."""
        self.circuit_trip_count += 1

    def record_compensation(
        self, *, invoked: bool, resource_id: Optional[str] = None
    ) -> None:
        """Record a saga completion, marking whether compensation was invoked."""
        self.total_saga_completions += 1
        if invoked:
            self.compensation_invocations += 1
            if resource_id:
                self._resource(resource_id)["compensation_hits"] += 1.0

    def record_retry(self, retry_class: str) -> None:
        """Record a retry event, keyed by retry_class name."""
        self.retry_histogram[retry_class] = self.retry_histogram.get(retry_class, 0) + 1


# ── Telemetry snapshot builder ────────────────────────────────────────────────


def build_telemetry(
    acc: TelemetryAccumulator,
    *,
    window_end: datetime,
    resource_type: Optional[str] = None,
) -> CoordinationTelemetry:
    """Compute a CoordinationTelemetry snapshot from a TelemetryAccumulator.

    All rate fields are clamped to [0.0, 1.0] and default to 0.0 when the
    denominator is zero (no observations in the window).

    Args:
        acc:           The accumulator holding windowed counters.
        window_end:    End of the observation window (usually utcnow).
        resource_type: Optional resource-type filter label.

    Returns:
        A CoordinationTelemetry snapshot.
    """
    def _rate(numerator: int, denominator: int) -> float:
        if denominator == 0:
            return 0.0
        return max(0.0, min(1.0, numerator / denominator))

    def _avg(total: float, count: int) -> float:
        if count == 0:
            return 0.0
        return max(0.0, total / count)

    return CoordinationTelemetry(
        telemetry_window_start=acc.window_start,
        telemetry_window_end=window_end,
        resource_type=resource_type,
        lease_contention_rate=_rate(
            acc.contended_lease_requests, acc.total_lease_requests
        ),
        average_queue_wait_ms=_avg(acc.total_queue_wait_ms, acc.total_queue_waits),
        queue_abandonment_rate=_rate(acc.queue_abandons, acc.total_queue_waits),
        stale_write_rejection_rate=_rate(
            acc.stale_write_rejections, acc.total_write_attempts
        ),
        budget_throttle_rate=_rate(acc.budget_throttles, acc.total_budget_admissions),
        circuit_breaker_trip_count=acc.circuit_trip_count,
        compensation_invocation_rate=_rate(
            acc.compensation_invocations, acc.total_saga_completions
        ),
        retry_distribution=copy.copy(acc.retry_histogram),
    )


# ── Hotspot detection ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class HotspotEntry:
    """A single resource hotspot finding from detect_hotspots().

    Attributes:
        resource_id:        The resource with elevated contention/failure.
        hotspot_score:      Composite weighted score (higher = more concerning).
        primary_cause:      Dominant dimension driving the score.
        recommended_action: Optional operator remediation hint.
    """

    resource_id: str
    hotspot_score: float
    primary_cause: str
    recommended_action: Optional[str] = None


# Default scoring weights
_LEASE_WEIGHT: float = 2.0
_STALE_WRITE_WEIGHT: float = 3.0
_QUEUE_WAIT_WEIGHT: float = 0.001   # per ms — scales to be comparable with counts
_COMPENSATION_WEIGHT: float = 5.0

_CAUSE_RECOMMENDATIONS: dict[str, str] = {
    "lease_contention":  "Shorten lease TTL or increase token capacity for this resource.",
    "stale_writes":      "Increase CAS retry tolerance or add queue-first conflict strategy.",
    "queue_wait":        "Implement queue fairness policy or increase concurrency limit.",
    "compensation":      "Review saga compensation coverage and add inverse-action handlers.",
}


def detect_hotspots(
    acc: TelemetryAccumulator,
    *,
    lease_weight: float = _LEASE_WEIGHT,
    stale_write_weight: float = _STALE_WRITE_WEIGHT,
    queue_wait_weight: float = _QUEUE_WAIT_WEIGHT,
    compensation_weight: float = _COMPENSATION_WEIGHT,
) -> list[HotspotEntry]:
    """Rank resources by composite contention/failure score.

    Only resources with a non-zero score are returned.  Results are sorted
    descending by hotspot_score.

    Args:
        acc:                  TelemetryAccumulator with per-resource stats.
        lease_weight:         Weight applied to contended-lease count.
        stale_write_weight:   Weight applied to stale-write rejection count.
        queue_wait_weight:    Weight applied to average queue wait ms.
        compensation_weight:  Weight applied to compensation invocation count.

    Returns:
        Sorted list of HotspotEntry, highest score first.
    """
    results: list[HotspotEntry] = []

    for resource_id, stats in acc._resource_stats.items():
        lease_score = lease_weight * stats["lease_hits"]
        stale_score = stale_write_weight * stats["stale_write_hits"]
        avg_queue_ms = (
            stats["queue_waits_ms_sum"] / stats["queue_waits_count"]
            if stats["queue_waits_count"] > 0
            else 0.0
        )
        queue_score = queue_wait_weight * avg_queue_ms
        comp_score = compensation_weight * stats["compensation_hits"]

        total_score = lease_score + stale_score + queue_score + comp_score
        if total_score == 0.0:
            continue

        # Primary cause: dimension with the highest individual contribution
        contributions = {
            "lease_contention": lease_score,
            "stale_writes": stale_score,
            "queue_wait": queue_score,
            "compensation": comp_score,
        }
        primary_cause = max(contributions, key=lambda k: contributions[k])
        recommended_action = _CAUSE_RECOMMENDATIONS.get(primary_cause)

        results.append(
            HotspotEntry(
                resource_id=resource_id,
                hotspot_score=round(total_score, 4),
                primary_cause=primary_cause,
                recommended_action=recommended_action,
            )
        )

    return sorted(results, key=lambda h: h.hotspot_score, reverse=True)
