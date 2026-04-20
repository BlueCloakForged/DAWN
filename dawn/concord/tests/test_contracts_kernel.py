"""Tests for CONCORD Phase 1 — contracts_kernel.py.

Covers:
- load_action_contract(): valid round-trip, sub-object conversion, normative rejections
- load_state_contract(): valid round-trip, state reference validation rejections
- ContractRegistry: register/lookup, KeyError on miss, state-machine queries,
  cross-contract validation (allowed_from_states, transitions_to_state),
  re-validation when StateContract registered after ActionContracts,
  introspection helpers, default_registry export

Fixtures use the canonical change_request worked example from spec §8.
"""

import pytest
from pydantic import ValidationError

from dawn.concord.contracts_kernel import (
    ContractRegistry,
    default_registry,
    load_action_contract,
    load_state_contract,
)
from dawn.concord.types.contracts import ActionContract, StateContract


# ── Canonical fixture data (change_request worked example) ────────────────────

UPDATE_ACTION = {
    "action_name": "update",
    "description": "Update draft change request fields.",
    "resource_type": "change_request",
    "action_family": "mutate",
    "input_schema_ref": "schemas/change_request/update_input.json",
    "output_schema_ref": "schemas/change_request/update_output.json",
    "required_capabilities": ["change_request:write"],
    "idempotency_required": True,
    "risk_level": "low",
    "consistency_profile": "STRONG",
    "conflict_resolution_strategy": "default",
    "compensation_strategy": "inverse_action",
    "participates_in_saga": False,
    "allowed_from_states": ["draft"],
    "transitions_to_state": "draft",
    "budget_cost_units": 1.0,
}

SUBMIT_ACTION = {
    "action_name": "submit",
    "description": "Submit change request for review.",
    "resource_type": "change_request",
    "action_family": "mutate",
    "input_schema_ref": "schemas/change_request/submit_input.json",
    "output_schema_ref": "schemas/change_request/submit_output.json",
    "required_capabilities": ["change_request:write"],
    "idempotency_required": True,
    "risk_level": "moderate",
    "consistency_profile": "EVENTUAL",
    "conflict_resolution_strategy": "default",
    "compensation_strategy": "inverse_action",
    "participates_in_saga": False,
    "allowed_from_states": ["draft"],
    "transitions_to_state": "submitted",
    "authoritative_recheck_required": True,
}

APPROVE_ACTION = {
    "action_name": "approve",
    "description": "Approve submitted change request.",
    "resource_type": "change_request",
    "action_family": "approve",
    "input_schema_ref": "schemas/change_request/approve_input.json",
    "output_schema_ref": "schemas/change_request/approve_output.json",
    "required_capabilities": ["change_request:approve"],
    "idempotency_required": True,
    "risk_level": "high",
    "consistency_profile": "READ_YOUR_WRITES",
    "conflict_resolution_strategy": "default",
    "compensation_strategy": "saga_handler",
    "participates_in_saga": True,
    "allowed_from_states": ["under_review"],
    "transitions_to_state": "approved",
}

DEPLOY_ACTION = {
    "action_name": "deploy",
    "description": "Deploy approved change request.",
    "resource_type": "change_request",
    "action_family": "deploy",
    "input_schema_ref": "schemas/change_request/deploy_input.json",
    "output_schema_ref": "schemas/change_request/deploy_output.json",
    "required_capabilities": ["change_request:deploy"],
    "idempotency_required": True,
    "risk_level": "critical",
    "consistency_profile": "ASYNC_PROJECTION",
    "projection_tolerance_ms": 5000,
    "conflict_resolution_strategy": "default",
    "compensation_strategy": "saga_handler",
    "participates_in_saga": True,
    "allowed_from_states": ["approved"],
    "transitions_to_state": "approved",  # deploy doesn't change business state
}

