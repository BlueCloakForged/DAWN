"""Tests for CONCORD v0.4-beta contract shapes: ActionDiscovery + AdmissionAdapter.

Covers:
- ActionSummary construction and fields
- ActionDiscoveryQuery defaults and optional filters
- ActionDiscoveryResponse structure and advisory semantics
- ActionDiscoveryRecommendation optional field
- AdmissionAdapter construction and output_kind constraint
"""

import pytest

from dawn.concord.types.contracts import (
    ActionDiscoveryQuery,
    ActionDiscoveryRecommendation,
    ActionDiscoveryResponse,
    ActionSummary,
    AdmissionAdapter,
)
from dawn.concord.types.enums import ActionFamily, RiskLevel


# ── Helpers ───────────────────────────────────────────────────────────────────


def make_summary(**kwargs) -> ActionSummary:
    defaults = dict(
        action_name="submit_change_request",
        resource_type="change_request",
        action_family=ActionFamily.MUTATE,
        risk_level=RiskLevel.MODERATE,
        description="Submits a draft change request for review.",
        guard_summary="requires state=draft; session trust >= T2",
    )
    defaults.update(kwargs)
    return ActionSummary(**defaults)


def make_query(**kwargs) -> ActionDiscoveryQuery:
    defaults = dict(session_id="sess-1")
    defaults.update(kwargs)
    return ActionDiscoveryQuery(**defaults)


def make_response(**kwargs) -> ActionDiscoveryResponse:
    defaults = dict(
        available_actions=[make_summary()],
        filtered_by={"session_id": "sess-1"},
        total_available=1,
        catalog_version="v1.0.0",
    )
    defaults.update(kwargs)
    return ActionDiscoveryResponse(**defaults)


def make_adapter(**kwargs) -> AdmissionAdapter:
    defaults = dict(
        adapter_id="adapter-cli-v1",
        entry_point_id="ep-1",
        output_kind="intent",
    )
    defaults.update(kwargs)
    return AdmissionAdapter(**defaults)


# ── ActionSummary ─────────────────────────────────────────────────────────────


class TestActionSummary:
    def test_basic_construction(self):
        s = make_summary()
        assert s.action_name == "submit_change_request"
        assert s.action_family == ActionFamily.MUTATE
        assert s.risk_level == RiskLevel.MODERATE

    def test_guard_summary_is_string(self):
        s = make_summary(guard_summary="no guards")
        assert isinstance(s.guard_summary, str)

    def test_read_action(self):
        s = make_summary(action_name="get_change_request", action_family=ActionFamily.READ,
                         risk_level=RiskLevel.LOW)
        assert s.action_family == ActionFamily.READ
        assert s.risk_level == RiskLevel.LOW

    def test_deploy_action(self):
        s = make_summary(action_name="deploy_change_request", action_family=ActionFamily.DEPLOY,
                         risk_level=RiskLevel.CRITICAL)
        assert s.action_family == ActionFamily.DEPLOY


# ── ActionDiscoveryQuery ──────────────────────────────────────────────────────


class TestActionDiscoveryQuery:
    def test_only_session_id_required(self):
        q = make_query()
        assert q.session_id == "sess-1"

    def test_defaults(self):
        q = make_query()
        assert q.max_results == 10
        assert q.include_schemas is False
        assert q.resource_type is None
        assert q.action_family is None
        assert q.task_context is None

    def test_filtered_by_resource_type(self):
        q = make_query(resource_type="change_request")
        assert q.resource_type == "change_request"

    def test_filtered_by_action_family(self):
        q = make_query(action_family=ActionFamily.MUTATE)
        assert q.action_family == ActionFamily.MUTATE

    def test_task_context_for_semantic_search(self):
        q = make_query(task_context="fix authentication bug in login service")
        assert q.task_context is not None
        assert "authentication" in q.task_context

    def test_include_schemas_true(self):
        q = make_query(include_schemas=True)
        assert q.include_schemas is True

    def test_max_results_custom(self):
        q = make_query(max_results=5)
        assert q.max_results == 5


# ── ActionDiscoveryResponse ───────────────────────────────────────────────────


class TestActionDiscoveryResponse:
    def test_basic_construction(self):
        r = make_response()
        assert len(r.available_actions) == 1
        assert r.total_available == 1
        assert r.catalog_version == "v1.0.0"

    def test_available_actions_are_summaries(self):
        r = make_response()
        assert isinstance(r.available_actions[0], ActionSummary)

    def test_recommendation_defaults_to_none(self):
        # Normative: discovery is advisory — recommendation is optional
        r = make_response()
        assert r.recommendation is None

    def test_recommendation_can_be_set(self):
        rec = ActionDiscoveryRecommendation(
            action_name="submit_change_request",
            rationale="Matches task context and current resource state.",
            confidence=0.87,
        )
        r = make_response(recommendation=rec)
        assert r.recommendation is not None
        assert r.recommendation.confidence == 0.87

    def test_filtered_by_is_dict(self):
        r = make_response(filtered_by={"action_family": "mutate", "resource_type": "change_request"})
        assert r.filtered_by["action_family"] == "mutate"

    def test_total_available_can_exceed_returned(self):
        # total_available reflects full count before max_results truncation
        r = make_response(
            available_actions=[make_summary()],
            total_available=47,
        )
        assert r.total_available == 47
        assert len(r.available_actions) == 1

    def test_empty_result_is_valid(self):
        r = make_response(available_actions=[], total_available=0)
        assert r.available_actions == []
        assert r.total_available == 0


# ── ActionDiscoveryRecommendation ─────────────────────────────────────────────


class TestActionDiscoveryRecommendation:
    def test_basic_construction(self):
        rec = ActionDiscoveryRecommendation(
            action_name="approve_change_request",
            rationale="High confidence match based on current state=under_review.",
            confidence=0.95,
        )
        assert rec.action_name == "approve_change_request"
        assert rec.confidence == 0.95

    def test_low_confidence(self):
        rec = ActionDiscoveryRecommendation(
            action_name="update_change_request",
            rationale="Weak signal — task_context is vague.",
            confidence=0.3,
        )
        assert rec.confidence < 0.5


# ── AdmissionAdapter ─────────────────────────────────────────────────────────


class TestAdmissionAdapter:
    def test_intent_output_kind(self):
        a = make_adapter(output_kind="intent")
        assert a.output_kind == "intent"

    def test_dispatch_request_output_kind(self):
        a = make_adapter(output_kind="dispatch_request")
        assert a.output_kind == "dispatch_request"

    def test_default_enrichments_starts_empty(self):
        a = make_adapter()
        assert a.default_enrichments == {}

    def test_enrichments_can_be_set(self):
        a = make_adapter(default_enrichments={"priority": "normal", "max_attempts": 3})
        assert a.default_enrichments["priority"] == "normal"

    def test_agent_class_override_defaults_to_none(self):
        a = make_adapter()
        assert a.agent_class_override is None

    def test_agent_class_override_can_be_set(self):
        a = make_adapter(agent_class_override="cls-supervised")
        assert a.agent_class_override == "cls-supervised"

    def test_entry_point_id_is_set(self):
        a = make_adapter(entry_point_id="ep-slack-01")
        assert a.entry_point_id == "ep-slack-01"

    def test_adapter_id_is_set(self):
        a = make_adapter(adapter_id="adapter-slack-v2")
        assert a.adapter_id == "adapter-slack-v2"
