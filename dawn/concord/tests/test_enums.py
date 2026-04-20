"""Tests for CONCORD v0.3/v0.4 enums — runtime (16) + coordination (4) + scanner (7) + v0.4-alpha (9) + v0.4-beta (2) + v0.4-rc (5)."""

import pytest

from dawn.concord.types.enums import (
    ActionFamily,
    AuthenticationMethod,
    BundleStatus,
    CircuitState,
    CompensationStrategy,
    ConflictResolutionStrategy,
    ConsistencyProfile,
    CooldownPolicy,
    DangerType,
    DependencyEdgeType,
    DispatchPriority,
    DispatchStatus,
    EntryChannel,
    EnvironmentClass,
    EnvironmentStatus,
    EvidenceSource,
    FleetCompletionPolicy,
    FleetStatus,
    FreshnessStatus,
    IdempotencyScope,
    IntentStatus,
    IsolationLevel,
    IsolationRequirement,
    LeaseStatus,
    LeaseType,
    MaturityLevel,
    PatchPriority,
    ProvisioningStatus,
    RetryClass,
    RiskLevel,
    SagaTimeoutPolicy,
    ScopedRuleAppliesTo,
    ScopedRuleSeverity,
    ScopedRuleType,
    ScopeType,
    SessionMode,
    SessionStatus,
    SilentFailureLikelihood,
    SinglePointDangerCategory,
    TokenStatus,
    TokenType,
    TripRecoveryPolicy,
    TrustTier,
)


# ── Runtime enums ─────────────────────────────────────────────────────────────


class TestTrustTier:
    def test_all_five_tiers_present(self):
        values = {t.value for t in TrustTier}
        assert values == {
            "T0/observe",
            "T1/propose",
            "T2/bounded",
            "T3/privileged",
            "T4/governed_critical",
        }

    def test_is_str_enum(self):
        assert TrustTier.T0_OBSERVE == "T0/observe"
        assert isinstance(TrustTier.T4_GOVERNED_CRITICAL, str)


class TestActionFamily:
    def test_all_seven_families(self):
        expected = {"read", "plan", "mutate", "approve", "deploy", "compensate", "admin"}
        assert {f.value for f in ActionFamily} == expected


class TestConsistencyProfile:
    def test_all_five_profiles(self):
        expected = {
            "STRONG",
            "SESSION_MONOTONIC",
            "READ_YOUR_WRITES",
            "EVENTUAL",
            "ASYNC_PROJECTION",
        }
        assert {p.value for p in ConsistencyProfile} == expected


class TestConflictResolutionStrategy:
    def test_all_six_strategies(self):
        expected = {"default", "fail_fast", "queue_first", "lease_first", "policy_first", "custom"}
        assert {s.value for s in ConflictResolutionStrategy} == expected


class TestSagaTimeoutPolicy:
    def test_all_four_policies(self):
        expected = {"fixed", "step_adaptive", "heartbeat", "external_gated"}
        assert {p.value for p in SagaTimeoutPolicy} == expected


class TestCompensationStrategy:
    def test_all_four_strategies(self):
        expected = {"none", "inverse_action", "saga_handler", "manual_only"}
        assert {s.value for s in CompensationStrategy} == expected


class TestRetryClass:
    def test_all_four_classes(self):
        expected = {"none", "safe_retry", "recheck_then_retry", "queue_then_retry"}
        assert {c.value for c in RetryClass} == expected


class TestRiskLevel:
    def test_all_four_levels(self):
        assert {r.value for r in RiskLevel} == {"low", "moderate", "high", "critical"}


class TestLeaseType:
    def test_all_five_types(self):
        expected = {"edit", "review", "execute", "reservation", "approval_slot"}
        assert {t.value for t in LeaseType} == expected


class TestTokenType:
    def test_all_four_types(self):
        expected = {"capacity", "quorum", "validation_gate", "deployment_gate"}
        assert {t.value for t in TokenType} == expected


class TestCircuitState:
    def test_all_three_states(self):
        assert {s.value for s in CircuitState} == {"closed", "throttled", "open"}