CHANGE_REQUEST_STATE_CONTRACT = {
    "resource_type": "change_request",
    "initial_state": "draft",
    "terminal_states": ["approved", "rejected"],
    "states": [
        {"name": "draft", "description": "Work in progress."},
        {"name": "submitted", "description": "Awaiting review."},
        {"name": "under_review", "description": "Reviewer assigned."},
        {"name": "approved", "description": "Approved for deployment.", "is_terminal": True,
         "allowed_action_refs": ["deploy"]},
        {"name": "rejected", "description": "Rejected by reviewer.", "is_terminal": True},
    ],
    "transitions": [
        {"name": "update_draft", "from_state": "draft", "to_state": "draft", "action_ref": "update"},
        {"name": "submit_for_review", "from_state": "draft", "to_state": "submitted", "action_ref": "submit"},
        {"name": "begin_review", "from_state": "submitted", "to_state": "under_review", "action_ref": "review"},
        {"name": "approve_cr", "from_state": "under_review", "to_state": "approved", "action_ref": "approve"},
        {"name": "reject_cr", "from_state": "under_review", "to_state": "rejected", "action_ref": "reject"},
        {"name": "deploy_cr", "from_state": "approved", "to_state": "approved", "action_ref": "deploy"},
    ],
}


# ── load_action_contract ───────────────────────────────────────────────────────


class TestLoadActionContract:
    def test_returns_action_contract_instance(self):
        ac = load_action_contract(UPDATE_ACTION)
        assert isinstance(ac, ActionContract)

    def test_core_fields_round_trip(self):
        ac = load_action_contract(UPDATE_ACTION)
        assert ac.action_name == "update"
        assert ac.resource_type == "change_request"
        assert ac.risk_level.value == "low"
        assert ac.consistency_profile.value == "STRONG"

    def test_defaults_applied(self):
        ac = load_action_contract(UPDATE_ACTION)
        assert ac.idempotency_scope.value == "session"
        assert ac.retry_class.value == "none"
        assert ac.budget_cost_units == 1.0
        assert ac.guard_predicates == []
        assert ac.side_effects == []

    def test_optional_allowed_from_states(self):
        ac = load_action_contract(UPDATE_ACTION)
        assert ac.allowed_from_states == ["draft"]

    def test_transitions_to_state(self):
        ac = load_action_contract(SUBMIT_ACTION)
        assert ac.transitions_to_state == "submitted"

    def test_authoritative_recheck_preserved(self):
        ac = load_action_contract(SUBMIT_ACTION)
        assert ac.authoritative_recheck_required is True

    def test_async_projection_with_tolerance(self):
        ac = load_action_contract(DEPLOY_ACTION)
        assert ac.consistency_profile.value == "ASYNC_PROJECTION"
        assert ac.projection_tolerance_ms == 5000

    def test_saga_with_handler_strategy(self):
        ac = load_action_contract(APPROVE_ACTION)
        assert ac.participates_in_saga is True
        assert ac.compensation_strategy.value == "saga_handler"

    def test_guard_predicates_conversion(self):
        data = dict(UPDATE_ACTION, guard_predicates=[
            {"name": "is_draft_owner", "guard_type": "permission",
             "parameters": {"role": "owner"}, "evaluation_order": 1},
        ])
        ac = load_action_contract(data)
        assert len(ac.guard_predicates) == 1
        assert ac.guard_predicates[0].name == "is_draft_owner"
        assert ac.guard_predicates[0].guard_type == "permission"
        assert ac.guard_predicates[0].parameters == {"role": "owner"}
        assert ac.guard_predicates[0].evaluation_order == 1

    def test_side_effects_conversion(self):
        data = dict(UPDATE_ACTION, side_effects=[
            {"effect_type": "event_emit", "reversible": True,
             "description": "Emits change.updated event.",
             "target_system": "event_bus"},
        ])
        ac = load_action_contract(data)
        assert len(ac.side_effects) == 1
        assert ac.side_effects[0].effect_type == "event_emit"
        assert ac.side_effects[0].reversible is True
        assert ac.side_effects[0].target_system == "event_bus"

    def test_rejects_mutating_without_idempotency(self):
        bad = dict(UPDATE_ACTION, idempotency_required=False)
        with pytest.raises(ValidationError, match="idempotency_required"):
            load_action_contract(bad)

    def test_rejects_saga_with_none_compensation(self):
        bad = dict(APPROVE_ACTION, compensation_strategy="none")
        with pytest.raises(ValidationError, match="compensation_strategy"):
            load_action_contract(bad)

    def test_rejects_async_projection_without_tolerance(self):
        bad = {k: v for k, v in DEPLOY_ACTION.items() if k != "projection_tolerance_ms"}
        with pytest.raises(ValidationError, match="projection_tolerance_ms"):
            load_action_contract(bad)

    def test_rejects_missing_required_field(self):
        bad = {k: v for k, v in UPDATE_ACTION.items() if k != "action_name"}
        with pytest.raises(ValidationError):
            load_action_contract(bad)

    def test_rejects_invalid_action_family(self):
        bad = dict(UPDATE_ACTION, action_family="teleport")
        with pytest.raises(ValidationError):
            load_action_contract(bad)

    def test_budget_cost_units_must_be_positive(self):
        bad = dict(UPDATE_ACTION, budget_cost_units=0.0)
        with pytest.raises(ValidationError):
            load_action_contract(bad)


