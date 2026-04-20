"""Tests for CONCORD v0.3/v0.4 entity dataclasses.

Covers:
- v0.3 entities: Session, Receipt, BudgetProfile, BudgetLedger field additions
- v0.4-alpha new entities: ExecutionEnvironment, TaskFleet, DispatchRequest
- v0.4-beta new entities: EntryPoint; Intent entry_point_id/channel fields
- Normative invariants on new entities
"""

from datetime import datetime, timezone

import pytest

from dawn.concord.types.entities import (
    BudgetLedger,
    BudgetProfile,
    CircuitBreakerThresholds,
    ContextScope,
    DispatchRequest,
    EntryPoint,
    ExecutionEnvironment,
    Intent,
    Receipt,
    ReviewBundle,
    ScopedRule,
    Session,
    TaskFleet,
)
from dawn.concord.types.enums import (
    AuthenticationMethod,
    BundleStatus,
    CircuitState,
    ConsistencyProfile,
    CooldownPolicy,
    DispatchPriority,
    DispatchStatus,
    EntryChannel,
    EnvironmentClass,
    EnvironmentStatus,
    FleetCompletionPolicy,
    FleetStatus,
    IntentStatus,
    IsolationLevel,
    IsolationRequirement,
    ProvisioningStatus,
    RiskLevel,
    ScopedRuleAppliesTo,
    ScopedRuleSeverity,
    ScopedRuleType,
    ScopeType,
    SessionMode,
    SessionStatus,
    TripRecoveryPolicy,
    TrustTier,
)

NOW = datetime(2026, 3, 5, 12, 0, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 3, 5, 13, 0, 0, tzinfo=timezone.utc)


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_thresholds() -> CircuitBreakerThresholds:
    return CircuitBreakerThresholds(
        stale_version_failure_rate=0.1,
        budget_exceeded_rate=0.05,
        error_rate=0.2,
        evaluation_window_ms=60000,
        trip_recovery_policy=TripRecoveryPolicy.AUTO_AFTER_COOLDOWN,
    )


def make_session(**kwargs) -> Session:
    defaults = dict(
        id="sess-1",
        agent_id="agent-1",
        agent_class_id="cls-1",
        trust_tier=TrustTier.T2_BOUNDED,
        mode=SessionMode.EXECUTE,
        status=SessionStatus.ACTIVE,
        watermark=0,
        started_at=NOW,
        budget_profile_id="bp-1",
    )
    defaults.update(kwargs)
    return Session(**defaults)


def make_receipt(**kwargs) -> Receipt:
    defaults = dict(
        operation_id="op-1",
        intent_id="intent-1",
        previous_state={"status": "draft"},
        next_state={"status": "submitted"},
        version_before=1,
        version_after=2,
        result_status="success",
        duration_ms=120,
        policy_decision="admitted",
    )
    defaults.update(kwargs)
    return Receipt(**defaults)


def make_env(**kwargs) -> ExecutionEnvironment:
    defaults = dict(
        environment_id="env-1",
        environment_class=EnvironmentClass.EPHEMERAL,
        provisioning_status=ProvisioningStatus.READY,
        isolation_level=IsolationLevel.CONTAINER,
        resource_spec={"cpu": 2, "memory_gb": 4},
        preload_manifest=["sha256:abc123"],
        created_at=NOW,
        max_lifetime_ms=3600000,
        heartbeat_interval_ms=30000,
        status=EnvironmentStatus.ACTIVE,
    )
    defaults.update(kwargs)
    return ExecutionEnvironment(**defaults)


def make_fleet(**kwargs) -> TaskFleet:
    defaults = dict(
        fleet_id="fleet-1",
        owner_session_id="sess-owner",
        agent_class_id="cls-1",
        max_concurrent=5,
        member_sessions=[],
        fleet_status=FleetStatus.ACTIVE,
        budget_profile_id="bp-1",
        isolation_requirement=IsolationRequirement.PER_SESSION,
        completion_policy=FleetCompletionPolicy.ALL_MUST_SUCCEED,
        created_at=NOW,
        timeout_at=LATER,
    )
    defaults.update(kwargs)
    return TaskFleet(**defaults)