class TestCooldownPolicy:
    def test_all_five_policies(self):
        expected = {
            "fixed_backoff",
            "exponential_backoff",
            "contention_scaled",
            "risk_scaled",
            "manual_resume_required",
        }
        assert {p.value for p in CooldownPolicy} == expected


class TestIntentStatus:
    def test_all_nine_statuses(self):
        expected = {
            "proposed", "admitted", "queued", "blocked", "executing",
            "committed", "compensated", "failed", "expired",
        }
        assert {s.value for s in IntentStatus} == expected


class TestSessionMode:
    def test_all_four_modes(self):
        expected = {"read_only", "propose_only", "execute", "supervised"}
        assert {m.value for m in SessionMode} == expected


class TestFreshnessStatus:
    def test_all_three_statuses(self):
        assert {s.value for s in FreshnessStatus} == {"fresh", "warning", "stale"}


class TestTripRecoveryPolicy:
    def test_all_three_policies(self):
        expected = {"auto_after_cooldown", "manual_reset", "gradual_ramp"}
        assert {p.value for p in TripRecoveryPolicy} == expected


# ── Coordination status enums ─────────────────────────────────────────────────


class TestLeaseStatus:
    def test_all_four_statuses(self):
        assert {s.value for s in LeaseStatus} == {"active", "expired", "released", "revoked"}

    def test_is_str_enum(self):
        assert LeaseStatus.ACTIVE == "active"


class TestTokenStatus:
    def test_all_four_statuses(self):
        assert {s.value for s in TokenStatus} == {"active", "exhausted", "expired", "suspended"}


class TestIdempotencyScope:
    def test_all_three_scopes(self):
        assert {s.value for s in IdempotencyScope} == {"session", "resource", "global"}


class TestSessionStatus:
    def test_all_three_statuses(self):
        assert {s.value for s in SessionStatus} == {"active", "expired", "terminated"}


# ── Phase 9 scanner enums ─────────────────────────────────────────────────────


class TestMaturityLevel:
    def test_seven_levels(self):
        assert len(MaturityLevel) == 7

    def test_level_values(self):
        expected = {f"level_{i}" for i in range(7)}
        assert {l.value for l in MaturityLevel} == expected


class TestDangerType:
    def test_two_types(self):
        assert {d.value for d in DangerType} == {"single_point", "compound"}


class TestDependencyEdgeType:
    def test_all_six_edge_types(self):
        expected = {
            "mutates",
            "reads_before_mutation",
            "projects_to",
            "background_updates",
            "triggers",
            "depends_on_external",
        }
        assert {e.value for e in DependencyEdgeType} == expected


class TestPatchPriority:
    def test_all_four_priorities(self):
        assert {p.value for p in PatchPriority} == {"P0", "P1", "P2", "P3"}

    def test_p0_is_highest(self):
        assert PatchPriority.P0 == "P0"


class TestEvidenceSource:
    def test_all_three_sources(self):
        assert {e.value for e in EvidenceSource} == {"discovered", "inferred", "heuristic"}


class TestSilentFailureLikelihood:
    def test_all_three_values(self):
        assert {s.value for s in SilentFailureLikelihood} == {"low", "moderate", "high"}


class TestSinglePointDangerCategory:
    def test_exactly_eight_categories(self):
        assert len(SinglePointDangerCategory) == 8

    def test_all_eight_categories_present(self):
        expected = {
            "destructive_without_idempotency",
            "mutable_without_versioning",
            "shared_without_coordination",
            "implicit_ordering_dependency",
            "background_job_api_collision",
            "missing_authoritative_recheck",
            "unbounded_bulk_mutation",
            "multi_step_without_compensation",
        }
        assert {c.value for c in SinglePointDangerCategory} == expected


# ── v0.4-alpha: fleet + environment enums ─────────────────────────────────────


class TestEnvironmentClass:
    def test_all_three_classes(self):
        assert {e.value for e in EnvironmentClass} == {"ephemeral", "persistent", "shared_pool"}

    def test_is_str_enum(self):
        assert EnvironmentClass.EPHEMERAL == "ephemeral"


