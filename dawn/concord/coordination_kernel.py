"""CONCORD Phase 5 — Coordination layer.

Provides:
- LeaseAcquireResult / TokenAcquireResult / AdmissionResult  — frozen result types
- LeaseStore (ABC) / InMemoryLeaseStore                       — lease persistence
- TokenStore (ABC) / InMemoryTokenStore                       — token persistence
- is_lease_active() / grant_lease() / release_lease()
  revoke_lease() / renew_lease()                              — lease lifecycle
- is_token_available() / acquire_token() / release_token()    — token lifecycle
- admit_intent()                                              — full admission pipeline
- IntentQueue                                                 — per-resource priority queue

Normative rules enforced:
  Leases (exclusive coordination locks):
  - Any active lease held by a DIFFERENT session on the same resource → LEASE_HELD.
  - Same session may hold multiple lease types on the same resource without conflict.
  - Lease is only active when status == ACTIVE and expires_at is in the future.
  - Only the holding session may release its own lease (release validates session_id).
  - Revoke is unrestricted (admin operation).
  - Renewal extends expires_at; renewal_count increments.
  - grant_lease checks for conflicting active leases before issuing.

  Tokens (finite coordination tokens):
  - Token is available when status == ACTIVE and available_count > 0.
  - Acquiring a token decrements available_count and adds session_id to holders.
  - A session may not hold the same token twice (duplicate acquire is idempotent check).
  - Releasing a token increments available_count and removes session_id from holders.
  - available_count may not exceed capacity (invariant maintained by release).
  - When available_count reaches 0 → status transitions to EXHAUSTED.
  - When all holders release → status returns to ACTIVE (if not expired/suspended).

  Admission pipeline (admit_intent):
  - Checks are ordered: capability → gateway budget → intent budget → duplicate → lease conflict.
  - First denial encountered is returned immediately (fail-fast per check type).
  - DUPLICATE_INTENT is informational — the existing intent's idempotency key matched.
  - All checks are pure (no I/O) — callers pass in fetched leases and intents.

  IntentQueue:
  - Per-resource FIFO within equal priority; higher numeric priority dequeued first.
  - Enqueue respects max_queue_depth (from BudgetProfile); raises QueueFullError if exceeded.
  - Queue position is 1-indexed (position 1 = next to be dequeued).
"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Optional

from dawn.concord.budget_kernel import (
    check_gateway_budget,
    check_intent_budget,
)
from dawn.concord.identity_kernel import check_capability
from dawn.concord.types.entities import (
    AgentClass,
    BudgetLedger,
    BudgetProfile,
    CapabilitySet,
    Intent,
    Lease,
    Token,
)
from dawn.concord.types.contracts import ActionContract
from dawn.concord.types.enums import (
    IntentStatus,
    LeaseStatus,
    TokenStatus,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LeaseAcquireResult:
    """Result of a grant_lease or renew_lease operation.

    Attributes:
        success:    True when the lease was granted or renewed.
        lease:      The Lease on success; the conflicting Lease on LEASE_HELD; None otherwise.
        error_code: LEASE_HELD when blocked; None on success.
        reason:     Human-readable explanation.
    """

    success: bool
    lease: Optional[Lease] = None
    error_code: Optional[str] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class TokenAcquireResult:
    """Result of an acquire_token operation.

    Attributes:
        success:    True when the token was acquired.
        token:      The updated Token on success; None on failure.
        error_code: QUORUM_INCOMPLETE or CAPACITY_EXHAUSTED when unavailable; None on success.
        reason:     Human-readable explanation.
    """

    success: bool
    token: Optional[Token] = None
    error_code: Optional[str] = None
    reason: Optional[str] = None


@dataclass(frozen=True)
class AdmissionResult:
    """Result of the full intent admission pipeline.

    Attributes:
        admitted:           True when the intent may proceed to execution.
        error_code:         The first conflict or error code encountered, or None.
        reason:             Human-readable explanation of the denial.
        retry_delay_hint_ms: Advisory retry delay from the relevant error registry entry.
        requires_queue:     True when the caller should enqueue the intent and wait.
        queue_position:     Set when requires_queue is True and the intent was enqueued.
    """

    admitted: bool
    error_code: Optional[str] = None
    reason: Optional[str] = None
    retry_delay_hint_ms: Optional[int] = None
    requires_queue: bool = False
    queue_position: Optional[int] = None


# ── Lease store ───────────────────────────────────────────────────────────────


class LeaseStore(ABC):
    """Abstract persistence layer for Lease objects."""

    @abstractmethod
    def fetch(self, lease_id: str) -> Lease:
        """Return the Lease with *lease_id*.

        Raises:
            KeyError: if not found.
        """

    @abstractmethod
    def fetch_active_for_resource(self, resource_id: str) -> list[Lease]:
        """Return all leases with status=ACTIVE for *resource_id*."""

    @abstractmethod
    def save(self, lease: Lease) -> Lease:
        """Persist (create or update) *lease* and return the stored copy."""

    @abstractmethod
    def exists(self, lease_id: str) -> bool:
        """Return True if *lease_id* exists in the store."""


class InMemoryLeaseStore(LeaseStore):
    """Dict-backed LeaseStore for testing and local development."""

    def __init__(self) -> None:
        self._store: dict[str, Lease] = {}

    def fetch(self, lease_id: str) -> Lease:
        if lease_id not in self._store:
            raise KeyError(f"Lease '{lease_id}' not found.")
        return copy.deepcopy(self._store[lease_id])

    def fetch_active_for_resource(self, resource_id: str) -> list[Lease]:
        return [
            copy.deepcopy(l)
            for l in self._store.values()
            if l.resource_id == resource_id and l.status == LeaseStatus.ACTIVE
        ]

    def save(self, lease: Lease) -> Lease:
        stored = copy.deepcopy(lease)
        self._store[lease.id] = stored
        return copy.deepcopy(stored)

    def exists(self, lease_id: str) -> bool:
        return lease_id in self._store

    def __len__(self) -> int:
        return len(self._store)


# ── Lease operations ──────────────────────────────────────────────────────────


def is_lease_active(lease: Lease) -> bool:
    """Return True if *lease* is in ACTIVE status and not past its expiry."""
    return lease.status == LeaseStatus.ACTIVE and _utcnow() < lease.expires_at


def grant_lease(
    store: LeaseStore,
    *,
    lease_id: str,
    resource_id: str,
    session_id: str,
    lease_type: "LeaseType",
    duration_ms: int,
    purpose: Optional[str] = None,
) -> LeaseAcquireResult:
    """Attempt to grant a new lease to *session_id* on *resource_id*.

    Checks all currently active leases on the resource. If another session holds
    an active lease, returns LEASE_HELD with the conflicting Lease.

    Args:
        store:       LeaseStore to check for conflicts and persist the new lease.
        lease_id:    Caller-supplied ID for the new lease.
        resource_id: Target resource.
        session_id:  Session requesting the lease.
        lease_type:  Type of lease being requested.
        duration_ms: Lease duration in milliseconds.
        purpose:     Optional human-readable description.

    Returns:
        LeaseAcquireResult with success=True and the granted Lease, or
        LeaseAcquireResult with success=False and error_code=LEASE_HELD.
    """
    active = store.fetch_active_for_resource(resource_id)
    for existing in active:
        if existing.session_id != session_id:
            return LeaseAcquireResult(
                success=False,
                lease=existing,
                error_code="LEASE_HELD",
                reason=(
                    f"Resource '{resource_id}' already has an active {existing.lease_type.value} "
                    f"lease held by session '{existing.session_id}' "
                    f"(expires {existing.expires_at.isoformat()})."
                ),
            )

    now = _utcnow()
    lease = Lease(
        id=lease_id,
        resource_id=resource_id,
        session_id=session_id,
        lease_type=lease_type,
        expires_at=now + timedelta(milliseconds=duration_ms),
        granted_at=now,
        status=LeaseStatus.ACTIVE,
        renewal_count=0,
        purpose=purpose,
    )
    stored = store.save(lease)
    return LeaseAcquireResult(success=True, lease=stored)


def release_lease(
    store: LeaseStore,
    lease_id: str,
    requesting_session_id: str,
) -> Lease:
    """Release a lease held by *requesting_session_id*.

    Sets status to RELEASED.

    Raises:
        KeyError:    if lease_id is not found.
        ValueError:  if the requesting session does not own the lease.
        ValueError:  if the lease is already in a terminal state.
    """
    lease = store.fetch(lease_id)

    if lease.session_id != requesting_session_id:
        raise ValueError(
            f"Session '{requesting_session_id}' cannot release lease '{lease_id}' "
            f"owned by session '{lease.session_id}'."
        )
    if lease.status != LeaseStatus.ACTIVE:
        raise ValueError(
            f"Lease '{lease_id}' is not active (status={lease.status.value}); "
            "cannot release."
        )

    updated = replace(lease, status=LeaseStatus.RELEASED)
    return store.save(updated)


def revoke_lease(store: LeaseStore, lease_id: str) -> Lease:
    """Revoke a lease (admin operation, unrestricted by session ownership).

    Sets status to REVOKED.

    Raises:
        KeyError:   if lease_id is not found.
        ValueError: if the lease is already in a terminal state.
    """
    lease = store.fetch(lease_id)
    if lease.status != LeaseStatus.ACTIVE:
        raise ValueError(
            f"Lease '{lease_id}' is not active (status={lease.status.value}); "
            "cannot revoke."
        )
    updated = replace(lease, status=LeaseStatus.REVOKED)
    return store.save(updated)


def renew_lease(
    store: LeaseStore,
    lease_id: str,
    requesting_session_id: str,
    extension_ms: int,
) -> LeaseAcquireResult:
    """Extend an active lease's expiry by *extension_ms* milliseconds.

    Raises:
        KeyError:   if lease_id is not found.
        ValueError: if the requesting session does not own the lease.
    """
    lease = store.fetch(lease_id)

    if lease.session_id != requesting_session_id:
        raise ValueError(
            f"Session '{requesting_session_id}' cannot renew lease '{lease_id}' "
            f"owned by session '{lease.session_id}'."
        )
    if lease.status != LeaseStatus.ACTIVE:
        return LeaseAcquireResult(
            success=False,
            error_code="LEASE_HELD",
            reason=(
                f"Lease '{lease_id}' is not active (status={lease.status.value}); "
                "cannot renew."
            ),
        )

    updated = replace(
        lease,
        expires_at=lease.expires_at + timedelta(milliseconds=extension_ms),
        renewal_count=lease.renewal_count + 1,
    )
    stored = store.save(updated)
    return LeaseAcquireResult(success=True, lease=stored)


# ── Token store ───────────────────────────────────────────────────────────────


class TokenStore(ABC):
    """Abstract persistence layer for Token objects."""

    @abstractmethod
    def fetch(self, token_id: str) -> Token:
        """Return the Token with *token_id*.

        Raises:
            KeyError: if not found.
        """

    @abstractmethod
    def save(self, token: Token) -> Token:
        """Persist (create or update) *token* and return the stored copy."""

    @abstractmethod
    def exists(self, token_id: str) -> bool:
        """Return True if *token_id* exists in the store."""


class InMemoryTokenStore(TokenStore):
    """Dict-backed TokenStore for testing and local development."""

    def __init__(self) -> None:
        self._store: dict[str, Token] = {}

    def fetch(self, token_id: str) -> Token:
        if token_id not in self._store:
            raise KeyError(f"Token '{token_id}' not found.")
        return copy.deepcopy(self._store[token_id])

    def save(self, token: Token) -> Token:
        stored = copy.deepcopy(token)
        self._store[token.id] = stored
        return copy.deepcopy(stored)

    def exists(self, token_id: str) -> bool:
        return token_id in self._store

    def __len__(self) -> int:
        return len(self._store)


# ── Token operations ──────────────────────────────────────────────────────────


def is_token_available(token: Token) -> bool:
    """Return True if *token* can be acquired (ACTIVE and available_count > 0)."""
    return token.status == TokenStatus.ACTIVE and token.available_count > 0


def acquire_token(
    store: TokenStore,
    token_id: str,
    session_id: str,
) -> TokenAcquireResult:
    """Acquire one slot of *token_id* for *session_id*.

    Idempotent: if session_id already holds this token, returns success without
    double-decrementing available_count.

    Returns:
        TokenAcquireResult with success=True and the updated Token, or
        success=False with error_code QUORUM_INCOMPLETE (token unavailable or
        exhausted) or CAPACITY_EXHAUSTED (available_count == 0).

    Raises:
        KeyError: if token_id is not found.
    """
    token = store.fetch(token_id)

    # Idempotency: already a holder.
    if session_id in token.holders:
        return TokenAcquireResult(success=True, token=token)

    if token.status == TokenStatus.EXHAUSTED:
        return TokenAcquireResult(
            success=False,
            error_code="CAPACITY_EXHAUSTED",
            reason=(
                f"Token '{token_id}' is exhausted (no available slots)."
            ),
        )

    if token.status != TokenStatus.ACTIVE:
        return TokenAcquireResult(
            success=False,
            error_code="QUORUM_INCOMPLETE",
            reason=(
                f"Token '{token_id}' is not active (status={token.status.value}); "
                "cannot acquire."
            ),
        )

    if token.available_count <= 0:
        return TokenAcquireResult(
            success=False,
            error_code="CAPACITY_EXHAUSTED",
            reason=(
                f"Token '{token_id}' has no available slots "
                f"(capacity={token.capacity}, available=0)."
            ),
        )

    new_available = token.available_count - 1
    new_status = TokenStatus.EXHAUSTED if new_available == 0 else TokenStatus.ACTIVE
    updated = replace(
        token,
        available_count=new_available,
        holders=[*token.holders, session_id],
        status=new_status,
    )
    stored = store.save(updated)
    return TokenAcquireResult(success=True, token=stored)


def release_token(
    store: TokenStore,
    token_id: str,
    session_id: str,
) -> Token:
    """Release *session_id*'s slot in *token_id*.

    Increments available_count and removes session_id from holders. If the token
    was EXHAUSTED, transitions it back to ACTIVE.

    Returns the updated Token.

    Raises:
        KeyError:   if token_id is not found.
        ValueError: if session_id is not a current holder.
        ValueError: if available_count would exceed capacity.
    """
    token = store.fetch(token_id)

    if session_id not in token.holders:
        raise ValueError(
            f"Session '{session_id}' does not hold token '{token_id}'."
        )

    new_available = token.available_count + 1
    if new_available > token.capacity:
        raise ValueError(
            f"Releasing token '{token_id}' would exceed capacity "
            f"({new_available} > {token.capacity})."
        )

    new_holders = [h for h in token.holders if h != session_id]
    new_status = (
        TokenStatus.ACTIVE
        if token.status == TokenStatus.EXHAUSTED
        else token.status
    )
    updated = replace(
        token,
        available_count=new_available,
        holders=new_holders,
        status=new_status,
    )
    return store.save(updated)


# ── Admission pipeline ────────────────────────────────────────────────────────


def admit_intent(
    intent: Intent,
    *,
    agent_class: AgentClass,
    capability_sets: list[CapabilitySet],
    action_contract: ActionContract,
    profile: BudgetProfile,
    ledger: BudgetLedger,
    active_leases: list[Lease],
    existing_intents: list[Intent],
) -> AdmissionResult:
    """Run the full intent admission pipeline and return an AdmissionResult.

    Pipeline order (first denial wins):
    1. Capability check — is the agent class authorized for this action/resource?
    2. Gateway budget check — circuit open or cooldown active?
    3. Intent budget check — all quota dimensions.
    4. Duplicate intent check — same idempotency key already active?
    5. Lease conflict check — another session holds an active lease?

    Args:
        intent:           The Intent to be admitted.
        agent_class:      AgentClass of the requesting session.
        capability_sets:  All CapabilitySets for agent_class.
        action_contract:  The ActionContract for intent.action_name.
        profile:          BudgetProfile for the agent class.
        ledger:           Current BudgetLedger snapshot for the session.
        active_leases:    Active leases currently held on intent.resource_id.
        existing_intents: Non-terminal intents for the same session (for duplicate detection).

    Returns:
        AdmissionResult with admitted=True, or denial with error_code and reason.
    """
    # 1. Capability
    cap = check_capability(agent_class, capability_sets, action_contract, intent.resource_type)
    if not cap.allowed:
        return AdmissionResult(
            admitted=False,
            error_code=cap.error_code,
            reason=cap.reason,
        )

    # 2. Gateway budget
    gw = check_gateway_budget(profile, ledger)
    if not gw.allowed:
        return AdmissionResult(
            admitted=False,
            error_code=gw.error_code,
            reason=gw.reason,
            retry_delay_hint_ms=gw.retry_delay_hint_ms,
        )

    # 3. Intent budget
    ib = check_intent_budget(
        profile,
        ledger,
        cost_units=action_contract.budget_cost_units,
        action_family=action_contract.action_family,
        risk_level=action_contract.risk_level,
    )
    if not ib.allowed:
        return AdmissionResult(
            admitted=False,
            error_code=ib.error_code,
            reason=ib.reason,
            retry_delay_hint_ms=ib.retry_delay_hint_ms,
        )

    # 4. Duplicate intent — same idempotency key already non-terminal in this session
    for existing in existing_intents:
        if (
            existing.idempotency_key == intent.idempotency_key
            and existing.id != intent.id
            and existing.status not in (
                IntentStatus.COMMITTED,
                IntentStatus.COMPENSATED,
                IntentStatus.FAILED,
                IntentStatus.EXPIRED,
            )
        ):
            return AdmissionResult(
                admitted=False,
                error_code="DUPLICATE_INTENT",
                reason=(
                    f"Intent '{existing.id}' with idempotency_key "
                    f"'{intent.idempotency_key}' is already active "
                    f"(status={existing.status.value})."
                ),
                retry_delay_hint_ms=None,
            )

    # 5. Lease conflict — another session holds an active lease on the resource
    for lease in active_leases:
        if is_lease_active(lease) and lease.session_id != intent.session_id:
            return AdmissionResult(
                admitted=False,
                error_code="LEASE_HELD",
                reason=(
                    f"Resource '{intent.resource_id}' has an active "
                    f"{lease.lease_type.value} lease held by session "
                    f"'{lease.session_id}' (expires {lease.expires_at.isoformat()})."
                ),
                retry_delay_hint_ms=1500,
                requires_queue=True,
            )

    return AdmissionResult(admitted=True)


# ── Intent queue ──────────────────────────────────────────────────────────────


class QueueFullError(Exception):
    """Raised when enqueue is attempted on a full resource queue."""


@dataclass(order=True)
class _QueueEntry:
    """Internal queue entry sorted by (neg_priority, seq) for min-heap semantics."""

    neg_priority: int          # negated so higher priority sorts first
    seq: int                   # insertion order tiebreaker
    intent_id: str = field(compare=False)
    resource_id: str = field(compare=False)


class IntentQueue:
    """Per-resource priority queue for intents awaiting coordination clearance.

    Higher numeric priority = dequeued first. Within equal priority, FIFO order.

    Queue position is 1-indexed (position 1 = next to be dequeued for that resource).
    """

    def __init__(self) -> None:
        # resource_id → list of _QueueEntry, kept sorted
        self._queues: dict[str, list[_QueueEntry]] = {}
        self._seq: int = 0
        # intent_id → resource_id for O(1) position lookup
        self._intent_to_resource: dict[str, str] = {}

    def enqueue(
        self,
        intent_id: str,
        resource_id: str,
        priority: int = 0,
        max_depth: Optional[int] = None,
    ) -> int:
        """Add *intent_id* to the queue for *resource_id*.

        Args:
            intent_id:  Intent to enqueue.
            resource_id: Resource the intent is waiting on.
            priority:    Higher value = dequeued sooner (default 0).
            max_depth:   Maximum allowed queue depth for this resource; None = unlimited.

        Returns:
            1-indexed queue position after insertion.

        Raises:
            ValueError:     if intent_id is already in the queue.
            QueueFullError: if max_depth would be exceeded.
        """
        if intent_id in self._intent_to_resource:
            raise ValueError(f"Intent '{intent_id}' is already in the queue.")

        q = self._queues.setdefault(resource_id, [])

        if max_depth is not None and len(q) >= max_depth:
            raise QueueFullError(
                f"Queue for resource '{resource_id}' is full "
                f"(depth={len(q)}, max={max_depth})."
            )

        entry = _QueueEntry(
            neg_priority=-priority,
            seq=self._seq,
            intent_id=intent_id,
            resource_id=resource_id,
        )
        self._seq += 1

        # Insert in sorted position (maintains sorted list)
        import bisect
        bisect.insort(q, entry)

        self._intent_to_resource[intent_id] = resource_id
        return self.position(intent_id)  # type: ignore[return-value]

    def dequeue(self, resource_id: str) -> Optional[str]:
        """Remove and return the highest-priority intent_id for *resource_id*.

        Returns None if the queue for *resource_id* is empty.
        """
        q = self._queues.get(resource_id, [])
        if not q:
            return None
        entry = q.pop(0)
        self._intent_to_resource.pop(entry.intent_id, None)
        return entry.intent_id

    def position(self, intent_id: str) -> Optional[int]:
        """Return the 1-indexed queue position of *intent_id*, or None if not queued."""
        resource_id = self._intent_to_resource.get(intent_id)
        if resource_id is None:
            return None
        q = self._queues.get(resource_id, [])
        for i, entry in enumerate(q):
            if entry.intent_id == intent_id:
                return i + 1
        return None

    def remove(self, intent_id: str) -> bool:
        """Remove *intent_id* from the queue without dequeuing the head.

        Returns True if the intent was found and removed, False if not in queue.
        """
        resource_id = self._intent_to_resource.pop(intent_id, None)
        if resource_id is None:
            return False
        q = self._queues.get(resource_id, [])
        for i, entry in enumerate(q):
            if entry.intent_id == intent_id:
                q.pop(i)
                return True
        return False

    def depth(self, resource_id: str) -> int:
        """Return the number of intents queued for *resource_id*."""
        return len(self._queues.get(resource_id, []))

    def peek(self, resource_id: str) -> Optional[str]:
        """Return the next intent_id to be dequeued without removing it, or None."""
        q = self._queues.get(resource_id, [])
        return q[0].intent_id if q else None