def make_dispatch(**kwargs) -> DispatchRequest:
    defaults = dict(
        dispatch_id="dispatch-1",
        fleet_id="fleet-1",
        task_description={"type": "fix_bug", "issue_id": "GH-42"},
        priority=DispatchPriority.NORMAL,
        max_attempts=3,
        attempt_count=0,
        idempotency_key="idem-abc-123",
        dispatch_status=DispatchStatus.QUEUED,
    )
    defaults.update(kwargs)
    return DispatchRequest(**defaults)


# ── v0.3 field additions: Session ────────────────────────────────────────────


class TestSessionV04Fields:
    def test_environment_id_defaults_to_none(self):
        s = make_session()
        assert s.environment_id is None

    def test_fleet_id_defaults_to_none(self):
        s = make_session()
        assert s.fleet_id is None

    def test_environment_id_can_be_set(self):
        s = make_session(environment_id="env-42")
        assert s.environment_id == "env-42"

    def test_fleet_id_can_be_set(self):
        s = make_session(fleet_id="fleet-7")
        assert s.fleet_id == "fleet-7"


# ── v0.3 field additions: Receipt ────────────────────────────────────────────


class TestReceiptV04Fields:
    def test_environment_id_defaults_to_none(self):
        r = make_receipt()
        assert r.environment_id is None

    def test_entry_point_id_defaults_to_none(self):
        r = make_receipt()
        assert r.entry_point_id is None

    def test_environment_id_can_be_set(self):
        r = make_receipt(environment_id="env-99")
        assert r.environment_id == "env-99"


# ── v0.3 field additions: BudgetProfile ──────────────────────────────────────


class TestBudgetProfileV04Fields:
    def test_max_parallel_environments_defaults_to_none(self):
        bp = BudgetProfile(
            id="bp-1",
            max_actions_per_minute=60,
            max_mutating_actions_per_hour=24,
            max_high_risk_per_day=3,
            max_cost_units_per_session=40.0,
            burst_limit=10,
            circuit_breaker_thresholds=make_thresholds(),
            cooldown_policy=CooldownPolicy.CONTENTION_SCALED,
        )
        assert bp.max_parallel_environments is None

    def test_max_parallel_environments_can_be_set(self):
        bp = BudgetProfile(
            id="bp-2",
            max_actions_per_minute=60,
            max_mutating_actions_per_hour=24,
            max_high_risk_per_day=3,
            max_cost_units_per_session=40.0,
            burst_limit=10,
            circuit_breaker_thresholds=make_thresholds(),
            cooldown_policy=CooldownPolicy.CONTENTION_SCALED,
            max_parallel_environments=4,
        )
        assert bp.max_parallel_environments == 4


# ── v0.3 field additions: BudgetLedger ───────────────────────────────────────


class TestBudgetLedgerV04Fields:
    def test_fleet_id_defaults_to_none(self):
        bl = BudgetLedger(
            ledger_id="led-1",
            session_id="sess-1",
            agent_class_id="cls-1",
            budget_profile_id="bp-1",
            window_start=NOW,
            window_end=LATER,
            actions_consumed=5,
            mutating_actions_consumed=2,
            high_risk_actions_consumed=0,
            cost_units_consumed=10.0,
            parallel_leases_in_use=1,
            queue_slots_in_use=0,
            circuit_state=CircuitState.CLOSED,
        )
        assert bl.fleet_id is None

    def test_fleet_id_can_be_set(self):
        bl = BudgetLedger(
            ledger_id="led-2",
            session_id="sess-2",
            agent_class_id="cls-1",
            budget_profile_id="bp-1",
            window_start=NOW,
            window_end=LATER,
            actions_consumed=0,
            mutating_actions_consumed=0,
            high_risk_actions_consumed=0,
            cost_units_consumed=0.0,
            parallel_leases_in_use=0,
            queue_slots_in_use=0,
            circuit_state=CircuitState.CLOSED,
            fleet_id="fleet-1",
        )
        assert bl.fleet_id == "fleet-1"


