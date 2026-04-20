"""CONCORD Phase 2 — Resource + version layer.

Provides:
- CASResult / ReadResult / IdempotencyRecord  — plain result types
- ResourceRepository (ABC)     — abstract storage interface
- IdempotencyStore (ABC)       — abstract idempotency-key store
- read_with_profile()          — consistency-profile-aware resource read
- InMemoryResourceRepository   — dict-backed implementation for tests / dev
- InMemoryIdempotencyStore     — dict-backed implementation for tests / dev

Normative rules enforced here:
  CAS:
  - compare_and_swap MUST atomically check version before writing.
  - On version mismatch, returns CASResult(success=False, error_code=STALE_VERSION).
  - On success, version increments by exactly 1 and updated_at is refreshed.

  Consistency profiles (read_with_profile):
  - STRONG:            authoritative fetch; FreshnessStatus.FRESH guaranteed.
  - SESSION_MONOTONIC: authoritative fetch; STALE_VERSION if version < session_watermark.
  - READ_YOUR_WRITES:  authoritative fetch; READ_FRESHNESS_UNAVAILABLE if version < min_version.
  - EVENTUAL:          authoritative fetch (in-memory); FreshnessStatus.WARNING — callers
                       must treat result as advisory for mutation decisions.
  - ASYNC_PROJECTION:  authoritative fetch (in-memory); projection_lag_ms attached;
                       FreshnessStatus.WARNING; callers MUST set authoritative_recheck_required.

  Idempotency:
  - check() returns an existing IdempotencyRecord if the key+scope+scope_id was already seen.
  - record() is a write-once operation; duplicate keys within scope raise ValueError.
"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from dawn.concord.types.entities import Resource
from dawn.concord.types.enums import ConsistencyProfile, FreshnessStatus, IdempotencyScope


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CASResult:
    """Result of a compare-and-swap operation.

    Attributes:
        success:    True when the write was applied.
        resource:   The resource after the operation.
                    On success: the updated resource (version incremented).
                    On conflict: the current resource at the conflicting version.
        error_code: STALE_VERSION on version mismatch; None on success.
    """

    success: bool
    resource: Resource
    error_code: Optional[str] = None


@dataclass(frozen=True)
class ReadResult:
    """Result of a consistency-profile-aware resource read.

    Attributes:
        resource:         The resource as returned by the read.
        freshness_status: FRESH for authoritative reads; WARNING for eventual/projection.
        error_code:       STALE_VERSION (SESSION_MONOTONIC) or
                          READ_FRESHNESS_UNAVAILABLE (READ_YOUR_WRITES) on staleness;
                          None otherwise.
        projection_lag_ms: For ASYNC_PROJECTION reads — caller-supplied lag hint.
    """

    resource: Resource
    freshness_status: FreshnessStatus
    error_code: Optional[str] = None
    projection_lag_ms: Optional[int] = None


@dataclass(frozen=True)
class IdempotencyRecord:
    """A recorded idempotency key entry.

    Attributes:
        key:        The idempotency key string.
        scope:      SESSION, RESOURCE, or GLOBAL.
        scope_id:   The session_id, resource_id, or "" for GLOBAL.
        result_ref: Opaque reference to the original operation's Receipt or output.
        recorded_at: When the record was first written.
    """

    key: str
    scope: IdempotencyScope
    scope_id: str
    result_ref: str
    recorded_at: datetime


# ── Abstract interfaces ───────────────────────────────────────────────────────


class ResourceRepository(ABC):
    """Abstract repository for Resource persistence.

    All implementations MUST satisfy the CAS atomicity guarantee:
    compare_and_swap reads and writes in a single atomic operation with
    respect to the version field.
    """

    @abstractmethod
    def fetch(self, resource_id: str) -> Resource:
        """Return the current authoritative resource.

        Raises:
            KeyError: if resource_id does not exist.
        """

    @abstractmethod
    def compare_and_swap(
        self,
        resource_id: str,
        expected_version: int,
        business_state: dict,
        coordination_state: Optional[dict] = None,
    ) -> CASResult:
        """Atomically update resource if current version == expected_version.

        Args:
            resource_id:        Target resource.
            expected_version:   Version the caller observed before the mutation.
            business_state:     Full replacement for business_state (not a patch).
            coordination_state: Full replacement for coordination_state, or None
                                to leave coordination_state unchanged.

        Returns:
            CASResult with success=True and the updated resource, or
            CASResult with success=False and error_code=STALE_VERSION.

        Raises:
            KeyError: if resource_id does not exist.
        """

    @abstractmethod
    def create(self, resource: Resource) -> Resource:
        """Persist a new resource.

        Raises:
            ValueError: if a resource with the same id already exists.
        """

    @abstractmethod
    def exists(self, resource_id: str) -> bool:
        """Return True if resource_id is present in the store."""


class IdempotencyStore(ABC):
    """Abstract store for idempotency key records."""

    @abstractmethod
    def check(
        self, key: str, scope: IdempotencyScope, scope_id: str
    ) -> Optional[IdempotencyRecord]:
        """Return existing record for (key, scope, scope_id), or None."""

    @abstractmethod
    def record(
        self,
        key: str,
        scope: IdempotencyScope,
        scope_id: str,
        result_ref: str,
    ) -> IdempotencyRecord:
        """Write a new idempotency record.

        Raises:
            ValueError: if the (key, scope, scope_id) combination already exists.
        """


# ── Consistency-profile-aware read ────────────────────────────────────────────


def read_with_profile(
    repo: ResourceRepository,
    resource_id: str,
    profile: ConsistencyProfile,
    *,
    session_watermark: Optional[int] = None,
    min_version: Optional[int] = None,
    projection_lag_ms: Optional[int] = None,
) -> ReadResult:
    """Read a resource applying the semantics of *profile*.

    Profile semantics:

    STRONG
        Authoritative fetch. Returns FreshnessStatus.FRESH.
        session_watermark and min_version are ignored.

    SESSION_MONOTONIC
        Authoritative fetch. If version < session_watermark, returns
        error_code=STALE_VERSION and FreshnessStatus.STALE. Callers must
        refresh their watermark and retry.

    READ_YOUR_WRITES
        Authoritative fetch. If version < min_version (last written version),
        returns error_code=READ_FRESHNESS_UNAVAILABLE and FreshnessStatus.WARNING.

    EVENTUAL
        Authoritative fetch (in-memory has no replica lag). FreshnessStatus.WARNING
        is returned to remind callers this read is advisory — the resource may
        have advanced before the caller acts on it.

    ASYNC_PROJECTION
        Authoritative fetch (in-memory). FreshnessStatus.WARNING. projection_lag_ms
        is attached to the ReadResult so callers can populate OperationContext
        accordingly. Callers MUST set requires_authoritative_recheck=True before
        any mutation based on this read.

    Raises:
        KeyError: propagated from repo.fetch() if resource_id is missing.
        ValueError: if SESSION_MONOTONIC is used without session_watermark, or
                    READ_YOUR_WRITES is used without min_version.
    """
    resource = repo.fetch(resource_id)

    if profile == ConsistencyProfile.STRONG:
        return ReadResult(resource=resource, freshness_status=FreshnessStatus.FRESH)

    if profile == ConsistencyProfile.SESSION_MONOTONIC:
        if session_watermark is None:
            raise ValueError(
                "SESSION_MONOTONIC read requires session_watermark to be provided."
            )
        if resource.version < session_watermark:
            return ReadResult(
                resource=resource,
                freshness_status=FreshnessStatus.STALE,
                error_code="STALE_VERSION",
            )
        return ReadResult(resource=resource, freshness_status=FreshnessStatus.FRESH)

    if profile == ConsistencyProfile.READ_YOUR_WRITES:
        if min_version is None:
            raise ValueError(
                "READ_YOUR_WRITES read requires min_version to be provided."
            )
        if resource.version < min_version:
            return ReadResult(
                resource=resource,
                freshness_status=FreshnessStatus.WARNING,
                error_code="READ_FRESHNESS_UNAVAILABLE",
            )
        return ReadResult(resource=resource, freshness_status=FreshnessStatus.FRESH)

    if profile == ConsistencyProfile.EVENTUAL:
        return ReadResult(resource=resource, freshness_status=FreshnessStatus.WARNING)

    if profile == ConsistencyProfile.ASYNC_PROJECTION:
        return ReadResult(
            resource=resource,
            freshness_status=FreshnessStatus.WARNING,
            projection_lag_ms=projection_lag_ms,
        )

    # Exhaustive — all five profiles handled above.
    raise ValueError(f"Unhandled consistency profile: {profile!r}")  # pragma: no cover


# ── In-memory implementations ─────────────────────────────────────────────────


class InMemoryResourceRepository(ResourceRepository):
    """Dict-backed ResourceRepository for testing and local development.

    Deep-copies resources on write so stored state is immutable to callers.
    compare_and_swap is atomic within a single Python thread.
    """

    def __init__(self) -> None:
        self._store: dict[str, Resource] = {}

    def fetch(self, resource_id: str) -> Resource:
        if resource_id not in self._store:
            raise KeyError(f"Resource '{resource_id}' not found.")
        return copy.deepcopy(self._store[resource_id])

    def compare_and_swap(
        self,
        resource_id: str,
        expected_version: int,
        business_state: dict,
        coordination_state: Optional[dict] = None,
    ) -> CASResult:
        if resource_id not in self._store:
            raise KeyError(f"Resource '{resource_id}' not found.")

        current = self._store[resource_id]

        if current.version != expected_version:
            return CASResult(
                success=False,
                resource=copy.deepcopy(current),
                error_code="STALE_VERSION",
            )

        updated = Resource(
            id=current.id,
            resource_type=current.resource_type,
            business_state=copy.deepcopy(business_state),
            coordination_state=(
                copy.deepcopy(coordination_state)
                if coordination_state is not None
                else copy.deepcopy(current.coordination_state)
            ),
            version=current.version + 1,
            created_at=current.created_at,
            updated_at=_utcnow(),
        )
        self._store[resource_id] = updated
        return CASResult(success=True, resource=copy.deepcopy(updated))

    def create(self, resource: Resource) -> Resource:
        if resource.id in self._store:
            raise ValueError(
                f"Resource '{resource.id}' already exists. Use compare_and_swap to update."
            )
        stored = copy.deepcopy(resource)
        self._store[resource.id] = stored
        return copy.deepcopy(stored)

    def exists(self, resource_id: str) -> bool:
        return resource_id in self._store

    # Convenience for tests
    def __len__(self) -> int:
        return len(self._store)


class InMemoryIdempotencyStore(IdempotencyStore):
    """Dict-backed IdempotencyStore for testing and local development.

    Records are keyed by (key, scope, scope_id) tuples.
    """

    def __init__(self) -> None:
        self._store: dict[tuple, IdempotencyRecord] = {}

    def _key(self, key: str, scope: IdempotencyScope, scope_id: str) -> tuple:
        return (key, scope, scope_id)

    def check(
        self, key: str, scope: IdempotencyScope, scope_id: str
    ) -> Optional[IdempotencyRecord]:
        return self._store.get(self._key(key, scope, scope_id))

    def record(
        self,
        key: str,
        scope: IdempotencyScope,
        scope_id: str,
        result_ref: str,
    ) -> IdempotencyRecord:
        k = self._key(key, scope, scope_id)
        if k in self._store:
            raise ValueError(
                f"Idempotency key '{key}' already recorded for "
                f"scope={scope.value} scope_id='{scope_id}'."
            )
        rec = IdempotencyRecord(
            key=key,
            scope=scope,
            scope_id=scope_id,
            result_ref=result_ref,
            recorded_at=_utcnow(),
        )
        self._store[k] = rec
        return rec

    def __len__(self) -> int:
        return len(self._store)