class TestProvisioningStatus:
    def test_all_six_statuses(self):
        expected = {"cold", "warming", "ready", "assigned", "draining", "terminated"}
        assert {s.value for s in ProvisioningStatus} == expected


class TestIsolationLevel:
    def test_all_four_levels(self):
        expected = {"none", "container", "vm", "dedicated_host"}
        assert {l.value for l in IsolationLevel} == expected

    def test_container_is_minimum_for_unattended(self):
        # Normative: unattended sessions require isolation_level >= container
        levels = list(IsolationLevel)
        container_idx = levels.index(IsolationLevel.CONTAINER)
        assert container_idx > levels.index(IsolationLevel.NONE)


class TestEnvironmentStatus:
    def test_all_three_statuses(self):
        assert {s.value for s in EnvironmentStatus} == {"active", "unhealthy", "terminated"}


class TestFleetStatus:
    def test_all_five_statuses(self):
        expected = {"assembling", "active", "draining", "completed", "aborted"}
        assert {s.value for s in FleetStatus} == expected


class TestFleetCompletionPolicy:
    def test_all_four_policies(self):
        expected = {"all_must_succeed", "best_effort", "first_success", "quorum_n"}
        assert {p.value for p in FleetCompletionPolicy} == expected


class TestIsolationRequirement:
    def test_all_three_requirements(self):
        assert {r.value for r in IsolationRequirement} == {"per_session", "shared", "mixed"}


class TestDispatchStatus:
    def test_all_six_statuses(self):
        expected = {"queued", "assigned", "active", "completed", "failed", "cancelled"}
        assert {s.value for s in DispatchStatus} == expected

    def test_is_str_enum(self):
        assert DispatchStatus.QUEUED == "queued"


class TestDispatchPriority:
    def test_all_four_priorities(self):
        assert {p.value for p in DispatchPriority} == {"low", "normal", "high", "critical"}


# ── v0.4-beta: entry-point enums ──────────────────────────────────────────────


class TestEntryChannel:
    def test_all_seven_channels(self):
        expected = {"cli", "web_ui", "slack", "api", "webhook", "cron", "event_trigger"}
        assert {c.value for c in EntryChannel} == expected

    def test_is_str_enum(self):
        assert EntryChannel.CLI == "cli"
        assert EntryChannel.SLACK == "slack"


class TestAuthenticationMethod:
    def test_all_five_methods(self):
        expected = {"token", "oauth", "session_cookie", "service_account", "none"}
        assert {m.value for m in AuthenticationMethod} == expected

    def test_none_value(self):
        assert AuthenticationMethod.NONE == "none"


# ── v0.4-rc: context-scope + review enums ─────────────────────────────────────


class TestScopeType:
    def test_all_six_types(self):
        expected = {"resource_type", "domain", "path_glob", "tag", "action_family", "composite"}
        assert {s.value for s in ScopeType} == expected

    def test_is_str_enum(self):
        assert ScopeType.PATH_GLOB == "path_glob"


class TestScopedRuleType:
    def test_all_five_types(self):
        expected = {"convention", "constraint", "preference", "warning", "escalation_trigger"}
        assert {t.value for t in ScopedRuleType} == expected


class TestScopedRuleSeverity:
    def test_all_three_severities(self):
        assert {s.value for s in ScopedRuleSeverity} == {"advisory", "recommended", "required"}

    def test_required_is_strongest(self):
        assert ScopedRuleSeverity.REQUIRED == "required"


class TestScopedRuleAppliesTo:
    def test_all_four_targets(self):
        assert {t.value for t in ScopedRuleAppliesTo} == {"agent", "validator", "reviewer", "all"}


class TestBundleStatus:
    def test_all_four_statuses(self):
        expected = {"pending_review", "approved", "rejected", "revision_requested"}
        assert {s.value for s in BundleStatus} == expected

    def test_is_str_enum(self):
        assert BundleStatus.APPROVED == "approved"
        assert BundleStatus.PENDING_REVIEW == "pending_review"