# ── v0.4-alpha new entity: ExecutionEnvironment ───────────────────────────────


class TestExecutionEnvironment:
    def test_basic_construction(self):
        env = make_env()
        assert env.environment_id == "env-1"
        assert env.environment_class == EnvironmentClass.EPHEMERAL
        assert env.isolation_level == IsolationLevel.CONTAINER
        assert env.status == EnvironmentStatus.ACTIVE

    def test_optional_fields_default_to_none(self):
        env = make_env()
        assert env.assigned_session_id is None
        assert env.ready_at is None
        assert env.assigned_at is None

    def test_assigned_session_can_be_set(self):
        env = make_env(assigned_session_id="sess-42", assigned_at=NOW)
        assert env.assigned_session_id == "sess-42"
        assert env.assigned_at == NOW

    def test_preload_manifest_is_list(self):
        env = make_env(preload_manifest=["sha256:aaa", "sha256:bbb"])
        assert len(env.preload_manifest) == 2

    def test_resource_spec_is_dict(self):
        env = make_env(resource_spec={"cpu": 4, "memory_gb": 8, "network": "10gbe"})
        assert env.resource_spec["cpu"] == 4

    def test_vm_isolation_level(self):
        env = make_env(isolation_level=IsolationLevel.VM)
        assert env.isolation_level == IsolationLevel.VM

    def test_provisioning_status_ready(self):
        env = make_env(provisioning_status=ProvisioningStatus.READY)
        assert env.provisioning_status == ProvisioningStatus.READY

    def test_unhealthy_status(self):
        env = make_env(status=EnvironmentStatus.UNHEALTHY)
        assert env.status == EnvironmentStatus.UNHEALTHY


# ── v0.4-alpha new entity: TaskFleet ─────────────────────────────────────────


class TestTaskFleet:
    def test_basic_construction(self):
        fleet = make_fleet()
        assert fleet.fleet_id == "fleet-1"
        assert fleet.max_concurrent == 5
        assert fleet.fleet_status == FleetStatus.ACTIVE

    def test_completion_policy_all_must_succeed(self):
        fleet = make_fleet(completion_policy=FleetCompletionPolicy.ALL_MUST_SUCCEED)
        assert fleet.completion_policy == FleetCompletionPolicy.ALL_MUST_SUCCEED

    def test_completion_policy_best_effort(self):
        fleet = make_fleet(completion_policy=FleetCompletionPolicy.BEST_EFFORT)
        assert fleet.completion_policy == FleetCompletionPolicy.BEST_EFFORT

    def test_member_sessions_starts_empty(self):
        fleet = make_fleet()
        assert fleet.member_sessions == []

    def test_member_sessions_can_be_populated(self):
        fleet = make_fleet(member_sessions=["sess-a", "sess-b", "sess-c"])
        assert len(fleet.member_sessions) == 3

    def test_timeout_at_after_created_at(self):
        fleet = make_fleet(created_at=NOW, timeout_at=LATER)
        assert fleet.timeout_at > fleet.created_at

    def test_isolation_requirement_per_session(self):
        fleet = make_fleet(isolation_requirement=IsolationRequirement.PER_SESSION)
        assert fleet.isolation_requirement == IsolationRequirement.PER_SESSION

    def test_assembling_status(self):
        fleet = make_fleet(fleet_status=FleetStatus.ASSEMBLING)
        assert fleet.fleet_status == FleetStatus.ASSEMBLING


# ── v0.4-alpha new entity: DispatchRequest ────────────────────────────────────


