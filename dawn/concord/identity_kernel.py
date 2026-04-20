"""CONCORD Phase 3 — Identity, trust, and intent layer.

Provides:
- TRUST_TIER_ORDER / trust_tier_sufficient()  — ordered trust tier comparison
- CapabilityCheckResult / check_capability()  — action authorization against AgentClass
- requires_human_gate()                       — AgentClass gate check for an action
- create_session() / is_session_active()
  expire_session() / terminate_session()
  advance_watermark()                         — session lifecycle helpers
- VALID_INTENT_TRANSITIONS                    — normative status machine
- IntentJournal                               — in-memory intent store with status enforcement

Normative rules enforced:
  Trust:
  - Agent may only open a session with mode 'execute' at trust_tier >= T2/bounded.
  - Agent may only open a session with mode 'supervised' at trust_tier >= T1/propose.
  - required_trust_tier on ActionContract is satisfied iff session.trust_tier >= required.

  Capability:
  - CapabilitySet.allowed_action_families is an allowlist; empty = no actions granted.
  - CapabilitySet.allowed_resource_types is an allowlist; empty = all resource types allowed.
  - CapabilitySet.restricted_resource_types is a denylist; denials override allows.
  - required_capabilities on ActionContract are matched against allowed_resource_types.
    A capability string "resource_type:permission" is matched on its resource_type prefix.

  Session:
  - Session.watermark advances monotonically (only forward, never backward).
  - Expired and terminated sessions are terminal — no further lifecycle transitions.
  - A session without an expiry is valid until explicitly terminated.

  Intent:
  - VALID_INTENT_TRANSITIONS defines the only legal status progressions.
  - Terminal statuses (committed, compensated, failed, expired) accept no outbound transitions.
  - IntentJournal is write-once for create; transition() replaces the stored intent.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Optional

from dawn.concord.types.contracts import ActionContract
from dawn.concord.types.entities import AgentClass, CapabilitySet, Intent, Session
from dawn.concord.types.enums import (
    IntentStatus,
    SessionMode,
    SessionStatus,
    TrustTier,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Trust tier ordering ────────────────────────────────────────────────────────

TRUST_TIER_ORDER: list[TrustTier] = [
    TrustTier.T0_OBSERVE,
    TrustTier.T1_PROPOSE,
    TrustTier.T2_BOUNDED,
    TrustTier.T3_PRIVILEGED,
    TrustTier.T4_GOVERNED_CRITICAL,
]

# Minimum trust tier required for each session mode.
_SESSION_MODE_MIN_TIER: dict[SessionMode, TrustTier] = {
    SessionMode.READ_ONLY:    TrustTier.T0_OBSERVE,
    SessionMode.PROPOSE_ONLY: TrustTier.T1_PROPOSE,
    SessionMode.SUPERVISED:   TrustTier.T1_PROPOSE,
    SessionMode.EXECUTE:      TrustTier.T2_BOUNDED,
}


def trust_tier_sufficient(session_tier: TrustTier, required_tier: TrustTier) -> bool:
    """Return True if *session_tier* is equal to or higher than *required_tier*.

    Higher index in TRUST_TIER_ORDER = higher trust.
    """
    try:
        return TRUST_TIER_ORDER.index(session_tier) >= TRUST_TIER_ORDER.index(required_tier)
    except ValueError:
        return False


# ── Capability check ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CapabilityCheckResult:
    """Result of a capability authorization check.

    Attributes:
        allowed:    True when the agent class is authorized to perform the action.
        error_code: NOT_AUTHORIZED_FOR_AGENT_CLASS when denied; None when allowed.
        reason:     Human-readable explanation of the denial reason.
    """

    allowed: bool
    error_code: Optional[str] = None
    reason: Optional[str] = None


def check_capability(
    agent_class: AgentClass,
    capability_sets: list[CapabilitySet],
    action_contract: ActionContract,
    resource_type: str,
) -> CapabilityCheckResult:
    """Check whether *agent_class* is authorized to perform *action_contract* on *resource_type*.

    Authorization requires ALL of the following:
    1. action_contract.action_family is in at least one CapabilitySet's
       allowed_action_families (allowlist; empty list grants nothing).
    2. resource_type is NOT in any CapabilitySet's restricted_resource_types (denylist wins).
    3. resource_type is in at least one CapabilitySet's allowed_resource_types, OR
       every CapabilitySet in *capability_sets* has an empty allowed_resource_types list
       (empty = no per-resource restriction for that set).
    4. If action_contract.required_trust_tier is set, agent_class.trust_tier must
       be >= required_trust_tier.

    Args:
        agent_class:       The AgentClass whose authorization is being checked.
        capability_sets:   All CapabilitySets associated with agent_class.
        action_contract:   The ActionContract the agent wants to execute.
        resource_type:     The resource_type the action targets.

    Returns:
        CapabilityCheckResult with allowed=True, or denied with an explanatory reason.
    """
    family_value = action_contract.action_family.value

    # Rule 1: action family must appear in at least one CapabilitySet's allowlist.
    family_allowed = any(
        family_value in cs.allowed_action_families
        for cs in capability_sets
    )
    if not family_allowed:
        return CapabilityCheckResult(
            allowed=False,
            error_code="NOT_AUTHORIZED_FOR_AGENT_CLASS",
            reason=(
                f"action_family '{family_value}' is not in any CapabilitySet "
                f"allowed_action_families for agent class '{agent_class.id}'."
            ),
        )

    # Rule 2: resource_type must not appear in any restricted_resource_types.
    for cs in capability_sets:
        if resource_type in cs.restricted_resource_types:
            return CapabilityCheckResult(
                allowed=False,
                error_code="NOT_AUTHORIZED_FOR_AGENT_CLASS",
                reason=(
                    f"resource_type '{resource_type}' is explicitly restricted "
                    f"in CapabilitySet '{cs.id}' for agent class '{agent_class.id}'."
                ),
            )

    # Rule 3: resource_type must be in at least one CapabilitySet's allowed_resource_types,
    # unless all sets have an empty allowed_resource_types (meaning no per-resource restriction).
    sets_with_resource_allowlist = [cs for cs in capability_sets if cs.allowed_resource_types]
    if sets_with_resource_allowlist:
        resource_allowed = any(
            resource_type in cs.allowed_resource_types
            for cs in sets_with_resource_allowlist
        )
        if not resource_allowed:
            return CapabilityCheckResult(
                allowed=False,
                error_code="NOT_AUTHORIZED_FOR_AGENT_CLASS",
                reason=(
                    f"resource_type '{resource_type}' is not in any CapabilitySet "
                    f"allowed_resource_types for agent class '{agent_class.id}'."
                ),
            )

    # Rule 4: trust tier sufficiency.
    if action_contract.required_trust_tier is not None:
        if not trust_tier_sufficient(agent_class.trust_tier, action_contract.required_trust_tier):
            return CapabilityCheckResult(
                allowed=False,
                error_code="NOT_AUTHORIZED_FOR_AGENT_CLASS",
                reason=(
                    f"Agent class '{agent_class.id}' has trust_tier "
                    f"'{agent_class.trust_tier.value}' but action "
                    f"'{action_contract.action_name}' requires "
                    f"'{action_contract.required_trust_tier.value}'."
                ),
            )

    return CapabilityCheckResult(allowed=True)


def requires_human_gate(agent_class: AgentClass, action_name: str) -> bool:
    """Return True if *agent_class* requires a human gate before *action_name* executes.

    Checks AgentClass.requires_human_gate_for. A non-empty list means those
    action names must pass through a human review step (→ REVIEW_REQUIRED).
    """
    return action_name in agent_class.requires_human_gate_for


# ── Session lifecycle ─────────────────────────────────────────────────────────


def create_session(
    *,
    id: str,
    agent_id: str,
    agent_class: AgentClass,
    mode: SessionMode,
    budget_profile_id: str,
    task_id: Optional[str] = None,
    expires_at: Optional[datetime] = None,
    environment_id: Optional[str] = None,
    fleet_id: Optional[str] = None,
) -> Session:
    """Create a new Session in PROPOSED/active status.

    Enforces:
    - Session mode requires at minimum the trust tier defined in _SESSION_MODE_MIN_TIER.

    Raises:
        ValueError: if agent_class.trust_tier is insufficient for the requested mode.
    """
    required_tier = _SESSION_MODE_MIN_TIER[mode]
    if not trust_tier_sufficient(agent_class.trust_tier, required_tier):
        raise ValueError(
            f"Session mode '{mode.value}' requires trust_tier >= "
            f"'{required_tier.value}', but agent class '{agent_class.id}' "
            f"has trust_tier '{agent_class.trust_tier.value}'."
        )

    return Session(
        id=id,
        agent_id=agent_id,
        agent_class_id=agent_class.id,
        trust_tier=agent_class.trust_tier,
        mode=mode,
        status=SessionStatus.ACTIVE,
        watermark=0,
        started_at=_utcnow(),
        budget_profile_id=budget_profile_id,
        task_id=task_id,
        expires_at=expires_at,
        environment_id=environment_id,
        fleet_id=fleet_id,
    )


def is_session_active(session: Session) -> bool:
    """Return True if session is active and not past its expiry."""
    if session.status != SessionStatus.ACTIVE:
        return False
    if session.expires_at is not None and _utcnow() > session.expires_at:
        return False
    return True


def expire_session(session: Session) -> Session:
    """Return a new Session with status=EXPIRED.

    Raises:
        ValueError: if session is already in a terminal state.
    """
    if session.status in (SessionStatus.EXPIRED, SessionStatus.TERMINATED):
        raise ValueError(
            f"Session '{session.id}' is already terminal (status={session.status.value})."
        )
    return replace(session, status=SessionStatus.EXPIRED)


def terminate_session(session: Session) -> Session:
    """Return a new Session with status=TERMINATED.

    Raises:
        ValueError: if session is already in a terminal state.
    """
    if session.status in (SessionStatus.EXPIRED, SessionStatus.TERMINATED):
        raise ValueError(
            f"Session '{session.id}' is already terminal (status={session.status.value})."
        )
    return replace(session, status=SessionStatus.TERMINATED)


def advance_watermark(session: Session, new_version: int) -> Session:
    """Return a new Session whose watermark is max(session.watermark, new_version).

    Watermarks are monotonically increasing — they never go backward.
    """
    if new_version > session.watermark:
        return replace(session, watermark=new_version)
    return session


# ── Intent status machine ─────────────────────────────────────────────────────

#: Terminal statuses accept no further transitions.
INTENT_TERMINAL_STATUSES: frozenset[IntentStatus] = frozenset({
    IntentStatus.COMMITTED,
    IntentStatus.COMPENSATED,
    IntentStatus.FAILED,
    IntentStatus.EXPIRED,
})

#: Valid outbound transitions from each non-terminal status.
VALID_INTENT_TRANSITIONS: dict[IntentStatus, frozenset[IntentStatus]] = {
    IntentStatus.PROPOSED: frozenset({
        IntentStatus.ADMITTED,
        IntentStatus.FAILED,
        IntentStatus.EXPIRED,
    }),
    IntentStatus.ADMITTED: frozenset({
        IntentStatus.QUEUED,
        IntentStatus.EXECUTING,
        IntentStatus.BLOCKED,
        IntentStatus.FAILED,
        IntentStatus.EXPIRED,
    }),
    IntentStatus.QUEUED: frozenset({
        IntentStatus.ADMITTED,
        IntentStatus.BLOCKED,
        IntentStatus.FAILED,
        IntentStatus.EXPIRED,
    }),
    IntentStatus.BLOCKED: frozenset({
        IntentStatus.ADMITTED,
        IntentStatus.QUEUED,
        IntentStatus.FAILED,
        IntentStatus.EXPIRED,
    }),
    IntentStatus.EXECUTING: frozenset({
        IntentStatus.COMMITTED,
        IntentStatus.COMPENSATED,
        IntentStatus.FAILED,
        IntentStatus.EXPIRED,
    }),
    # Terminal statuses have no outbound transitions.
    IntentStatus.COMMITTED:   frozenset(),
    IntentStatus.COMPENSATED: frozenset(),
    IntentStatus.FAILED:      frozenset(),
    IntentStatus.EXPIRED:     frozenset(),
}


# ── IntentJournal ─────────────────────────────────────────────────────────────


class IntentJournal:
    """In-memory journal of Intent records with status-machine enforcement.

    Indexed by intent_id, with secondary indices by session_id and resource_id.
    All stored intents are deep-copied on read to prevent caller mutation.
    """

    def __init__(self) -> None:
        self._store: dict[str, Intent] = {}

    def create(self, intent: Intent) -> Intent:
        """Add a new Intent to the journal.

        Raises:
            ValueError: if an intent with the same id already exists.
            ValueError: if the initial status is not PROPOSED.
        """
        if intent.id in self._store:
            raise ValueError(
                f"Intent '{intent.id}' already exists in the journal."
            )
        if intent.status != IntentStatus.PROPOSED:
            raise ValueError(
                f"New intents must start with status PROPOSED, "
                f"got '{intent.status.value}'."
            )
        stored = copy.deepcopy(intent)
        self._store[intent.id] = stored
        return copy.deepcopy(stored)

    def transition(self, intent_id: str, new_status: IntentStatus) -> Intent:
        """Advance an intent's status, returning the updated Intent.

        Enforces VALID_INTENT_TRANSITIONS.

        Raises:
            KeyError:   if intent_id is not in the journal.
            ValueError: if the transition is not permitted by the status machine.
        """
        if intent_id not in self._store:
            raise KeyError(f"Intent '{intent_id}' not found in journal.")

        current = self._store[intent_id]
        allowed = VALID_INTENT_TRANSITIONS.get(current.status, frozenset())

        if new_status not in allowed:
            raise ValueError(
                f"Intent '{intent_id}': transition from '{current.status.value}' "
                f"to '{new_status.value}' is not permitted. "
                f"Allowed: {sorted(s.value for s in allowed) or '(terminal)'}"
            )

        now = _utcnow()
        kwargs: dict = {}
        if new_status == IntentStatus.ADMITTED and current.admitted_at is None:
            kwargs["admitted_at"] = now
        if new_status == IntentStatus.EXECUTING and current.executed_at is None:
            kwargs["executed_at"] = now

        updated = replace(current, status=new_status, **kwargs)
        self._store[intent_id] = updated
        return copy.deepcopy(updated)

    def get(self, intent_id: str) -> Intent:
        """Return a deep copy of the intent.

        Raises:
            KeyError: if intent_id is not in the journal.
        """
        if intent_id not in self._store:
            raise KeyError(f"Intent '{intent_id}' not found in journal.")
        return copy.deepcopy(self._store[intent_id])

    def list_by_session(self, session_id: str) -> list[Intent]:
        """Return all intents for *session_id*, sorted by created_at ascending."""
        return sorted(
            (copy.deepcopy(i) for i in self._store.values() if i.session_id == session_id),
            key=lambda i: i.created_at,
        )

    def list_by_resource(self, resource_id: str) -> list[Intent]:
        """Return all intents targeting *resource_id*, sorted by created_at ascending."""
        return sorted(
            (copy.deepcopy(i) for i in self._store.values() if i.resource_id == resource_id),
            key=lambda i: i.created_at,
        )

    def list_active(self, session_id: str) -> list[Intent]:
        """Return non-terminal intents for *session_id*, sorted by created_at ascending."""
        return [
            i for i in self.list_by_session(session_id)
            if i.status not in INTENT_TERMINAL_STATUSES
        ]

    def __len__(self) -> int:
        return len(self._store)
