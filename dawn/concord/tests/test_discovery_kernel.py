"""Tests for CONCORD v0.4-beta — discovery_kernel.py.

Key scenario tested:
  "Show me an ActionDiscovery query where the requesting agent's CapabilitySet
  excludes actions that exist in the catalog. Confirm those actions don't
  appear in results."

  - CapabilitySet.allowed_action_families restricts to only read/plan
  - CapabilitySet.restricted_resource_types denies a specific resource type
  - CapabilitySet.exclusions bars specific action names by name
  - required_trust_tier on ActionContract bars agents below the required tier
  - Available actions that PASS the filter DO appear in results
  - total_available reflects pre-truncation count
  - filtered_by transparency dict documents every applied filter
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from dawn.concord.contracts_kernel import ContractRegistry
from dawn.concord.discovery_kernel import execute_discovery, is_action_permitted
from dawn.concord.types.contracts import (
    ActionContract,
    ActionDiscoveryQuery,
    ActionDiscoveryResponse,
    ActionSummary,
)
from dawn.concord.types.entities import CapabilitySet
from dawn.concord.types.enums import (
    ActionFamily,
    CompensationStrategy,
    ConflictResolutionStrategy,
    ConsistencyProfile,
    IdempotencyScope,
    RetryClass,
    RiskLevel,
    TrustTier,
)


# ── Fixture helpers ───────────────────────────────────────────────────────────


def _ac(
    action_name: str,
    resource_type: str = "change_request",
    family: ActionFamily = ActionFamily.READ,
    risk: RiskLevel = RiskLevel.LOW,
    required_trust_tier: TrustTier | None = None,
    description: str = "",
) -> ActionContract:
    return ActionContract(
        action_name=action_name,
        description=description or f"Action {action_name}",
        resource_type=resource_type,
        action_family=family,
        input_schema_ref=f"#/{action_name}_input",
        output_schema_ref=f"#/{action_name}_output",
        required_capabilities=[],
        idempotency_required=(family != ActionFamily.READ),
        risk_level=risk,
        consistency_profile=ConsistencyProfile.STRONG,
        conflict_resolution_strategy=ConflictResolutionStrategy.DEFAULT,
        compensation_strategy=CompensationStrategy.NONE,
        participates_in_saga=False,
        required_trust_tier=required_trust_tier,
    )


def _caps(
    cap_id: str = "cap-1",
    allowed_families: list[str] | None = None,
    allowed_resources: list[str] | None = None,
    restricted_resources: list[str] | None = None,
    exclusions: list[str] | None = None,
) -> CapabilitySet:
    return CapabilitySet(
        id=cap_id,
        allowed_action_families=allowed_families or [],
        allowed_resource_types=allowed_resources or [],
        restricted_resource_types=restricted_resources or [],
        exclusions=exclusions or [],
    )


def _registry(*actions: ActionContract) -> ContractRegistry:
    r = ContractRegistry()
    for ac in actions:
        r.register_action(ac)
    return r


def _query(
    session_id: str = "sess-1",
    resource_type: str | None = None,
    family: ActionFamily | None = None,
    max_results: int = 10,
    task_context: str | None = None,
) -> ActionDiscoveryQuery:
    return ActionDiscoveryQuery(
        session_id=session_id,
        resource_type=resource_type,
        action_family=family,
        max_results=max_results,
        task_context=task_context,
    )


# ── is_action_permitted ───────────────────────────────────────────────────────


class TestIsActionPermitted:
    def test_no_restrictions_permits_all(self):
        ac = _ac("read_item", family=ActionFamily.READ)
        caps = _caps()
        assert is_action_permitted(ac, caps) is True

    def test_exclusion_denies_action_by_name(self):
        ac = _ac("delete_item", family=ActionFamily.MUTATE)
        caps = _caps(exclusions=["delete_item"])
        assert is_action_permitted(ac, caps) is False

    def test_exclusion_does_not_affect_other_actions(self):
        ac = _ac("read_item", family=ActionFamily.READ)
        caps = _caps(exclusions=["delete_item"])
        assert is_action_permitted(ac, caps) is True

    def test_restricted_resource_type_denies(self):
        ac = _ac("read_item", resource_type="secret_vault")
        caps = _caps(restricted_resources=["secret_vault"])
        assert is_action_permitted(ac, caps) is False

    def test_restricted_wins_over_allowed(self):
        """deny always wins over allow."""
        ac = _ac("read_item", resource_type="secret_vault")
        caps = _caps(
            allowed_resources=["secret_vault"],
            restricted_resources=["secret_vault"],
        )
        assert is_action_permitted(ac, caps) is False

    def test_allowed_resource_type_allowlist_passes(self):
        ac = _ac("read_item", resource_type="change_request")
        caps = _caps(allowed_resources=["change_request"])
        assert is_action_permitted(ac, caps) is True

    def test_allowed_resource_type_allowlist_blocks_others(self):
        ac = _ac("read_item", resource_type="deployment")
        caps = _caps(allowed_resources=["change_request"])
        assert is_action_permitted(ac, caps) is False

    def test_allowed_action_family_passes(self):
        ac = _ac("read_item", family=ActionFamily.READ)
        caps = _caps(allowed_families=["read"])
        assert is_action_permitted(ac, caps) is True

    def test_allowed_action_family_blocks_other_families(self):
        """THE SCENARIO: CapabilitySet allows only read/plan; mutate is excluded."""
        ac = _ac("update_cr", family=ActionFamily.MUTATE)
        caps = _caps(allowed_families=["read", "plan"])
        assert is_action_permitted(ac, caps) is False

    def test_empty_allowed_families_permits_all(self):
        ac = _ac("update_cr", family=ActionFamily.MUTATE)
        caps = _caps(allowed_families=[])
        assert is_action_permitted(ac, caps) is True

    def test_required_trust_tier_met(self):
        ac = _ac("approve_cr", required_trust_tier=TrustTier.T2_BOUNDED)
        caps = _caps()
        assert is_action_permitted(ac, caps, agent_trust_tier=TrustTier.T2_BOUNDED) is True

    def test_required_trust_tier_exceeded(self):
        ac = _ac("approve_cr", required_trust_tier=TrustTier.T2_BOUNDED)
        caps = _caps()
        assert is_action_permitted(ac, caps, agent_trust_tier=TrustTier.T3_PRIVILEGED) is True

    def test_required_trust_tier_not_met(self):
        ac = _ac("deploy_cr", required_trust_tier=TrustTier.T3_PRIVILEGED)
        caps = _caps()
        assert is_action_permitted(ac, caps, agent_trust_tier=TrustTier.T1_PROPOSE) is False

    def test_required_trust_tier_no_agent_tier_denies(self):
        ac = _ac("deploy_cr", required_trust_tier=TrustTier.T1_PROPOSE)
        caps = _caps()
        assert is_action_permitted(ac, caps, agent_trust_tier=None) is False

    def test_no_required_tier_no_agent_tier_passes(self):
        ac = _ac("read_item", required_trust_tier=None)
        caps = _caps()
        assert is_action_permitted(ac, caps, agent_trust_tier=None) is True

    def test_multiple_restrictions_all_must_pass(self):
        ac = _ac("update_cr", resource_type="change_request", family=ActionFamily.MUTATE)
        caps = _caps(
            allowed_families=["read"],          # mutate not allowed
            allowed_resources=["change_request"],  # resource OK
        )
        assert is_action_permitted(ac, caps) is False


# ── execute_discovery ─────────────────────────────────────────────────────────


class TestExecuteDiscovery:
    def test_returns_discovery_response(self):
        reg = _registry(_ac("read_cr"))
        result = execute_discovery(reg, query=_query(), capability_set=_caps())
        assert isinstance(result, ActionDiscoveryResponse)

    def test_empty_registry_returns_empty(self):
        reg = ContractRegistry()
        result = execute_discovery(reg, query=_query(), capability_set=_caps())
        assert result.available_actions == []
        assert result.total_available == 0

    def test_permitted_action_appears_in_results(self):
        reg = _registry(_ac("read_cr"))
        result = execute_discovery(reg, query=_query(), capability_set=_caps())
        assert any(a.action_name == "read_cr" for a in result.available_actions)

    def test_excluded_action_absent_from_results(self):
        """Core security invariant: agent must not discover excluded actions."""
        reg = _registry(
            _ac("read_cr", family=ActionFamily.READ),
            _ac("delete_cr", family=ActionFamily.MUTATE),
        )
        caps = _caps(exclusions=["delete_cr"])
        result = execute_discovery(reg, query=_query(), capability_set=caps)
        names = {a.action_name for a in result.available_actions}
        assert "delete_cr" not in names
        assert "read_cr" in names

    def test_family_filter_in_capability_blocks_mutate(self):
        """THE SCENARIO: capability allows read/plan only; mutate actions hidden."""
        reg = _registry(
            _ac("read_cr", family=ActionFamily.READ),
            _ac("plan_cr", family=ActionFamily.PLAN),
            _ac("update_cr", family=ActionFamily.MUTATE),
            _ac("approve_cr", family=ActionFamily.APPROVE),
        )
        caps = _caps(allowed_families=["read", "plan"])
        result = execute_discovery(reg, query=_query(), capability_set=caps)
        names = {a.action_name for a in result.available_actions}
        assert names == {"read_cr", "plan_cr"}
        assert "update_cr" not in names
        assert "approve_cr" not in names

    def test_restricted_resource_type_hidden(self):
        reg = _registry(
            _ac("read_cr", resource_type="change_request"),
            _ac("read_vault", resource_type="secret_vault"),
        )
        caps = _caps(restricted_resources=["secret_vault"])
        result = execute_discovery(reg, query=_query(), capability_set=caps)
        names = {a.action_name for a in result.available_actions}
        assert "read_vault" not in names
        assert "read_cr" in names

    def test_trust_tier_filter(self):
        reg = _registry(
            _ac("read_cr", required_trust_tier=None),
            _ac("deploy_cr", family=ActionFamily.DEPLOY, required_trust_tier=TrustTier.T3_PRIVILEGED, risk=RiskLevel.CRITICAL),
        )
        caps = _caps()
        # T1 agent cannot deploy
        result = execute_discovery(
            reg, query=_query(), capability_set=caps,
            agent_trust_tier=TrustTier.T1_PROPOSE,
        )
        names = {a.action_name for a in result.available_actions}
        assert "deploy_cr" not in names
        assert "read_cr" in names

    def test_query_resource_type_filter(self):
        reg = _registry(
            _ac("read_cr", resource_type="change_request"),
            _ac("read_dep", resource_type="deployment"),
        )
        result = execute_discovery(
            reg, query=_query(resource_type="change_request"), capability_set=_caps()
        )
        names = {a.action_name for a in result.available_actions}
        assert "read_cr" in names
        assert "read_dep" not in names

    def test_query_action_family_filter(self):
        reg = _registry(
            _ac("read_cr", family=ActionFamily.READ),
            _ac("update_cr", family=ActionFamily.MUTATE),
        )
        result = execute_discovery(
            reg, query=_query(family=ActionFamily.READ), capability_set=_caps()
        )
        names = {a.action_name for a in result.available_actions}
        assert "read_cr" in names
        assert "update_cr" not in names

    def test_max_results_truncates(self):
        actions = [_ac(f"read_{i}") for i in range(5)]
        reg = _registry(*actions)
        result = execute_discovery(reg, query=_query(max_results=3), capability_set=_caps())
        assert len(result.available_actions) <= 3

    def test_total_available_reflects_pre_truncation_count(self):
        actions = [_ac(f"read_{i}") for i in range(5)]
        reg = _registry(*actions)
        result = execute_discovery(reg, query=_query(max_results=2), capability_set=_caps())
        assert result.total_available == 5
        assert len(result.available_actions) == 2

    def test_filtered_by_contains_capability_set_id(self):
        reg = _registry(_ac("read_cr"))
        caps = _caps(cap_id="caps-abc")
        result = execute_discovery(reg, query=_query(), capability_set=caps)
        assert result.filtered_by["capability_set_id"] == "caps-abc"

    def test_filtered_by_contains_session_id(self):
        reg = _registry(_ac("read_cr"))
        result = execute_discovery(reg, query=_query(session_id="sess-xyz"), capability_set=_caps())
        assert result.filtered_by["session_id"] == "sess-xyz"

    def test_catalog_version_forwarded(self):
        reg = _registry(_ac("read_cr"))
        result = execute_discovery(reg, query=_query(), capability_set=_caps(), catalog_version="v2.1")
        assert result.catalog_version == "v2.1"

    def test_action_summary_fields(self):
        ac = _ac("read_cr", family=ActionFamily.READ, risk=RiskLevel.LOW, description="Read a CR")
        reg = _registry(ac)
        result = execute_discovery(reg, query=_query(), capability_set=_caps())
        summary = result.available_actions[0]
        assert summary.action_name == "read_cr"
        assert summary.action_family == ActionFamily.READ
        assert summary.risk_level == RiskLevel.LOW
        assert summary.description == "Read a CR"

    def test_task_context_produces_recommendation(self):
        ac = _ac("read_cr", description="Read a change request for review")
        reg = _registry(ac)
        result = execute_discovery(
            reg, query=_query(task_context="change request"), capability_set=_caps()
        )
        assert result.recommendation is not None
        assert result.recommendation.action_name == "read_cr"
        assert 0 < result.recommendation.confidence <= 1.0

    def test_no_task_context_no_recommendation(self):
        ac = _ac("read_cr")
        reg = _registry(ac)
        result = execute_discovery(reg, query=_query(task_context=None), capability_set=_caps())
        assert result.recommendation is None

    def test_all_filtered_out_empty_response(self):
        """ForgeWorks scenario: all catalog actions excluded by capability set."""
        reg = _registry(
            _ac("deploy_high_risk", family=ActionFamily.DEPLOY, risk=RiskLevel.CRITICAL),
            _ac("admin_action", family=ActionFamily.ADMIN, risk=RiskLevel.CRITICAL),
        )
        caps = _caps(allowed_families=["read"])  # only read allowed; none match
        result = execute_discovery(reg, query=_query(), capability_set=caps)
        assert result.available_actions == []
        assert result.total_available == 0

    def test_multiple_resource_types_when_no_filter(self):
        reg = _registry(
            _ac("read_cr", resource_type="change_request"),
            _ac("read_dep", resource_type="deployment"),
        )
        result = execute_discovery(reg, query=_query(), capability_set=_caps())
        names = {a.action_name for a in result.available_actions}
        assert names == {"read_cr", "read_dep"}

    def test_advisory_response_has_no_authoritative_flag(self):
        """Discovery response is advisory — it carries no authoritative_for_mutation field."""
        reg = _registry(_ac("read_cr"))
        result = execute_discovery(reg, query=_query(), capability_set=_caps())
        assert not hasattr(result, "authoritative_for_mutation")
