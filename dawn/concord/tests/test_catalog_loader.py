"""Tests for catalog_loader.py — P0-3.

Covers:
- Happy path against the real action_catalogs/change_request/ seed data
- Programmatic synthetic catalogs via tmp_path
- Error cases: YAML syntax, resource_type mismatch, Pydantic validation failure
- Empty root, action-only resource, state-only resource
- Incremental load into an existing registry
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from dawn.concord.catalog_loader import CatalogLoadError, CatalogLoader, load_catalog
from dawn.concord.contracts_kernel import ContractRegistry

# Path to the real seed catalog relative to the DAWN project root.
_REPO_ROOT = pathlib.Path(__file__).parents[3]   # DAWN/
_REAL_CATALOG = _REPO_ROOT / "action_catalogs"


# ── Minimal valid YAML fragments ──────────────────────────────────────────────

_VALID_STATE = {
    "resource_type": "widget",
    "initial_state": "new",
    "terminal_states": ["done"],
    "states": [
        {"name": "new", "is_terminal": False, "allowed_action_refs": ["activate_widget"]},
        {"name": "done", "is_terminal": True, "allowed_action_refs": []},
    ],
    "transitions": [
        {"name": "new_to_done", "from_state": "new", "to_state": "done",
         "action_ref": "activate_widget"},
    ],
    "rollback_rules": [], "entry_hooks": [], "exit_hooks": [],
}

_VALID_ACTION = {
    "action_name": "activate_widget",
    "description": "Activate a widget.",
    "resource_type": "widget",
    "action_family": "mutate",
    "input_schema_ref": "#/activate_input",
    "output_schema_ref": "#/activate_output",
    "required_capabilities": [],
    "idempotency_required": True,
    "risk_level": "low",
    "consistency_profile": "STRONG",
    "conflict_resolution_strategy": "default",
    "compensation_strategy": "none",
    "participates_in_saga": False,
}


def _write_yaml(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data))


# ── Real seed catalog ─────────────────────────────────────────────────────────


class TestRealCatalog:
    def test_catalog_root_exists(self):
        assert _REAL_CATALOG.exists(), f"action_catalogs/ not found at {_REAL_CATALOG}"

    def test_load_returns_registry(self):
        reg = load_catalog(_REAL_CATALOG)
        assert isinstance(reg, ContractRegistry)

    def test_change_request_resource_type_registered(self):
        reg = load_catalog(_REAL_CATALOG)
        assert "change_request" in reg.registered_resource_types()

    def test_all_10_actions_loaded(self):
        reg = load_catalog(_REAL_CATALOG)
        actions = reg.registered_actions("change_request")
        assert len(actions) == 10

    def test_expected_actions_present(self):
        reg = load_catalog(_REAL_CATALOG)
        actions = set(reg.registered_actions("change_request"))
        expected = {
            "read_change_request", "update_change_request", "request_edit_lease",
            "submit_change_request", "request_review_token", "withdraw_change_request",
            "approve_change_request", "reject_change_request",
            "deploy_change_request", "reopen_change_request",
        }
        assert expected == actions

    def test_state_contract_loaded(self):
        reg = load_catalog(_REAL_CATALOG)
        sc = reg.lookup_state("change_request")
        assert sc.initial_state == "draft"
        assert set(sc.terminal_states) == {"approved", "rejected"}

    def test_state_machine_has_five_states(self):
        reg = load_catalog(_REAL_CATALOG)
        sc = reg.lookup_state("change_request")
        assert len(sc.states) == 5

    def test_deploy_has_async_projection(self):
        reg = load_catalog(_REAL_CATALOG)
        ac = reg.lookup_action("change_request", "deploy_change_request")
        from dawn.concord.types.enums import ConsistencyProfile
        assert ac.consistency_profile == ConsistencyProfile.ASYNC_PROJECTION
        assert ac.projection_tolerance_ms == 5000

    def test_submit_verbatim_from_spec(self):
        """submit_change_request matches §3.4 field values exactly."""
        reg = load_catalog(_REAL_CATALOG)
        ac = reg.lookup_action("change_request", "submit_change_request")
        from dawn.concord.types.enums import (
            ActionFamily, ConsistencyProfile, RiskLevel, TrustTier, RetryClass,
        )
        assert ac.action_family == ActionFamily.MUTATE
        assert ac.consistency_profile == ConsistencyProfile.EVENTUAL
        assert ac.risk_level == RiskLevel.MODERATE
        assert ac.required_trust_tier == TrustTier.T2_BOUNDED
        assert ac.retry_class == RetryClass.RECHECK_THEN_RETRY
        assert ac.budget_cost_units == 3.0
        assert ac.participates_in_saga is True
        assert ac.authoritative_recheck_required is True

    def test_approve_requires_t3_trust(self):
        reg = load_catalog(_REAL_CATALOG)
        ac = reg.lookup_action("change_request", "approve_change_request")
        from dawn.concord.types.enums import TrustTier
        assert ac.required_trust_tier == TrustTier.T3_PRIVILEGED

    def test_deploy_requires_t4_trust(self):
        reg = load_catalog(_REAL_CATALOG)
        ac = reg.lookup_action("change_request", "deploy_change_request")
        from dawn.concord.types.enums import TrustTier
        assert ac.required_trust_tier == TrustTier.T4_GOVERNED_CRITICAL

    def test_cross_validation_passes(self):
        """ContractRegistry cross-validation found no errors during load."""
        reg = load_catalog(_REAL_CATALOG)
        for action_name in reg.registered_actions("change_request"):
            errs = reg.validate_action_against_state("change_request", action_name)
            assert errs == [], f"{action_name}: {errs}"


# ── Synthetic happy-path tests ────────────────────────────────────────────────


class TestSyntheticHappyPath:
    def test_empty_root_returns_empty_registry(self, tmp_path):
        reg = load_catalog(tmp_path)
        assert reg.registered_resource_types() == set()

    def test_returns_new_registry_by_default(self, tmp_path):
        reg = load_catalog(tmp_path)
        assert isinstance(reg, ContractRegistry)

    def test_uses_provided_registry(self, tmp_path):
        existing = ContractRegistry()
        result = load_catalog(tmp_path, registry=existing)
        assert result is existing

    def test_loads_action_without_state_contract(self, tmp_path):
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", _VALID_ACTION)
        reg = load_catalog(tmp_path)
        assert "activate_widget" in reg.registered_actions("widget")

    def test_loads_state_without_actions(self, tmp_path):
        _write_yaml(tmp_path / "widget" / "state_contract.yaml", _VALID_STATE)
        reg = load_catalog(tmp_path)
        sc = reg.lookup_state("widget")
        assert sc.initial_state == "new"

    def test_loads_state_and_action_together(self, tmp_path):
        _write_yaml(tmp_path / "widget" / "state_contract.yaml", _VALID_STATE)
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", _VALID_ACTION)
        reg = load_catalog(tmp_path)
        assert reg.lookup_action("widget", "activate_widget") is not None
        assert reg.lookup_state("widget") is not None

    def test_multiple_resource_types(self, tmp_path):
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", _VALID_ACTION)
        gadget_action = {**_VALID_ACTION, "action_name": "use_gadget", "resource_type": "gadget"}
        _write_yaml(tmp_path / "gadget" / "actions" / "use_gadget.yaml", gadget_action)
        reg = load_catalog(tmp_path)
        assert "widget" in reg.registered_resource_types()
        assert "gadget" in reg.registered_resource_types()

    def test_incremental_load_into_existing_registry(self, tmp_path):
        existing = ContractRegistry()
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", _VALID_ACTION)
        load_catalog(tmp_path, registry=existing)
        assert "widget" in existing.registered_resource_types()

    def test_non_yaml_files_in_actions_ignored(self, tmp_path):
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", _VALID_ACTION)
        (tmp_path / "widget" / "actions" / "README.txt").write_text("notes")
        (tmp_path / "widget" / "actions" / "draft.json").write_text("{}")
        reg = load_catalog(tmp_path)
        assert reg.registered_actions("widget") == ["activate_widget"]

    def test_non_directory_entries_in_root_ignored(self, tmp_path):
        (tmp_path / "not_a_dir.yaml").write_text("resource_type: stray")
        reg = load_catalog(tmp_path)
        assert reg.registered_resource_types() == set()

    def test_accepts_string_path(self, tmp_path):
        reg = load_catalog(str(tmp_path))
        assert isinstance(reg, ContractRegistry)

    def test_state_loaded_before_actions(self, tmp_path):
        """Cross-validation runs because state is registered first."""
        _write_yaml(tmp_path / "widget" / "state_contract.yaml", _VALID_STATE)
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", _VALID_ACTION)
        reg = load_catalog(tmp_path)
        errs = reg.validate_action_against_state("widget", "activate_widget")
        assert errs == []


# ── Error-case tests ──────────────────────────────────────────────────────────


class TestErrorCases:
    def test_missing_catalog_root_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_catalog("/nonexistent/path/that/does/not/exist")

    def test_yaml_syntax_error_raises_catalog_load_error(self, tmp_path):
        bad = tmp_path / "widget" / "actions" / "bad.yaml"
        bad.parent.mkdir(parents=True)
        bad.write_text("action_name: [\n  unclosed bracket")
        with pytest.raises(CatalogLoadError) as exc_info:
            load_catalog(tmp_path)
        assert bad == exc_info.value.path

    def test_non_mapping_yaml_raises_catalog_load_error(self, tmp_path):
        bad = tmp_path / "widget" / "actions" / "list.yaml"
        bad.parent.mkdir(parents=True)
        bad.write_text("- item1\n- item2\n")
        with pytest.raises(CatalogLoadError) as exc_info:
            load_catalog(tmp_path)
        assert bad == exc_info.value.path

    def test_resource_type_mismatch_in_action_raises_error(self, tmp_path):
        wrong = {**_VALID_ACTION, "resource_type": "wrong_type"}
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", wrong)
        with pytest.raises(CatalogLoadError) as exc_info:
            load_catalog(tmp_path)
        assert "mismatch" in str(exc_info.value).lower()

    def test_resource_type_mismatch_in_state_raises_error(self, tmp_path):
        wrong = {**_VALID_STATE, "resource_type": "wrong_type"}
        _write_yaml(tmp_path / "widget" / "state_contract.yaml", wrong)
        with pytest.raises(CatalogLoadError) as exc_info:
            load_catalog(tmp_path)
        assert "mismatch" in str(exc_info.value).lower()

    def test_pydantic_validation_failure_raises_catalog_load_error(self, tmp_path):
        invalid = {**_VALID_ACTION, "idempotency_required": False}  # mutate must be True
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", invalid)
        with pytest.raises(CatalogLoadError) as exc_info:
            load_catalog(tmp_path)
        assert exc_info.value.path.name == "activate_widget.yaml"

    def test_async_projection_missing_tolerance_raises_error(self, tmp_path):
        invalid = {
            **_VALID_ACTION,
            "consistency_profile": "ASYNC_PROJECTION",
            # projection_tolerance_ms intentionally omitted
        }
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", invalid)
        with pytest.raises(CatalogLoadError):
            load_catalog(tmp_path)

    def test_catalog_load_error_carries_cause(self, tmp_path):
        bad = tmp_path / "widget" / "actions" / "bad.yaml"
        bad.parent.mkdir(parents=True)
        bad.write_text(": invalid yaml :")
        with pytest.raises(CatalogLoadError) as exc_info:
            load_catalog(tmp_path)
        assert exc_info.value.cause is not None

    def test_catalog_load_error_str_includes_path(self, tmp_path):
        invalid = {**_VALID_ACTION, "idempotency_required": False}
        path = tmp_path / "widget" / "actions" / "activate_widget.yaml"
        _write_yaml(path, invalid)
        with pytest.raises(CatalogLoadError) as exc_info:
            load_catalog(tmp_path)
        assert "activate_widget.yaml" in str(exc_info.value)


# ── CatalogLoader (P0-4) tests ────────────────────────────────────────────────


class TestCatalogLoaderClass:
    def test_returns_contract_registry(self, tmp_path):
        loader = CatalogLoader(tmp_path)
        assert isinstance(loader.load(), ContractRegistry)

    def test_catalog_version_is_sha256_prefixed(self, tmp_path):
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", _VALID_ACTION)
        loader = CatalogLoader(tmp_path)
        loader.load()
        assert loader.catalog_version.startswith("sha256:")

    def test_catalog_version_is_deterministic(self, tmp_path):
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", _VALID_ACTION)
        v1 = CatalogLoader(tmp_path)
        v1.load()
        v2 = CatalogLoader(tmp_path)
        v2.load()
        assert v1.catalog_version == v2.catalog_version

    def test_catalog_version_changes_when_file_added(self, tmp_path):
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", _VALID_ACTION)
        loader = CatalogLoader(tmp_path)
        loader.load()
        version_before = loader.catalog_version

        gadget = {**_VALID_ACTION, "action_name": "use_gadget", "resource_type": "gadget"}
        _write_yaml(tmp_path / "gadget" / "actions" / "use_gadget.yaml", gadget)
        loader2 = CatalogLoader(tmp_path)
        loader2.load()
        assert loader2.catalog_version != version_before

    def test_catalog_version_changes_when_file_modified(self, tmp_path):
        path = tmp_path / "widget" / "actions" / "activate_widget.yaml"
        _write_yaml(path, _VALID_ACTION)
        loader = CatalogLoader(tmp_path)
        loader.load()
        version_before = loader.catalog_version

        modified = {**_VALID_ACTION, "description": "Modified description."}
        _write_yaml(path, modified)
        loader2 = CatalogLoader(tmp_path)
        loader2.load()
        assert loader2.catalog_version != version_before

    def test_empty_catalog_has_empty_version_hash(self, tmp_path):
        loader = CatalogLoader(tmp_path)
        loader.load()
        # SHA-256 of empty input still produces a sha256: prefixed string
        assert loader.catalog_version.startswith("sha256:")

    def test_contracts_loaded_counts_actions(self, tmp_path):
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", _VALID_ACTION)
        gadget = {**_VALID_ACTION, "action_name": "use_gadget", "resource_type": "gadget"}
        _write_yaml(tmp_path / "gadget" / "actions" / "use_gadget.yaml", gadget)
        loader = CatalogLoader(tmp_path)
        loader.load()
        assert loader.contracts_loaded == 2

    def test_failures_empty_for_valid_catalog(self, tmp_path):
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", _VALID_ACTION)
        loader = CatalogLoader(tmp_path)
        loader.load()
        assert loader.failures == []

    def test_invalid_file_recorded_in_failures_not_raised(self, tmp_path):
        """CatalogLoader is lenient: invalid files go to failures, not exceptions."""
        invalid = {**_VALID_ACTION, "idempotency_required": False}
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", invalid)
        loader = CatalogLoader(tmp_path)
        reg = loader.load()  # must NOT raise
        assert len(loader.failures) == 1
        assert loader.contracts_loaded == 0
        assert loader.failures[0]["path"].endswith("activate_widget.yaml")

    def test_partial_load_valid_files_succeed_invalid_skipped(self, tmp_path):
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", _VALID_ACTION)
        invalid = {**_VALID_ACTION, "action_name": "bad_action", "idempotency_required": False}
        _write_yaml(tmp_path / "widget" / "actions" / "bad_action.yaml", invalid)
        loader = CatalogLoader(tmp_path)
        reg = loader.load()
        assert loader.contracts_loaded == 1
        assert len(loader.failures) == 1
        assert "activate_widget" in reg.registered_actions("widget")
        assert "bad_action" not in reg.registered_actions("widget")

    def test_missing_root_raises_file_not_found(self):
        loader = CatalogLoader("/nonexistent/path")
        with pytest.raises(FileNotFoundError):
            loader.load()

    def test_real_catalog_loads_all_10_actions(self):
        loader = CatalogLoader(_REAL_CATALOG)
        reg = loader.load()
        assert loader.contracts_loaded == 10
        assert loader.failures == []
        assert loader.catalog_version.startswith("sha256:")

    def test_uses_provided_registry(self, tmp_path):
        existing = ContractRegistry()
        _write_yaml(tmp_path / "widget" / "actions" / "activate_widget.yaml", _VALID_ACTION)
        loader = CatalogLoader(tmp_path, registry=existing)
        result = loader.load()
        assert result is existing
