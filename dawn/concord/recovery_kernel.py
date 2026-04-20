"""CONCORD Phase 6 — Recovery + sagas layer.

Provides:
- build_receipt()            — construct an immutable Receipt from execution context
- SagaStore / InMemorySagaStore — persistence interface for SagaRun objects
- create_saga()             — initialise a new SagaRun in EXECUTING state
- advance_saga_step()       — move current_step forward by one
- complete_saga()           — mark a saga COMMITTED (all steps done)
- fail_saga()               — mark a saga FAILED
- is_saga_timed_out()       — evaluate timeout per SagaTimeoutPolicy
- enforce_timeout()         — fail the saga in the store if timed out
- CompensationResult        — frozen result type for compensate_saga
- is_saga_poisoned()        — True when attempt_count >= max_compensation_attempts
- compensate_saga()         — run compensation; handles all CompensationStrategy values

Normative rules enforced:

  Receipt:
  - previous_state / next_state extracted from resource.business_state
  - version_before / version_after taken from resource.version

  Saga lifecycle:
  - create_saga:        starts in EXECUTING, current_step = 0
  - advance_saga_step:  EXECUTING only; raises ValueError if already at last step
  - complete_saga:      EXECUTING only; → COMMITTED
  - fail_saga:          EXECUTING only; → FAILED

  Timeout (is_saga_timed_out):
  - FIXED:          elapsed since saga.started_at >= timeout_deadline_ms
  - STEP_ADAPTIVE:  elapsed since last_step_started_at >= step_timeout_ms
  - HEARTBEAT:      elapsed since last_heartbeat_at >= heartbeat_interval_ms
  - EXTERNAL_GATED: elapsed since last_step_started_at >= external_dependency_timeout_ms
  - Missing required timestamps → False (not timed out, cannot determine)

  enforce_timeout:
  - If timed out → fail_saga in store; return updated SagaRun
  - Otherwise → return None

  Compensation (compensate_saga):
  - Raises ValueError if strategy requires a callable that was not supplied.
  - NONE:           always succeeds; → COMPENSATED
  - MANUAL_ONLY:    always fails; COMPENSATION_FAILED; attempt recorded
  - INVERSE_ACTION: calls compensator(step_id) for each completed step in reverse;
                    all must return True for success
  - SAGA_HANDLER:   calls saga_handler(); must return True for success
  - is_saga_poisoned checked BEFORE incrementing attempt_count
  - Poison: attempt_count >= max_compensation_attempts → SAGA_POISONED; no attempt incremented
"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Optional

from dawn.concord.types.entities import Intent, Receipt, Resource, SagaRun
from dawn.concord.types.enums import (
    CompensationStrategy,
    IntentStatus,
    SagaTimeoutPolicy,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _elapsed_ms(since: datetime, now: datetime) -> int:
    return max(int((now - since).total_seconds() * 1000), 0)


# ── Receipt builder ───────────────────────────────────────────────────────────


def build_receipt(
    *,
    operation_id: str,
    intent: Intent,
    resource_before: Resource,
    resource_after: Resource,
    duration_ms: int,
    policy_decision: str,
    warnings: list[str] | None = None,
    errors: list[str] | None = None,
    environment_id: Optional[str] = None,
    entry_point_id: Optional[str] = None,
    scopes_applied: list[str] | None = None,
) -> Receipt:
    """Construct an immutable Receipt from execution context.

    Args:
        operation_id:    Unique identifier for this operation record.
        intent:          The admitted Intent that drove the action.
        resource_before: Resource snapshot *before* the mutation.
        resource_after:  Resource snapshot *after* the mutation.
        duration_ms:     Wall-clock duration of the action in milliseconds.
        policy_decision: Human-readable summary of the policy outcome (e.g. "allowed").
        warnings:        Non-fatal advisory messages (default: empty).
        errors:          Error messages if any partial failure occurred (default: empty).
        environment_id:  v0.4 execution-environment identifier (optional).
        entry_point_id:  v0.4 entry-point identifier (optional).
        scopes_applied:  ContextScope scope_ids active during the operation (default: empty).

    Returns:
        A frozen Receipt dataclass.
    """
    return Receipt(
        operation_id=operation_id,
        intent_id=intent.id,
        previous_state=copy.deepcopy(resource_before.business_state),
        next_state=copy.deepcopy(resource_after.business_state),
        version_before=resource_before.version,
        version_after=resource_after.version,
        result_status="success",
        duration_ms=duration_ms,
        policy_decision=policy_decision,
        warnings=list(warnings) if warnings else [],
        errors=list(errors) if errors else [],
        environment_id=environment_id,
        entry_point_id=entry_point_id,
        scopes_applied=list(scopes_applied) if scopes_applied else [],
    )


# ── SagaStore ─────────────────────────────────────────────────────────────────


class SagaStore(ABC):
    """Abstract persistence interface for SagaRun objects."""

    @abstractmethod
    def fetch(self, saga_id: str) -> SagaRun:
        """Return the SagaRun with the given id.

        Raises:
            KeyError: if saga_id is not found.
        """

    @abstractmethod
    def save(self, saga: SagaRun) -> SagaRun:
        """Persist *saga* and return a deep copy of the stored value."""

    @abstractmethod
    def exists(self, saga_id: str) -> bool:
        """Return True if a SagaRun with *saga_id* is stored."""


class InMemorySagaStore(SagaStore):
    """Dict-backed SagaStore for testing and local development."""

    def __init__(self) -> None:
        self._store: dict[str, SagaRun] = {}

    def fetch(self, saga_id: str) -> SagaRun:
        if saga_id not in self._store:
            raise KeyError(f"SagaRun '{saga_id}' not found.")
        return copy.deepcopy(self._store[saga_id])

    def save(self, saga: SagaRun) -> SagaRun:
        stored = copy.deepcopy(saga)
        self._store[saga.id] = stored
        return copy.deepcopy(stored)

    def exists(self, saga_id: str) -> bool:
        return saga_id in self._store

    def __len__(self) -> int:
        return len(self._store)


# ── Saga lifecycle ────────────────────────────────────────────────────────────


def create_saga(
    store: SagaStore,
    *,
    id: str,
    root_intent_id: str,
    steps: list[str],
    timeout_policy: SagaTimeoutPolicy,
    timeout_deadline_ms: int,
    compensation_strategy: CompensationStrategy,
    max_compensation_attempts: int,
    step_timeout_ms: Optional[int] = None,
    heartbeat_interval_ms: Optional[int] = None,
    external_dependency_timeout_ms: Optional[int] = None,
    started_at: Optional[datetime] = None,
) -> SagaRun:
    """Create and persist a new SagaRun in EXECUTING state.

    Args:
        store:                          Where to persist the saga.
        id:                             Unique saga identifier.
        root_intent_id:                 The Intent that initiated this saga.
        steps:                          Ordered list of step identifiers.
        timeout_policy:                 Which timeout policy governs the saga.
        timeout_deadline_ms:            Overall deadline (ms) for FIXED policy.
        compensation_strategy:          How to compensate on failure.
        max_compensation_attempts:      Max retries before SAGA_POISONED.
        step_timeout_ms:                Per-step deadline (STEP_ADAPTIVE).
        heartbeat_interval_ms:          Max gap between heartbeats (HEARTBEAT).
        external_dependency_timeout_ms: External wait deadline (EXTERNAL_GATED).
        started_at:                     Wall-clock start time; defaults to utcnow().

    Returns:
        The persisted SagaRun.

    Raises:
        ValueError: if steps is empty.
    """
    if not steps:
        raise ValueError("SagaRun must have at least one step.")

    saga = SagaRun(
        id=id,
        root_intent_id=root_intent_id,
        steps=list(steps),
        current_step=0,
        timeout_policy=timeout_policy,
        timeout_deadline_ms=timeout_deadline_ms,
        compensation_strategy=compensation_strategy,
        max_compensation_attempts=max_compensation_attempts,
        attempt_count=0,
        status=IntentStatus.EXECUTING,
        step_timeout_ms=step_timeout_ms,
        heartbeat_interval_ms=heartbeat_interval_ms,
        external_dependency_timeout_ms=external_dependency_timeout_ms,
        started_at=started_at or _utcnow(),
    )
    return store.save(saga)


def advance_saga_step(store: SagaStore, saga_id: str) -> SagaRun:
    """Increment current_step by one for an EXECUTING saga.

    Raises:
        ValueError: if the saga is not EXECUTING, or current_step is already
                    at the last step (use complete_saga instead).
        KeyError:   if saga_id is not found.
    """
    saga = store.fetch(saga_id)

    if saga.status != IntentStatus.EXECUTING:
        raise ValueError(
            f"Cannot advance step: saga '{saga_id}' is not EXECUTING "
            f"(current status={saga.status.value})."
        )

    last_step_index = len(saga.steps) - 1
    if saga.current_step >= last_step_index:
        raise ValueError(
            f"Saga '{saga_id}' is already at the last step "
            f"({saga.current_step}/{last_step_index}). Use complete_saga() instead."
        )

    return store.save(replace(saga, current_step=saga.current_step + 1))


def complete_saga(store: SagaStore, saga_id: str) -> SagaRun:
    """Mark a saga COMMITTED (all steps successfully executed).

    Raises:
        ValueError: if the saga is not EXECUTING.
        KeyError:   if saga_id is not found.
    """
    saga = store.fetch(saga_id)

    if saga.status != IntentStatus.EXECUTING:
        raise ValueError(
            f"Cannot complete saga '{saga_id}': expected EXECUTING, "
            f"got {saga.status.value}."
        )

    return store.save(replace(saga, status=IntentStatus.COMMITTED))


def fail_saga(store: SagaStore, saga_id: str) -> SagaRun:
    """Mark a saga FAILED.

    Raises:
        ValueError: if the saga is not EXECUTING.
        KeyError:   if saga_id is not found.
    """
    saga = store.fetch(saga_id)

    if saga.status != IntentStatus.EXECUTING:
        raise ValueError(
            f"Cannot fail saga '{saga_id}': expected EXECUTING, "
            f"got {saga.status.value}."
        )

    return store.save(replace(saga, status=IntentStatus.FAILED))


# ── Timeout enforcer ──────────────────────────────────────────────────────────


def is_saga_timed_out(
    saga: SagaRun,
    *,
    now: datetime,
    last_step_started_at: Optional[datetime] = None,
    last_heartbeat_at: Optional[datetime] = None,
) -> bool:
    """Return True if the saga has exceeded its timeout.

    Policy rules:
      FIXED:          elapsed since saga.started_at >= timeout_deadline_ms.
      STEP_ADAPTIVE:  elapsed since last_step_started_at >= step_timeout_ms.
      HEARTBEAT:      elapsed since last_heartbeat_at >= heartbeat_interval_ms.
      EXTERNAL_GATED: elapsed since last_step_started_at >= external_dependency_timeout_ms.

    Returns False if any required timestamp or saga field is missing — the
    caller is responsible for supplying the correct parameters.

    Args:
        saga:                 The SagaRun to evaluate.
        now:                  Current wall-clock time (UTC).
        last_step_started_at: When the current step began (STEP_ADAPTIVE / EXTERNAL_GATED).
        last_heartbeat_at:    When the last heartbeat was recorded (HEARTBEAT).
    """
    policy = saga.timeout_policy

    if policy == SagaTimeoutPolicy.FIXED:
        if saga.started_at is None:
            return False
        return _elapsed_ms(saga.started_at, now) >= saga.timeout_deadline_ms

    if policy == SagaTimeoutPolicy.STEP_ADAPTIVE:
        if last_step_started_at is None or saga.step_timeout_ms is None:
            return False
        return _elapsed_ms(last_step_started_at, now) >= saga.step_timeout_ms

    if policy == SagaTimeoutPolicy.HEARTBEAT:
        if last_heartbeat_at is None or saga.heartbeat_interval_ms is None:
            return False
        return _elapsed_ms(last_heartbeat_at, now) >= saga.heartbeat_interval_ms

    if policy == SagaTimeoutPolicy.EXTERNAL_GATED:
        if last_step_started_at is None or saga.external_dependency_timeout_ms is None:
            return False
        return _elapsed_ms(last_step_started_at, now) >= saga.external_dependency_timeout_ms

    return False  # pragma: no cover


def enforce_timeout(
    store: SagaStore,
    saga_id: str,
    *,
    now: datetime,
    last_step_started_at: Optional[datetime] = None,
    last_heartbeat_at: Optional[datetime] = None,
) -> Optional[SagaRun]:
    """Fail the saga in the store if its timeout has been exceeded.

    Args:
        store:                SagaStore to read from and write to.
        saga_id:              ID of the saga to check.
        now:                  Current wall-clock time.
        last_step_started_at: Forwarded to is_saga_timed_out.
        last_heartbeat_at:    Forwarded to is_saga_timed_out.

    Returns:
        The updated (FAILED) SagaRun if it timed out; None if still within deadline.

    Raises:
        KeyError:   if saga_id is not found.
        ValueError: if the saga is not EXECUTING (already terminal/etc.).
    """
    saga = store.fetch(saga_id)
    if is_saga_timed_out(
        saga,
        now=now,
        last_step_started_at=last_step_started_at,
        last_heartbeat_at=last_heartbeat_at,
    ):
        return fail_saga(store, saga_id)
    return None


# ── Compensation ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CompensationResult:
    """Result of a compensate_saga call.

    Attributes:
        success:       True when compensation completed successfully.
        error_code:    SAGA_POISONED or COMPENSATION_FAILED when unsuccessful.
        reason:        Human-readable explanation on failure.
        attempts_used: attempt_count on the saga AFTER this call (or before, if poisoned).
    """

    success: bool
    error_code: Optional[str] = None
    reason: Optional[str] = None
    attempts_used: int = 0


def is_saga_poisoned(saga: SagaRun) -> bool:
    """Return True when the saga has exhausted all compensation attempts.

    A poisoned saga must not be retried automatically; operator intervention
    is required.
    """
    return saga.attempt_count >= saga.max_compensation_attempts


def compensate_saga(
    store: SagaStore,
    saga_id: str,
    *,
    compensator: Optional[Callable[[str], bool]] = None,
    saga_handler: Optional[Callable[[], bool]] = None,
) -> CompensationResult:
    """Attempt to compensate a failed saga.

    Checks poison status BEFORE incrementing attempt_count.  Increments
    attempt_count, executes compensation, and persists the updated saga.

    Strategy behaviours:
      NONE:           Always succeeds; → COMPENSATED.
      MANUAL_ONLY:    Always fails; COMPENSATION_FAILED; attempt recorded.
      INVERSE_ACTION: Calls compensator(step_id) for each completed step in
                      reverse order.  All must return True for success.
      SAGA_HANDLER:   Calls saga_handler(); must return True for success.

    Args:
        store:        SagaStore to read from and write to.
        saga_id:      ID of the saga to compensate.
        compensator:  Callable(step_id) → bool; required for INVERSE_ACTION.
        saga_handler: Callable() → bool; required for SAGA_HANDLER.

    Returns:
        CompensationResult.

    Raises:
        KeyError:    if saga_id is not found.
        ValueError:  if a required callable is missing for the chosen strategy.
    """
    saga = store.fetch(saga_id)

    # Poison check: do NOT increment attempt_count, just report.
    if is_saga_poisoned(saga):
        return CompensationResult(
            success=False,
            error_code="SAGA_POISONED",
            reason=(
                f"Saga '{saga_id}' has exhausted all "
                f"{saga.max_compensation_attempts} compensation attempts."
            ),
            attempts_used=saga.attempt_count,
        )

    # Increment attempt count for this attempt.
    saga = replace(saga, attempt_count=saga.attempt_count + 1)

    strategy = saga.compensation_strategy

    # ── NONE ─────────────────────────────────────────────────────────────────
    if strategy == CompensationStrategy.NONE:
        saga = replace(saga, status=IntentStatus.COMPENSATED)
        store.save(saga)
        return CompensationResult(success=True, attempts_used=saga.attempt_count)

    # ── MANUAL_ONLY ───────────────────────────────────────────────────────────
    if strategy == CompensationStrategy.MANUAL_ONLY:
        store.save(saga)
        return CompensationResult(
            success=False,
            error_code="COMPENSATION_FAILED",
            reason=(
                f"Saga '{saga_id}' requires manual compensation "
                "(strategy=manual_only); operator intervention needed."
            ),
            attempts_used=saga.attempt_count,
        )

    # ── INVERSE_ACTION ────────────────────────────────────────────────────────
    if strategy == CompensationStrategy.INVERSE_ACTION:
        if compensator is None:
            raise ValueError(
                "compensator callable is required for INVERSE_ACTION strategy."
            )
        steps_to_compensate = list(reversed(saga.steps[: saga.current_step + 1]))
        all_ok = all(compensator(step_id) for step_id in steps_to_compensate)
        if all_ok:
            saga = replace(saga, status=IntentStatus.COMPENSATED)
            store.save(saga)
            return CompensationResult(success=True, attempts_used=saga.attempt_count)
        store.save(saga)
        return CompensationResult(
            success=False,
            error_code="COMPENSATION_FAILED",
            reason=f"Inverse-action compensation failed for saga '{saga_id}'.",
            attempts_used=saga.attempt_count,
        )

    # ── SAGA_HANDLER ──────────────────────────────────────────────────────────
    if strategy == CompensationStrategy.SAGA_HANDLER:
        if saga_handler is None:
            raise ValueError(
                "saga_handler callable is required for SAGA_HANDLER strategy."
            )
        ok = saga_handler()
        if ok:
            saga = replace(saga, status=IntentStatus.COMPENSATED)
            store.save(saga)
            return CompensationResult(success=True, attempts_used=saga.attempt_count)
        store.save(saga)
        return CompensationResult(
            success=False,
            error_code="COMPENSATION_FAILED",
            reason=f"Saga handler failed for saga '{saga_id}'.",
            attempts_used=saga.attempt_count,
        )

    raise ValueError(  # pragma: no cover
        f"Unhandled CompensationStrategy: {strategy!r}"
    )