class TestDispatchRequest:
    def test_basic_construction(self):
        dr = make_dispatch()
        assert dr.dispatch_id == "dispatch-1"
        assert dr.fleet_id == "fleet-1"
        assert dr.dispatch_status == DispatchStatus.QUEUED

    def test_idempotency_key_is_required(self):
        # idempotency_key is a required field — missing it should raise TypeError
        with pytest.raises(TypeError):
            DispatchRequest(
                dispatch_id="d-1",
                fleet_id="f-1",
                task_description={},
                priority=DispatchPriority.NORMAL,
                max_attempts=3,
                attempt_count=0,
                dispatch_status=DispatchStatus.QUEUED,
                # idempotency_key deliberately omitted
            )

    def test_optional_assignment_fields_default_to_none(self):
        dr = make_dispatch()
        assert dr.assigned_session_id is None
        assert dr.assigned_environment_id is None
        assert dr.result_ref is None
        assert dr.entry_point_id is None
        assert dr.channel is None

    def test_assigned_fields_can_be_set(self):
        dr = make_dispatch(
            assigned_session_id="sess-99",
            assigned_environment_id="env-99",
            dispatch_status=DispatchStatus.ACTIVE,
        )
        assert dr.assigned_session_id == "sess-99"
        assert dr.assigned_environment_id == "env-99"
        assert dr.dispatch_status == DispatchStatus.ACTIVE

    def test_task_description_is_dict(self):
        dr = make_dispatch(task_description={"type": "review_pr", "pr_id": 101})
        assert dr.task_description["pr_id"] == 101

    def test_priority_critical(self):
        dr = make_dispatch(priority=DispatchPriority.CRITICAL)
        assert dr.priority == DispatchPriority.CRITICAL

    def test_attempt_count_starts_at_zero(self):
        dr = make_dispatch()
        assert dr.attempt_count == 0

    def test_completed_status(self):
        dr = make_dispatch(dispatch_status=DispatchStatus.COMPLETED, result_ref="ref://run/42")
        assert dr.dispatch_status == DispatchStatus.COMPLETED
        assert dr.result_ref == "ref://run/42"

    def test_channel_accepts_entry_channel_enum(self):
        dr = make_dispatch(channel=EntryChannel.SLACK)
        assert dr.channel == EntryChannel.SLACK

    def test_entry_point_id_can_be_set(self):
        dr = make_dispatch(entry_point_id="ep-slack-01")
        assert dr.entry_point_id == "ep-slack-01"


# ── v0.4-beta: Intent entry-point fields ─────────────────────────────────────


def make_intent(**kwargs) -> Intent:
    defaults = dict(
        id="intent-1",
        session_id="sess-1",
        resource_type="change_request",
        resource_id="cr-42",
        action_name="submit",
        idempotency_key="idem-xyz",
        status=IntentStatus.PROPOSED,
        consistency_profile=ConsistencyProfile.EVENTUAL,
        risk_level=RiskLevel.MODERATE,
        participates_in_saga=False,
        created_at=NOW,
    )
    defaults.update(kwargs)
    return Intent(**defaults)


class TestIntentV04BetaFields:
    def test_entry_point_id_defaults_to_none(self):
        i = make_intent()
        assert i.entry_point_id is None

    def test_channel_defaults_to_none(self):
        i = make_intent()
        assert i.channel is None

    def test_entry_point_id_can_be_set(self):
        i = make_intent(entry_point_id="ep-cli-01")
        assert i.entry_point_id == "ep-cli-01"

    def test_channel_accepts_enum(self):
        i = make_intent(channel=EntryChannel.CLI)
        assert i.channel == EntryChannel.CLI

    def test_channel_slack(self):
        i = make_intent(channel=EntryChannel.SLACK, entry_point_id="ep-slack-01")
        assert i.channel == EntryChannel.SLACK
        assert i.entry_point_id == "ep-slack-01"


# ── v0.4-beta: EntryPoint entity ──────────────────────────────────────────────


def make_entry_point(**kwargs) -> EntryPoint:
    defaults = dict(
        entry_point_id="ep-1",
        channel=EntryChannel.CLI,
        display_name="CLI Entry",
        admission_adapter_ref="adapter-cli-v1",
        required_fields=["task_description", "agent_class_id"],
        authentication_method=AuthenticationMethod.TOKEN,
        audit_channel=True,
    )
    defaults.update(kwargs)
    return EntryPoint(**defaults)