# ── load_state_contract ────────────────────────────────────────────────────────


class TestLoadStateContract:
    def test_returns_state_contract_instance(self):
        sc = load_state_contract(CHANGE_REQUEST_STATE_CONTRACT)
        assert isinstance(sc, StateContract)

    def test_core_fields_round_trip(self):
        sc = load_state_contract(CHANGE_REQUEST_STATE_CONTRACT)
        assert sc.resource_type == "change_request"
        assert sc.initial_state == "draft"
        assert set(sc.terminal_states) == {"approved", "rejected"}

    def test_states_converted(self):
        sc = load_state_contract(CHANGE_REQUEST_STATE_CONTRACT)
        names = {s.name for s in sc.states}
        assert names == {"draft", "submitted", "under_review", "approved", "rejected"}

    def test_terminal_states_marked(self):
        sc = load_state_contract(CHANGE_REQUEST_STATE_CONTRACT)
        terminal = {s.name for s in sc.states if s.is_terminal}
        assert terminal == {"approved", "rejected"}

    def test_transitions_converted(self):
        sc = load_state_contract(CHANGE_REQUEST_STATE_CONTRACT)
        assert len(sc.transitions) == 6
        names = {t.name for t in sc.transitions}
        assert "approve_cr" in names

    def test_transition_states_preserved(self):
        sc = load_state_contract(CHANGE_REQUEST_STATE_CONTRACT)
        t = next(t for t in sc.transitions if t.name == "submit_for_review")
        assert t.from_state == "draft"
        assert t.to_state == "submitted"
        assert t.action_ref == "submit"

    def test_rejects_undeclared_initial_state(self):
        bad = dict(CHANGE_REQUEST_STATE_CONTRACT, initial_state="nonexistent")
        with pytest.raises(ValidationError, match="initial_state"):
            load_state_contract(bad)

    def test_rejects_undeclared_terminal_state(self):
        bad = dict(CHANGE_REQUEST_STATE_CONTRACT, terminal_states=["approved", "ghost"])
        with pytest.raises(ValidationError, match="terminal_state"):
            load_state_contract(bad)

    def test_rejects_transition_from_undeclared_state(self):
        bad_transitions = list(CHANGE_REQUEST_STATE_CONTRACT["transitions"]) + [
            {"name": "bad_edge", "from_state": "limbo", "to_state": "draft", "action_ref": "update"},
        ]
        bad = dict(CHANGE_REQUEST_STATE_CONTRACT, transitions=bad_transitions)
        with pytest.raises(ValidationError, match="from_state"):
            load_state_contract(bad)

    def test_rejects_transition_to_undeclared_state(self):
        bad_transitions = list(CHANGE_REQUEST_STATE_CONTRACT["transitions"]) + [
            {"name": "bad_edge", "from_state": "draft", "to_state": "void", "action_ref": "update"},
        ]
        bad = dict(CHANGE_REQUEST_STATE_CONTRACT, transitions=bad_transitions)
        with pytest.raises(ValidationError, match="to_state"):
            load_state_contract(bad)

    def test_rejects_missing_resource_type(self):
        bad = {k: v for k, v in CHANGE_REQUEST_STATE_CONTRACT.items() if k != "resource_type"}
        with pytest.raises(ValidationError):
            load_state_contract(bad)


# ── ContractRegistry ───────────────────────────────────────────────────────────


@pytest.fixture
def registry():
    return ContractRegistry()


@pytest.fixture
def update_ac():
    return load_action_contract(UPDATE_ACTION)


