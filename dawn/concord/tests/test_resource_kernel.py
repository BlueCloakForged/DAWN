"""Tests for CONCORD Phase 2 — resource_kernel.py.

Covers:
- CASResult / ReadResult / IdempotencyRecord field contracts
- InMemoryResourceRepository: create, fetch, exists, CAS success/conflict
- CAS atomicity: version increments by 1, updated_at advances, created_at preserved
- CAS with coordination_state override vs. preservation
- read_with_profile: all five consistency profiles, error paths, missing-arg guards
- InMemoryIdempotencyStore: check (miss/hit), record (new/duplicate)
- Idempotency scopes: SESSION, RESOURCE, GLOBAL are independent namespaces
- ABC contracts: ResourceRepository and IdempotencyStore cannot be instantiated directly
"""

import time
from datetime import datetime, timezone

import pytest

from dawn.concord.resource_kernel import (
    CASResult,
    IdempotencyRecord,
    IdempotencyStore,
    InMemoryIdempotencyStore,
    InMemoryResourceRepository,
    ReadResult,
    ResourceRepository,
    read_with_profile,
)
from dawn.concord.types.entities import Resource
from dawn.concord.types.enums import ConsistencyProfile, FreshnessStatus, IdempotencyScope


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_resource(
    id="cr-1",
    resource_type="change_request",
    business_state=None,
    coordination_state=None,
    version=1,
) -> Resource:
    now = datetime.now(timezone.utc)
    return Resource(
        id=id,
        resource_type=resource_type,
        business_state=business_state or {"status": "draft"},
        coordination_state=coordination_state or {},
        version=version,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def repo():
    return InMemoryResourceRepository()


@pytest.fixture
def resource():
    return make_resource()


@pytest.fixture
def populated_repo(repo, resource):
    repo.create(resource)
    return repo


@pytest.fixture
def idempotency_store():
    return InMemoryIdempotencyStore()


# ── Result type contracts ──────────────────────────────────────────────────────


class TestCASResult:
    def test_success_result(self, resource):
        r = CASResult(success=True, resource=resource)
        assert r.success is True
        assert r.resource is resource
        assert r.error_code is None

    def test_conflict_result(self, resource):
        r = CASResult(success=False, resource=resource, error_code="STALE_VERSION")
        assert r.success is False
        assert r.error_code == "STALE_VERSION"

    def test_is_frozen(self, resource):
        r = CASResult(success=True, resource=resource)
        with pytest.raises((AttributeError, TypeError)):
            r.success = False  # type: ignore


class TestReadResult:
    def test_fresh_result(self, resource):
        r = ReadResult(resource=resource, freshness_status=FreshnessStatus.FRESH)
        assert r.freshness_status == FreshnessStatus.FRESH
        assert r.error_code is None
        assert r.projection_lag_ms is None

    def test_stale_result_with_error(self, resource):
        r = ReadResult(
            resource=resource,
            freshness_status=FreshnessStatus.STALE,
            error_code="STALE_VERSION",
        )
        assert r.error_code == "STALE_VERSION"

    def test_projection_lag_attached(self, resource):
        r = ReadResult(
            resource=resource,
            freshness_status=FreshnessStatus.WARNING,
            projection_lag_ms=250,
        )
        assert r.projection_lag_ms == 250

    def test_is_frozen(self, resource):
        r = ReadResult(resource=resource, freshness_status=FreshnessStatus.FRESH)
        with pytest.raises((AttributeError, TypeError)):
            r.freshness_status = FreshnessStatus.STALE  # type: ignore


# ── InMemoryResourceRepository ────────────────────────────────────────────────


class TestRepositoryCreate:
    def test_create_returns_resource(self, repo, resource):
        result = repo.create(resource)
        assert isinstance(result, Resource)
        assert result.id == "cr-1"

    def test_create_makes_exists_true(self, repo, resource):
        repo.create(resource)
        assert repo.exists("cr-1") is True

    def test_exists_false_before_create(self, repo):
        assert repo.exists("cr-1") is False

    def test_create_duplicate_raises(self, repo, resource):
        repo.create(resource)
        with pytest.raises(ValueError, match="already exists"):
            repo.create(resource)

    def test_create_isolates_from_caller(self, repo):
        res = make_resource(business_state={"status": "draft"})
        repo.create(res)
        # Mutating original dict should not affect stored copy
        res.business_state["status"] = "mutated"
        fetched = repo.fetch("cr-1")
        assert fetched.business_state["status"] == "draft"

    def test_len_increments(self, repo, resource):
        assert len(repo) == 0
        repo.create(resource)
        assert len(repo) == 1


class TestRepositoryFetch:
    def test_fetch_returns_correct_resource(self, populated_repo):
        r = populated_repo.fetch("cr-1")
        assert r.id == "cr-1"
        assert r.version == 1

    def test_fetch_missing_raises_key_error(self, repo):
        with pytest.raises(KeyError, match="cr-1"):
            repo.fetch("cr-1")

    def test_fetch_returns_deep_copy(self, populated_repo):
        r1 = populated_repo.fetch("cr-1")
        r2 = populated_repo.fetch("cr-1")
        assert r1 is not r2
        assert r1.business_state is not r2.business_state


# ── compare_and_swap ──────────────────────────────────────────────────────────


class TestCAS:
    def test_cas_success_returns_updated_resource(self, populated_repo):
        result = populated_repo.compare_and_swap(
            "cr-1",
            expected_version=1,
            business_state={"status": "submitted"},
        )
        assert result.success is True
        assert result.error_code is None
        assert result.resource.version == 2
        assert result.resource.business_state == {"status": "submitted"}

    def test_cas_increments_version_by_one(self, populated_repo):
        res = populated_repo.compare_and_swap(
            "cr-1", expected_version=1, business_state={"status": "submitted"}
        )
        assert res.resource.version == 2

    def test_cas_preserves_created_at(self, repo):
        res = make_resource()
        original_created = res.created_at
        repo.create(res)
        result = repo.compare_and_swap(
            "cr-1", expected_version=1, business_state={"status": "submitted"}
        )
        assert result.resource.created_at == original_created

    def test_cas_updates_updated_at(self, repo):
        res = make_resource()
        original_updated = res.updated_at
        time.sleep(0.001)  # ensure clock advances
        repo.create(res)
        result = repo.compare_and_swap(
            "cr-1", expected_version=1, business_state={"status": "submitted"}
        )
        assert result.resource.updated_at >= original_updated

    def test_cas_stale_version_returns_conflict(self, populated_repo):
        result = populated_repo.compare_and_swap(
            "cr-1",
            expected_version=99,  # wrong version
            business_state={"status": "submitted"},
        )
        assert result.success is False
        assert result.error_code == "STALE_VERSION"

    def test_cas_stale_version_returns_current_resource(self, populated_repo):
        result = populated_repo.compare_and_swap(
            "cr-1",
            expected_version=99,
            business_state={"status": "submitted"},
        )
        assert result.resource.version == 1  # unchanged

    def test_cas_stale_does_not_mutate_store(self, populated_repo):
        populated_repo.compare_and_swap(
            "cr-1", expected_version=99, business_state={"status": "submitted"}
        )
        fetched = populated_repo.fetch("cr-1")
        assert fetched.business_state == {"status": "draft"}
        assert fetched.version == 1

    def test_cas_with_coordination_state_override(self, populated_repo):
        result = populated_repo.compare_and_swap(
            "cr-1",
            expected_version=1,
            business_state={"status": "draft"},
            coordination_state={"lock": "session-42"},
        )
        assert result.success is True
        assert result.resource.coordination_state == {"lock": "session-42"}

    def test_cas_without_coordination_state_preserves_existing(self, repo):
        res = make_resource(coordination_state={"lock": "session-1"})
        repo.create(res)
        result = repo.compare_and_swap(
            "cr-1",
            expected_version=1,
            business_state={"status": "submitted"},
            # coordination_state not provided
        )
        assert result.resource.coordination_state == {"lock": "session-1"}

    def test_cas_sequential_writes(self, populated_repo):
        populated_repo.compare_and_swap(
            "cr-1", expected_version=1, business_state={"status": "submitted"}
        )
        result = populated_repo.compare_and_swap(
            "cr-1", expected_version=2, business_state={"status": "under_review"}
        )
        assert result.success is True
        assert result.resource.version == 3

    def test_cas_missing_resource_raises(self, repo):
        with pytest.raises(KeyError):
            repo.compare_and_swap("ghost", expected_version=1, business_state={})

    def test_cas_result_is_deep_copy(self, populated_repo):
        result = populated_repo.compare_and_swap(
            "cr-1", expected_version=1, business_state={"status": "submitted"}
        )
        # Mutating returned dict should not affect stored state
        result.resource.business_state["status"] = "tampered"
        fetched = populated_repo.fetch("cr-1")
        assert fetched.business_state["status"] == "submitted"

    def test_second_cas_with_stale_v1_after_successful_write(self, populated_repo):
        # Simulate two concurrent sessions both reading v1
        populated_repo.compare_and_swap(
            "cr-1", expected_version=1, business_state={"status": "submitted"}
        )
        # Second session still at v1 — must be rejected
        result = populated_repo.compare_and_swap(
            "cr-1", expected_version=1, business_state={"status": "blocked"}
        )
        assert result.success is False
        assert result.error_code == "STALE_VERSION"


# ── ABC enforcement ───────────────────────────────────────────────────────────


class TestABCEnforcement:
    def test_resource_repository_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            ResourceRepository()  # type: ignore

    def test_idempotency_store_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            IdempotencyStore()  # type: ignore

    def test_in_memory_repo_is_resource_repository(self, repo):
        assert isinstance(repo, ResourceRepository)

    def test_in_memory_idempotency_store_is_idempotency_store(self, idempotency_store):
        assert isinstance(idempotency_store, IdempotencyStore)


# ── read_with_profile ─────────────────────────────────────────────────────────


class TestReadWithProfile:
    def test_strong_returns_fresh(self, populated_repo):
        result = read_with_profile(
            populated_repo, "cr-1", ConsistencyProfile.STRONG
        )
        assert result.freshness_status == FreshnessStatus.FRESH
        assert result.error_code is None
        assert result.resource.id == "cr-1"

    def test_strong_missing_resource_raises(self, repo):
        with pytest.raises(KeyError):
            read_with_profile(repo, "ghost", ConsistencyProfile.STRONG)

    # SESSION_MONOTONIC ───────────────────────────────────────────────────────

    def test_session_monotonic_fresh_when_version_meets_watermark(self, populated_repo):
        result = read_with_profile(
            populated_repo, "cr-1", ConsistencyProfile.SESSION_MONOTONIC,
            session_watermark=1,
        )
        assert result.freshness_status == FreshnessStatus.FRESH
        assert result.error_code is None

    def test_session_monotonic_fresh_when_version_exceeds_watermark(self, repo):
        repo.create(make_resource(version=5))
        result = read_with_profile(
            repo, "cr-1", ConsistencyProfile.SESSION_MONOTONIC,
            session_watermark=3,
        )
        assert result.freshness_status == FreshnessStatus.FRESH

    def test_session_monotonic_stale_when_version_below_watermark(self, populated_repo):
        result = read_with_profile(
            populated_repo, "cr-1", ConsistencyProfile.SESSION_MONOTONIC,
            session_watermark=5,
        )
        assert result.freshness_status == FreshnessStatus.STALE
        assert result.error_code == "STALE_VERSION"

    def test_session_monotonic_requires_watermark(self, populated_repo):
        with pytest.raises(ValueError, match="session_watermark"):
            read_with_profile(
                populated_repo, "cr-1", ConsistencyProfile.SESSION_MONOTONIC
            )

    # READ_YOUR_WRITES ────────────────────────────────────────────────────────

    def test_read_your_writes_fresh_when_version_meets_min(self, populated_repo):
        result = read_with_profile(
            populated_repo, "cr-1", ConsistencyProfile.READ_YOUR_WRITES,
            min_version=1,
        )
        assert result.freshness_status == FreshnessStatus.FRESH
        assert result.error_code is None

    def test_read_your_writes_warning_when_version_below_min(self, populated_repo):
        result = read_with_profile(
            populated_repo, "cr-1", ConsistencyProfile.READ_YOUR_WRITES,
            min_version=3,
        )
        assert result.freshness_status == FreshnessStatus.WARNING
        assert result.error_code == "READ_FRESHNESS_UNAVAILABLE"

    def test_read_your_writes_requires_min_version(self, populated_repo):
        with pytest.raises(ValueError, match="min_version"):
            read_with_profile(
                populated_repo, "cr-1", ConsistencyProfile.READ_YOUR_WRITES
            )

    # EVENTUAL ────────────────────────────────────────────────────────────────

    def test_eventual_returns_warning(self, populated_repo):
        result = read_with_profile(
            populated_repo, "cr-1", ConsistencyProfile.EVENTUAL
        )
        assert result.freshness_status == FreshnessStatus.WARNING
        assert result.error_code is None

    def test_eventual_still_returns_resource(self, populated_repo):
        result = read_with_profile(
            populated_repo, "cr-1", ConsistencyProfile.EVENTUAL
        )
        assert result.resource.id == "cr-1"

    # ASYNC_PROJECTION ────────────────────────────────────────────────────────

    def test_async_projection_returns_warning(self, populated_repo):
        result = read_with_profile(
            populated_repo, "cr-1", ConsistencyProfile.ASYNC_PROJECTION,
            projection_lag_ms=500,
        )
        assert result.freshness_status == FreshnessStatus.WARNING
        assert result.error_code is None

    def test_async_projection_attaches_lag(self, populated_repo):
        result = read_with_profile(
            populated_repo, "cr-1", ConsistencyProfile.ASYNC_PROJECTION,
            projection_lag_ms=250,
        )
        assert result.projection_lag_ms == 250

    def test_async_projection_lag_none_by_default(self, populated_repo):
        result = read_with_profile(
            populated_repo, "cr-1", ConsistencyProfile.ASYNC_PROJECTION
        )
        assert result.projection_lag_ms is None


# ── InMemoryIdempotencyStore ───────────────────────────────────────────────────


class TestIdempotencyStore:
    def test_check_miss_returns_none(self, idempotency_store):
        result = idempotency_store.check(
            "key-abc", IdempotencyScope.SESSION, "session-1"
        )
        assert result is None

    def test_record_returns_idempotency_record(self, idempotency_store):
        rec = idempotency_store.record(
            "key-abc", IdempotencyScope.SESSION, "session-1", "receipt-001"
        )
        assert isinstance(rec, IdempotencyRecord)
        assert rec.key == "key-abc"
        assert rec.scope == IdempotencyScope.SESSION
        assert rec.scope_id == "session-1"
        assert rec.result_ref == "receipt-001"

    def test_record_then_check_returns_record(self, idempotency_store):
        idempotency_store.record("key-abc", IdempotencyScope.SESSION, "s1", "r1")
        rec = idempotency_store.check("key-abc", IdempotencyScope.SESSION, "s1")
        assert rec is not None
        assert rec.result_ref == "r1"

    def test_record_duplicate_raises(self, idempotency_store):
        idempotency_store.record("key-abc", IdempotencyScope.SESSION, "s1", "r1")
        with pytest.raises(ValueError, match="already recorded"):
            idempotency_store.record("key-abc", IdempotencyScope.SESSION, "s1", "r2")

    def test_same_key_different_scope_ids_are_independent(self, idempotency_store):
        idempotency_store.record("key-abc", IdempotencyScope.SESSION, "s1", "r1")
        # Different scope_id — should succeed
        rec = idempotency_store.record("key-abc", IdempotencyScope.SESSION, "s2", "r2")
        assert rec.scope_id == "s2"

    def test_same_key_different_scopes_are_independent(self, idempotency_store):
        idempotency_store.record("key-abc", IdempotencyScope.SESSION, "s1", "r1")
        idempotency_store.record("key-abc", IdempotencyScope.RESOURCE, "res-1", "r2")
        idempotency_store.record("key-abc", IdempotencyScope.GLOBAL, "", "r3")
        assert len(idempotency_store) == 3

    def test_global_scope_uses_empty_scope_id(self, idempotency_store):
        idempotency_store.record("key-global", IdempotencyScope.GLOBAL, "", "r1")
        rec = idempotency_store.check("key-global", IdempotencyScope.GLOBAL, "")
        assert rec is not None
        assert rec.scope == IdempotencyScope.GLOBAL

    def test_recorded_at_is_set(self, idempotency_store):
        rec = idempotency_store.record("k", IdempotencyScope.SESSION, "s1", "r1")
        assert isinstance(rec.recorded_at, datetime)

    def test_len_tracks_record_count(self, idempotency_store):
        assert len(idempotency_store) == 0
        idempotency_store.record("k1", IdempotencyScope.SESSION, "s1", "r1")
        idempotency_store.record("k2", IdempotencyScope.SESSION, "s1", "r2")
        assert len(idempotency_store) == 2

    def test_check_after_duplicate_attempt_still_returns_original(self, idempotency_store):
        idempotency_store.record("key", IdempotencyScope.SESSION, "s1", "original-ref")
        try:
            idempotency_store.record("key", IdempotencyScope.SESSION, "s1", "new-ref")
        except ValueError:
            pass
        rec = idempotency_store.check("key", IdempotencyScope.SESSION, "s1")
        assert rec.result_ref == "original-ref"