class TestEntryPoint:
    def test_basic_construction(self):
        ep = make_entry_point()
        assert ep.entry_point_id == "ep-1"
        assert ep.channel == EntryChannel.CLI
        assert ep.authentication_method == AuthenticationMethod.TOKEN
        assert ep.audit_channel is True

    def test_optional_fields_default_to_none(self):
        ep = make_entry_point()
        assert ep.default_agent_class_id is None
        assert ep.default_fleet_policy is None
        assert ep.rate_limit_profile_id is None

    def test_required_fields_is_list(self):
        ep = make_entry_point(required_fields=["task_description", "priority"])
        assert len(ep.required_fields) == 2
        assert "task_description" in ep.required_fields

    def test_slack_channel(self):
        ep = make_entry_point(
            entry_point_id="ep-slack",
            channel=EntryChannel.SLACK,
            display_name="Slack Entry",
            authentication_method=AuthenticationMethod.OAUTH,
        )
        assert ep.channel == EntryChannel.SLACK
        assert ep.authentication_method == AuthenticationMethod.OAUTH

    def test_default_agent_class_can_be_set(self):
        ep = make_entry_point(default_agent_class_id="cls-autonomous")
        assert ep.default_agent_class_id == "cls-autonomous"

    def test_default_fleet_policy_can_be_set(self):
        ep = make_entry_point(default_fleet_policy={"max_concurrent": 3})
        assert ep.default_fleet_policy["max_concurrent"] == 3

    def test_service_account_auth(self):
        ep = make_entry_point(
            channel=EntryChannel.WEBHOOK,
            authentication_method=AuthenticationMethod.SERVICE_ACCOUNT,
        )
        assert ep.authentication_method == AuthenticationMethod.SERVICE_ACCOUNT

    def test_no_auth_for_cron(self):
        ep = make_entry_point(
            channel=EntryChannel.CRON,
            authentication_method=AuthenticationMethod.NONE,
            audit_channel=False,
        )
        assert ep.authentication_method == AuthenticationMethod.NONE
        assert ep.audit_channel is False


# ── v0.4-rc: OperationContext + Receipt field additions ───────────────────────


class TestOperationContextV04RcFields:
    def test_active_scopes_defaults_to_empty_list(self):
        from dawn.concord.types.entities import OperationContext, Resource, BlockedReason
        from dawn.concord.types.enums import FreshnessStatus
        res = Resource(
            id="cr-1", resource_type="change_request",
            business_state={}, coordination_state={}, version=1,
            created_at=NOW, updated_at=NOW,
        )
        ctx = OperationContext(
            resource_id="cr-1", resource=res,
            allowed_actions=[], blocked_actions=[], blocked_reasons=[],
            active_leases=[], pending_intents=[],
            budget_remaining={}, freshness_status=FreshnessStatus.FRESH,
            context_assembled_at=NOW, context_ttl_ms=30000,
        )
        assert ctx.active_scopes == []

    def test_active_scopes_can_be_set(self):
        from dawn.concord.types.entities import OperationContext, Resource
        from dawn.concord.types.enums import FreshnessStatus
        res = Resource(
            id="cr-1", resource_type="change_request",
            business_state={}, coordination_state={}, version=1,
            created_at=NOW, updated_at=NOW,
        )
        ctx = OperationContext(
            resource_id="cr-1", resource=res,
            allowed_actions=[], blocked_actions=[], blocked_reasons=[],
            active_leases=[], pending_intents=[],
            budget_remaining={}, freshness_status=FreshnessStatus.FRESH,
            context_assembled_at=NOW, context_ttl_ms=30000,
            active_scopes=["scope-ci-pipeline", "scope-prod-domain"],
        )
        assert len(ctx.active_scopes) == 2
        assert "scope-ci-pipeline" in ctx.active_scopes