@pytest.fixture
def submit_ac():
    return load_action_contract(SUBMIT_ACTION)


@pytest.fixture
def approve_ac():
    return load_action_contract(APPROVE_ACTION)


@pytest.fixture
def deploy_ac():
    return load_action_contract(DEPLOY_ACTION)


@pytest.fixture
def cr_sc():
    return load_state_contract(CHANGE_REQUEST_STATE_CONTRACT)


class TestContractRegistryBasic:
    def test_register_and_lookup_action(self, registry, update_ac):
        registry.register_action(update_ac)
        result = registry.lookup_action("change_request", "update")
        assert result is update_ac

    def test_register_and_lookup_state(self, registry, cr_sc):
        registry.register_state(cr_sc)
        result = registry.lookup_state("change_request")
        assert result is cr_sc

    def test_lookup_action_missing_raises_key_error(self, registry):
        with pytest.raises(KeyError, match="change_request"):
            registry.lookup_action("change_request", "update")

    def test_lookup_state_missing_raises_key_error(self, registry):
        with pytest.raises(KeyError, match="change_request"):
            registry.lookup_state("change_request")

    def test_lookup_action_wrong_action_name(self, registry, update_ac):
        registry.register_action(update_ac)
        with pytest.raises(KeyError, match="nonexistent"):
            registry.lookup_action("change_request", "nonexistent")

    def test_overwrite_action_registration(self, registry, update_ac):
        registry.register_action(update_ac)
        # Re-registering same contract is allowed (overwrites)
        registry.register_action(update_ac)
        assert registry.lookup_action("change_request", "update") is update_ac

    def test_multiple_actions_same_resource(self, registry, update_ac, submit_ac, approve_ac):
        registry.register_action(update_ac)
        registry.register_action(submit_ac)
        registry.register_action(approve_ac)
        assert registry.lookup_action("change_request", "update") is update_ac
        assert registry.lookup_action("change_request", "submit") is submit_ac
        assert registry.lookup_action("change_request", "approve") is approve_ac


class TestContractRegistryIntrospection:
    def test_registered_resource_types_empty(self, registry):
        assert registry.registered_resource_types() == set()

    def test_registered_resource_types_from_action(self, registry, update_ac):
        registry.register_action(update_ac)
        assert "change_request" in registry.registered_resource_types()

    def test_registered_resource_types_from_state(self, registry, cr_sc):
        registry.register_state(cr_sc)
        assert "change_request" in registry.registered_resource_types()

    def test_registered_resource_types_union(self, registry, update_ac, cr_sc):
        registry.register_action(update_ac)
        registry.register_state(cr_sc)
        assert registry.registered_resource_types() == {"change_request"}

    def test_registered_actions_empty(self, registry):
        assert registry.registered_actions("change_request") == []

    def test_registered_actions_sorted(self, registry, update_ac, submit_ac, approve_ac):
        registry.register_action(approve_ac)
        registry.register_action(update_ac)
        registry.register_action(submit_ac)
        assert registry.registered_actions("change_request") == ["approve", "submit", "update"]

    def test_registered_actions_other_resource_not_included(self, registry, update_ac):
        registry.register_action(update_ac)
        assert registry.registered_actions("other_resource") == []


