"""CONCORD v0.4-alpha — ExecutionEnvironment lifecycle kernel.

Provides:
- EnvironmentTeardownResult  — outcome of an unhealthy-environment teardown attempt
- mark_environment_unhealthy()  — transition status to UNHEALTHY
- get_blocking_intents()        — filter intents in ADMITTED or EXECUTING status
- handle_unhealthy_environment() — full lifecycle handler: detect → compensate → decide

Normative rules enforced:

  Blocking status check:
  - Intents in ADMITTED or EXECUTING are "blocking": teardown MUST NOT proceed
    while any are present (spec v0.4 §Gap-1).

  Compensation:
  - For each blocking intent a caller-supplied compensate_fn(intent_id) is called.
  - compensate_fn returns True on success, False on failure.
  - If no compensate_fn is provided, blocking intents are NOT automatically
    compensated; can_terminate remains False.

  Error codes:
  - ENVIRONMENT_UNHEALTHY is emitted whenever blocking intents are detected.
  - agent_should = "escalate_and_request_environment_replacement" (per error registry).
  - requires_context_refresh = True (per error registry).

  Terminal state:
  - can_terminate is True only when:
      (a) No blocking intents existed at the time of the unhealthy event, OR
      (b) Blocking intents existed and all compensation calls returned True.
  - updated_environment.status = TERMINATED when can_terminate is True;
    UNHEALTHY otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Callable, Optional

from dawn.concord.types.entities import ExecutionEnvironment, Intent
from dawn.concord.types.enums import EnvironmentStatus, IntentStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Blocking intent statuses — teardown forbidden while any of these are present.
_BLOCKING_STATUSES: frozenset[IntentStatus] = frozenset(
    {IntentStatus.ADMITTED, IntentStatus.EXECUTING}
)

# Error code constants from the v0.4 error registry.
_ERROR_ENVIRONMENT_UNHEALTHY = "ENVIRONMENT_UNHEALTHY"
_AGENT_SHOULD_ESCALATE = "escalate_and_request_environment_replacement"


# ── Result type ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EnvironmentTeardownResult:
    """Outcome of a handle_unhealthy_environment() call.

    Attributes:
        environment_id:       ID of the affected environment.
        updated_environment:  New ExecutionEnvironment state after the event.
        blocking_intent_ids:  Intent IDs that were in ADMITTED/EXECUTING at the time.
        compensation_outcomes: Mapping of intent_id → compensation success flag.
                               Empty when no compensate_fn was supplied.
        error_code:           'ENVIRONMENT_UNHEALTHY' if blocking intents were found;
                               None when the environment had no assigned session or
                               all blocking intents resolved cleanly.
        agent_should:         Recommended agent action (per error registry), or None.
        can_terminate:        True when the environment may safely be marked TERMINATED.
    """

    environment_id: str
    updated_environment: ExecutionEnvironment
    blocking_intent_ids: list[str]
    compensation_outcomes: dict[str, bool]
    error_code: Optional[str]
    agent_should: Optional[str]
    can_terminate: bool


# ── Core functions ────────────────────────────────────────────────────────────


def mark_environment_unhealthy(env: ExecutionEnvironment) -> ExecutionEnvironment:
    """Return a copy of *env* with status set to UNHEALTHY.

    Does nothing (returns unchanged copy) if status is already UNHEALTHY or TERMINATED.
    """
    if env.status in (EnvironmentStatus.UNHEALTHY, EnvironmentStatus.TERMINATED):
        return replace(env)
    return replace(env, status=EnvironmentStatus.UNHEALTHY)


def get_blocking_intents(intents: list[Intent]) -> list[Intent]:
    """Return intents whose status is ADMITTED or EXECUTING.

    These are the intents that block environment teardown per spec v0.4 §Gap-1.

    Args:
        intents: All intents associated with the bound session.

    Returns:
        Subset of intents in ADMITTED or EXECUTING status, in input order.
    """
    return [i for i in intents if i.status in _BLOCKING_STATUSES]


def handle_unhealthy_environment(
    env: ExecutionEnvironment,
    session_intents: list[Intent],
    *,
    compensate_fn: Optional[Callable[[str], bool]] = None,
) -> EnvironmentTeardownResult:
    """Handle an unhealthy environment event end-to-end.

    Flow:
    1. Mark the environment UNHEALTHY.
    2. Identify blocking intents (ADMITTED or EXECUTING) for the bound session.
    3. If no blocking intents → environment may be TERMINATED immediately; no error.
    4. If blocking intents exist:
       a. Emit ENVIRONMENT_UNHEALTHY (agent_should = escalate …).
       b. If compensate_fn is provided, call it for each blocking intent.
       c. can_terminate = True only when every compensation call returned True.
       d. updated_environment.status = TERMINATED if can_terminate; UNHEALTHY otherwise.

    Args:
        env:             The environment that went unhealthy.
        session_intents: All intents for the session bound to this environment.
                         Pass [] when there is no bound session.
        compensate_fn:   Optional callback(intent_id) → bool.  Called once per
                         blocking intent.  Return True on success, False on failure.
                         If not supplied, blocking intents are not auto-compensated
                         and can_terminate will be False when they are present.

    Returns:
        EnvironmentTeardownResult describing the outcome.
    """
    unhealthy_env = mark_environment_unhealthy(env)

    blocking = get_blocking_intents(session_intents)
    blocking_ids = [i.id for i in blocking]

    if not blocking:
        # Safe to terminate immediately — no blocking intents.
        terminated_env = replace(unhealthy_env, status=EnvironmentStatus.TERMINATED)
        return EnvironmentTeardownResult(
            environment_id=env.environment_id,
            updated_environment=terminated_env,
            blocking_intent_ids=[],
            compensation_outcomes={},
            error_code=None,
            agent_should=None,
            can_terminate=True,
        )

    # Blocking intents found — must attempt compensation before teardown.
    compensation_outcomes: dict[str, bool] = {}
    if compensate_fn is not None:
        for intent_id in blocking_ids:
            compensation_outcomes[intent_id] = compensate_fn(intent_id)

    all_compensated = bool(compensation_outcomes) and all(compensation_outcomes.values())

    final_status = EnvironmentStatus.TERMINATED if all_compensated else EnvironmentStatus.UNHEALTHY
    final_env = replace(unhealthy_env, status=final_status)

    return EnvironmentTeardownResult(
        environment_id=env.environment_id,
        updated_environment=final_env,
        blocking_intent_ids=blocking_ids,
        compensation_outcomes=compensation_outcomes,
        error_code=_ERROR_ENVIRONMENT_UNHEALTHY,
        agent_should=_AGENT_SHOULD_ESCALATE,
        can_terminate=all_compensated,
    )