class TestReceiptV04RcFields:
    def test_scopes_applied_defaults_to_empty_list(self):
        r = make_receipt()
        assert r.scopes_applied == []

    def test_scopes_applied_can_be_set(self):
        r = make_receipt(scopes_applied=["scope-prod-domain"])
        assert r.scopes_applied == ["scope-prod-domain"]


# ── v0.4-rc: ScopedRule ───────────────────────────────────────────────────────


def make_rule(**kwargs) -> ScopedRule:
    defaults = dict(
        rule_id="rule-1",
        rule_type=ScopedRuleType.CONSTRAINT,
        content="All mutations to production resources require T3 trust tier.",
        applies_to=ScopedRuleAppliesTo.AGENT,
        severity=ScopedRuleSeverity.REQUIRED,
    )
    defaults.update(kwargs)
    return ScopedRule(**defaults)


class TestScopedRule:
    def test_basic_construction(self):
        r = make_rule()
        assert r.rule_id == "rule-1"
        assert r.rule_type == ScopedRuleType.CONSTRAINT
        assert r.severity == ScopedRuleSeverity.REQUIRED
        assert r.applies_to == ScopedRuleAppliesTo.AGENT

    def test_source_ref_defaults_to_none(self):
        r = make_rule()
        assert r.source_ref is None

    def test_source_ref_can_be_set(self):
        r = make_rule(source_ref="ADR-042")
        assert r.source_ref == "ADR-042"

    def test_convention_rule(self):
        r = make_rule(rule_type=ScopedRuleType.CONVENTION, severity=ScopedRuleSeverity.ADVISORY)
        assert r.rule_type == ScopedRuleType.CONVENTION
        assert r.severity == ScopedRuleSeverity.ADVISORY

    def test_applies_to_all(self):
        r = make_rule(applies_to=ScopedRuleAppliesTo.ALL)
        assert r.applies_to == ScopedRuleAppliesTo.ALL

    def test_escalation_trigger_rule(self):
        r = make_rule(rule_type=ScopedRuleType.ESCALATION_TRIGGER, severity=ScopedRuleSeverity.REQUIRED)
        assert r.rule_type == ScopedRuleType.ESCALATION_TRIGGER


# ── v0.4-rc: ContextScope ────────────────────────────────────────────────────


def make_scope(**kwargs) -> ContextScope:
    defaults = dict(
        scope_id="scope-prod-domain",
        scope_type=ScopeType.DOMAIN,
        match_pattern="production",
        priority=100,
        rules=[make_rule()],
        context_additions=["prod-runbook.md"],
        context_exclusions=[],
        active=True,
    )
    defaults.update(kwargs)
    return ContextScope(**defaults)


class TestContextScope:
    def test_basic_construction(self):
        s = make_scope()
        assert s.scope_id == "scope-prod-domain"
        assert s.scope_type == ScopeType.DOMAIN
        assert s.priority == 100
        assert s.active is True

    def test_inherits_from_defaults_to_none(self):
        s = make_scope()
        assert s.inherits_from is None

    def test_inherits_from_can_be_set(self):
        s = make_scope(inherits_from="scope-base")
        assert s.inherits_from == "scope-base"

    def test_rules_are_scoped_rule_objects(self):
        s = make_scope()
        assert isinstance(s.rules[0], ScopedRule)

    def test_multiple_rules(self):
        rules = [make_rule(rule_id=f"rule-{i}") for i in range(3)]
        s = make_scope(rules=rules)
        assert len(s.rules) == 3

    def test_path_glob_scope(self):
        s = make_scope(scope_type=ScopeType.PATH_GLOB, match_pattern="src/payments/**")
        assert s.scope_type == ScopeType.PATH_GLOB
        assert "payments" in s.match_pattern

    def test_context_additions_and_exclusions(self):
        s = make_scope(
            context_additions=["prod-runbook.md", "sla-policy.md"],
            context_exclusions=["dev-guide.md"],
        )
        assert len(s.context_additions) == 2
        assert len(s.context_exclusions) == 1

    def test_inactive_scope(self):
        s = make_scope(active=False)
        assert s.active is False

    def test_composite_scope(self):
        s = make_scope(scope_type=ScopeType.COMPOSITE, match_pattern="prod+payments")
        assert s.scope_type == ScopeType.COMPOSITE

    def test_higher_priority_wins(self):
        low = make_scope(scope_id="low", priority=10)
        high = make_scope(scope_id="high", priority=200)
        assert high.priority > low.priority