class TestContractRegistryStateMachineQueries:
    def test_is_action_allowed_from_state_true(self, registry, update_ac, cr_sc):
        registry.register_action(update_ac)
        registry.register_state(cr_sc)
        assert registry.is_action_allowed_from_state("change_request", "update", "draft") is True

    def test_is_action_allowed_from_state_false_wrong_state(self, registry, update_ac, cr_sc):
        registry.register_action(update_ac)
        registry.register_state(cr_sc)
        assert registry.is_action_allowed_from_state("change_request", "update", "approved") is False

    def test_is_action_allowed_from_state_no_state_contract(self, registry, update_ac):
        registry.register_action(update_ac)
        # No StateContract registered → returns False (not raises)
        assert registry.is_action_allowed_from_state("change_request", "update", "draft") is False

    def test_is_action_allowed_approve_from_under_review(self, registry, approve_ac, cr_sc):
        registry.register_action(approve_ac)
        registry.register_state(cr_sc)
        assert registry.is_action_allowed_from_state("change_request", "approve", "under_review") is True

    def test_is_action_allowed_approve_from_draft_is_false(self, registry, approve_ac, cr_sc):
        registry.register_action(approve_ac)
        registry.register_state(cr_sc)
        assert registry.is_action_allowed_from_state("change_request", "approve", "draft") is False

    def test_get_allowed_actions_for_state_draft(
        self, registry, update_ac, submit_ac, approve_ac, cr_sc
    ):
        registry.register_action(update_ac)
        registry.register_action(submit_ac)
        registry.register_action(approve_ac)
        registry.register_state(cr_sc)
        allowed = registry.get_allowed_actions_for_state("change_request", "draft")
        assert set(allowed) == {"update", "submit"}

    def test_get_allowed_actions_for_state_under_review(
        self, registry, approve_ac, cr_sc
    ):
        registry.register_action(approve_ac)
        registry.register_state(cr_sc)
        allowed = registry.get_allowed_actions_for_state("change_request", "under_review")
        assert allowed == ["approve"]

    def test_get_allowed_actions_for_terminal_state_empty(self, registry, cr_sc):
        registry.register_state(cr_sc)
        # No ActionContracts registered for "rejected" transitions
        allowed = registry.get_allowed_actions_for_state("change_request", "rejected")
        assert allowed == []

    def test_get_allowed_actions_no_state_contract_raises(self, registry):
        with pytest.raises(KeyError):
            registry.get_allowed_actions_for_state("change_request", "draft")


class TestCrossContractValidation:
    def test_valid_action_registers_cleanly(self, registry, update_ac, cr_sc):
        registry.register_state(cr_sc)
        # Should not raise
        registry.register_action(update_ac)

    def test_invalid_allowed_from_state_raises_on_action_register(self, registry, cr_sc):
        registry.register_state(cr_sc)
        bad_data = dict(UPDATE_ACTION, allowed_from_states=["nonexistent_state"])
        bad_ac = load_action_contract(bad_data)
        with pytest.raises(ValueError, match="nonexistent_state"):
            registry.register_action(bad_ac)

    def test_invalid_transitions_to_state_raises_on_action_register(self, registry, cr_sc):
        registry.register_state(cr_sc)
        bad_data = dict(UPDATE_ACTION, transitions_to_state="ghost_state")
        bad_ac = load_action_contract(bad_data)
        with pytest.raises(ValueError, match="ghost_state"):
            registry.register_action(bad_ac)

    def test_invalid_action_already_registered_raises_on_state_register(self, registry):
        # Register action with bad state ref first (no state contract yet — passes)
        bad_data = dict(UPDATE_ACTION, allowed_from_states=["phantom"])
        bad_ac = load_action_contract(bad_data)
        registry.register_action(bad_ac)
        # Now register state — should detect the inconsistency
        cr_sc = load_state_contract(CHANGE_REQUEST_STATE_CONTRACT)
        with pytest.raises(ValueError, match="phantom"):
            registry.register_state(cr_sc)

    def test_validate_action_against_state_valid(self, registry, update_ac, cr_sc):
        registry.register_action(update_ac)
        registry.register_state(cr_sc)
        assert registry.validate_action_against_state("change_request", "update") == []

    def test_validate_action_against_state_no_state_contract_returns_empty(
        self, registry, update_ac
    ):
        registry.register_action(update_ac)
        assert registry.validate_action_against_state("change_request", "update") == []

    def test_validate_action_against_state_unregistered_action_returns_empty(
        self, registry, cr_sc
    ):
        registry.register_state(cr_sc)
        assert registry.validate_action_against_state("change_request", "update") == []

    def test_no_cross_validation_without_state_contract(self, registry):
        # Action with bad state ref but no StateContract → registers without error
        bad_data = dict(UPDATE_ACTION, allowed_from_states=["does_not_exist"])
        bad_ac = load_action_contract(bad_data)
        registry.register_action(bad_ac)  # should not raise
        assert registry.registered_actions("change_request") == ["update"]


class TestDefaultRegistry:
    def test_default_registry_is_contract_registry_instance(self):
        assert isinstance(default_registry, ContractRegistry)

    def test_default_registry_is_module_level_singleton(self):
        from dawn.concord.contracts_kernel import default_registry as dr2
        assert default_registry is dr2