# ── v0.4-rc: ReviewBundle ────────────────────────────────────────────────────


def make_bundle(**kwargs) -> ReviewBundle:
    defaults = dict(
        bundle_id="bundle-1",
        session_id="sess-1",
        created_at=NOW,
        bundle_status=BundleStatus.PENDING_REVIEW,
        summary={"what": "Submitted CR-42 for review.", "actions_taken": 3},
        receipts=["op-1", "op-2", "op-3"],
        state_changes=[{"from": "draft", "to": "submitted", "action": "submit"}],
        resources_modified=["cr-42"],
        validation_results={"score": 0.92, "passed": True},
        risk_assessment={"highest_risk": "moderate", "cost_units": 12.5},
        artifacts={"diff_url": "https://example.com/diff/42"},
    )
    defaults.update(kwargs)
    return ReviewBundle(**defaults)


class TestReviewBundle:
    def test_basic_construction(self):
        b = make_bundle()
        assert b.bundle_id == "bundle-1"
        assert b.session_id == "sess-1"
        assert b.bundle_status == BundleStatus.PENDING_REVIEW

    def test_optional_fields_default_to_none(self):
        b = make_bundle()
        assert b.fleet_id is None
        assert b.dispatch_id is None
        assert b.diff_ref is None
        assert b.reviewer_session_id is None
        assert b.review_decision is None
        assert b.review_notes is None
        assert b.review_completed_at is None

    def test_receipts_is_list_of_operation_ids(self):
        b = make_bundle()
        assert len(b.receipts) == 3
        assert "op-1" in b.receipts

    def test_approved_bundle(self):
        b = make_bundle(
            bundle_status=BundleStatus.APPROVED,
            review_decision=BundleStatus.APPROVED,
            reviewer_session_id="sess-reviewer",
            review_notes="LGTM",
            review_completed_at=LATER,
        )
        assert b.bundle_status == BundleStatus.APPROVED
        assert b.review_decision == BundleStatus.APPROVED
        assert b.review_completed_at == LATER

    def test_rejected_bundle(self):
        b = make_bundle(
            bundle_status=BundleStatus.REJECTED,
            review_decision=BundleStatus.REJECTED,
            review_notes="Scope too broad — needs decomposition.",
        )
        assert b.bundle_status == BundleStatus.REJECTED
        assert b.review_notes is not None

    def test_revision_requested(self):
        b = make_bundle(
            bundle_status=BundleStatus.REVISION_REQUESTED,
            review_decision=BundleStatus.REVISION_REQUESTED,
        )
        assert b.bundle_status == BundleStatus.REVISION_REQUESTED

    def test_fleet_dispatch_traceability(self):
        b = make_bundle(fleet_id="fleet-1", dispatch_id="dispatch-42")
        assert b.fleet_id == "fleet-1"
        assert b.dispatch_id == "dispatch-42"

    def test_diff_ref_can_be_set(self):
        b = make_bundle(diff_ref="git://sha/abc123")
        assert b.diff_ref == "git://sha/abc123"

    def test_summary_is_domain_language(self):
        b = make_bundle(summary={"what": "Approved payment gateway config change.", "risk": "low"})
        assert "what" in b.summary

    def test_state_changes_list(self):
        b = make_bundle(state_changes=[
            {"from": "draft", "to": "submitted"},
            {"from": "submitted", "to": "under_review"},
        ])
        assert len(b.state_changes) == 2

    def test_risk_assessment_dict(self):
        b = make_bundle(risk_assessment={"highest_risk": "high", "escalations": 1})
        assert b.risk_assessment["highest_risk"] == "high"
