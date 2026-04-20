"""Tests for CONCORD v0.3/v0.4 error/conflict code registry.

Covers:
- All 26 v0.3 codes + PL-09 RETRY_RECOMMENDED + 6 v0.4-alpha + 2 v0.4-beta + 3 v0.4-rc codes (38 total)
- All 7 metadata fields non-null for every code
- Severity vocabulary: informational | warning | elevated | critical
- Specific values from spec metadata examples table (§4)
- v0.4-alpha/beta/rc code metadata spot-checks
- get_error() helper by enum and string
"""

import pytest

from dawn.concord.types.errors import ERROR_REGISTRY, ErrorCode, ErrorMetadata, get_error

CONFLICT_CODES = {
    "STALE_VERSION",
    "SESSION_STALE_VIEW",
    "LEASE_HELD",
    "QUEUE_REQUIRED",
    "QUEUE_AVAILABLE",
    "DUPLICATE_INTENT",
    "POLICY_BLOCKED",
    "BUDGET_EXCEEDED",
    "CIRCUIT_OPEN",
    "QUORUM_INCOMPLETE",
    "DEPENDENCY_PENDING",
    "CAPACITY_EXHAUSTED",
    "NEGOTIATION_AVAILABLE",
    "NEGOTIATION_REQUIRED",
    "ESCALATION_REQUIRED",
    "AUTHORITATIVE_RECHECK_REQUIRED",
    "RETRY_RECOMMENDED",
}

ERROR_CODES = {
    "MISSING_REQUIRED_FIELD",
    "INVALID_FIELD_VALUE",
    "READ_FRESHNESS_UNAVAILABLE",
    "STALE_READ_WARNING",
    "RESOURCE_LOCKED",
    "NOT_AUTHORIZED_FOR_AGENT_CLASS",
    "OVERRIDE_DENIED",
    "SAGA_TIMED_OUT",
    "SAGA_POISONED",
    "COMPENSATION_FAILED",
}

V04_ALPHA_CODES = {
    "ENVIRONMENT_UNAVAILABLE",
    "ENVIRONMENT_UNHEALTHY",
    "FLEET_BUDGET_EXCEEDED",
    "FLEET_CONCURRENCY_LIMIT",
    "FLEET_TIMEOUT",
    "DISPATCH_UNASSIGNABLE",
}

V04_BETA_CODES = {
    "ACTION_NOT_DISCOVERABLE",
    "ENTRY_VALIDATION_FAILED",
}

V04_RC_CODES = {
    "SCOPE_CONFLICT",
    "REVIEW_REQUIRED",
    "REVIEW_REJECTED",
}

V04_CODES = V04_ALPHA_CODES | V04_BETA_CODES | V04_RC_CODES

ALL_CODES = CONFLICT_CODES | ERROR_CODES | V04_CODES

VALID_SEVERITIES = {"informational", "warning", "elevated", "critical"}


class TestErrorCodeEnum:
    def test_exactly_38_codes(self):
        assert len(ErrorCode) == 38

    def test_all_conflict_codes_present(self):
        names = {c.name for c in ErrorCode}
        assert CONFLICT_CODES.issubset(names)

    def test_all_error_codes_present(self):
        names = {c.name for c in ErrorCode}
        assert ERROR_CODES.issubset(names)

    def test_all_v04_codes_present(self):
        names = {c.name for c in ErrorCode}
        assert V04_CODES.issubset(names)

    def test_code_is_str_enum(self):
        assert ErrorCode.STALE_VERSION == "STALE_VERSION"


class TestErrorRegistry:
    def test_registry_has_38_entries(self):
        assert len(ERROR_REGISTRY) == 38

    def test_all_38_codes_in_registry(self):
        registry_names = {code.name for code in ERROR_REGISTRY}
        assert registry_names == ALL_CODES

    @pytest.mark.parametrize("code_name", sorted(ALL_CODES))
    def test_all_metadata_fields_non_null(self, code_name: str):
        meta = ERROR_REGISTRY[ErrorCode(code_name)]
        assert meta.severity is not None
        assert meta.retryable is not None
        assert meta.agent_should is not None and meta.agent_should != ""
        assert meta.human_likely_needed is not None
        assert meta.blocks_other_actions is not None
        assert meta.requires_context_refresh is not None

    @pytest.mark.parametrize("code_name", sorted(ALL_CODES))
    def test_severity_uses_spec_vocabulary(self, code_name: str):
        meta = ERROR_REGISTRY[ErrorCode(code_name)]
        assert meta.severity in VALID_SEVERITIES, (
            f"{code_name}: severity '{meta.severity}' not in {VALID_SEVERITIES}"
        )

    @pytest.mark.parametrize("code_name", sorted(ALL_CODES))
    def test_retry_delay_consistent_with_retryable(self, code_name: str):
        meta = ERROR_REGISTRY[ErrorCode(code_name)]
        if not meta.retryable:
            assert meta.retry_delay_hint_ms is None, (
                f"{code_name}: non-retryable code should have retry_delay_hint_ms=None"
            )
        else:
            assert meta.retry_delay_hint_ms is not None, (
                f"{code_name}: retryable code should have a retry_delay_hint_ms"
            )


class TestSpecMetadataExamples:
    """Validates the exact values from the spec's §4 metadata examples table.

    Spec table rows: STALE_VERSION, LEASE_HELD, BUDGET_EXCEEDED, POLICY_BLOCKED, SAGA_POISONED.
    """

    def test_stale_version_retryable(self):
        assert get_error("STALE_VERSION").retryable is True

    def test_stale_version_retry_delay(self):
        assert get_error("STALE_VERSION").retry_delay_hint_ms == 0

    def test_stale_version_human_not_needed(self):
        assert get_error("STALE_VERSION").human_likely_needed is False

    def test_stale_version_blocks_other_actions_false(self):
        assert get_error("STALE_VERSION").blocks_other_actions is False

    def test_stale_version_requires_context_refresh(self):
        assert get_error("STALE_VERSION").requires_context_refresh is True

    def test_stale_version_severity_is_warning(self):
        assert get_error("STALE_VERSION").severity == "warning"

    def test_stale_version_agent_should_recheck(self):
        assert get_error("STALE_VERSION").agent_should == "recheck"

    def test_lease_held_retryable(self):
        assert get_error("LEASE_HELD").retryable is True

    def test_lease_held_retry_delay_1500(self):
        assert get_error("LEASE_HELD").retry_delay_hint_ms == 1500

    def test_lease_held_blocks_other_actions(self):
        assert get_error("LEASE_HELD").blocks_other_actions is True

    def test_lease_held_requires_context_refresh(self):
        assert get_error("LEASE_HELD").requires_context_refresh is True

    def test_budget_exceeded_retryable(self):
        assert get_error("BUDGET_EXCEEDED").retryable is True

    def test_budget_exceeded_human_not_needed(self):
        assert get_error("BUDGET_EXCEEDED").human_likely_needed is False

    def test_budget_exceeded_blocks_other_actions_false(self):
        assert get_error("BUDGET_EXCEEDED").blocks_other_actions is False

    def test_budget_exceeded_requires_context_refresh_false(self):
        assert get_error("BUDGET_EXCEEDED").requires_context_refresh is False

    def test_policy_blocked_not_retryable(self):
        assert get_error("POLICY_BLOCKED").retryable is False

    def test_policy_blocked_human_needed(self):
        assert get_error("POLICY_BLOCKED").human_likely_needed is True

    def test_policy_blocked_blocks_other_actions(self):
        assert get_error("POLICY_BLOCKED").blocks_other_actions is True

    def test_policy_blocked_severity_elevated(self):
        assert get_error("POLICY_BLOCKED").severity == "elevated"

    def test_saga_poisoned_not_retryable(self):
        assert get_error("SAGA_POISONED").retryable is False

    def test_saga_poisoned_human_needed(self):
        assert get_error("SAGA_POISONED").human_likely_needed is True

    def test_saga_poisoned_blocks_other_actions(self):
        assert get_error("SAGA_POISONED").blocks_other_actions is True

    def test_saga_poisoned_requires_context_refresh(self):
        assert get_error("SAGA_POISONED").requires_context_refresh is True

    def test_saga_poisoned_severity_critical(self):
        assert get_error("SAGA_POISONED").severity == "critical"


class TestGetErrorHelper:
    def test_lookup_by_enum(self):
        meta = get_error(ErrorCode.STALE_VERSION)
        assert isinstance(meta, ErrorMetadata)
        assert meta.retryable is True

    def test_lookup_by_string(self):
        meta = get_error("STALE_VERSION")
        assert meta.agent_should == "recheck"

    def test_lookup_compensation_failed(self):
        meta = get_error("COMPENSATION_FAILED")
        assert meta.severity == "critical"
        assert meta.human_likely_needed is True

    def test_invalid_code_raises(self):
        with pytest.raises((KeyError, ValueError)):
            get_error("NOT_A_REAL_CODE")


class TestV04AlphaCodes:
    """Spot-checks for v0.4-alpha environment + fleet error code metadata."""

    def test_environment_unavailable_is_elevated_and_retryable(self):
        meta = get_error("ENVIRONMENT_UNAVAILABLE")
        assert meta.severity == "elevated"
        assert meta.retryable is True
        assert meta.retry_delay_hint_ms is not None

    def test_environment_unhealthy_requires_context_refresh(self):
        meta = get_error("ENVIRONMENT_UNHEALTHY")
        assert meta.severity == "warning"
        assert meta.requires_context_refresh is True

    def test_fleet_budget_exceeded_not_retryable(self):
        meta = get_error("FLEET_BUDGET_EXCEEDED")
        assert meta.retryable is False
        assert meta.retry_delay_hint_ms is None

    def test_fleet_concurrency_limit_is_retryable(self):
        meta = get_error("FLEET_CONCURRENCY_LIMIT")
        assert meta.retryable is True
        assert meta.blocks_other_actions is False

    def test_fleet_timeout_blocks_and_needs_human(self):
        meta = get_error("FLEET_TIMEOUT")
        assert meta.severity == "elevated"
        assert meta.blocks_other_actions is True
        assert meta.human_likely_needed is True
        assert meta.retryable is False

    def test_dispatch_unassignable_is_retryable_warning(self):
        meta = get_error("DISPATCH_UNASSIGNABLE")
        assert meta.severity == "warning"
        assert meta.retryable is True
        assert meta.blocks_other_actions is False

    def test_all_v04_codes_pass_severity_vocabulary(self):
        valid = {"informational", "warning", "elevated", "critical"}
        for name in V04_CODES:
            meta = get_error(name)
            assert meta.severity in valid, f"{name}: severity '{meta.severity}' invalid"

    def test_all_v04_retryable_codes_have_delay(self):
        for name in V04_ALPHA_CODES:
            meta = get_error(name)
            if meta.retryable:
                assert meta.retry_delay_hint_ms is not None, (
                    f"{name}: retryable but retry_delay_hint_ms is None"
                )


class TestV04BetaCodes:
    """Spot-checks for v0.4-beta entry-point and discovery error code metadata."""

    def test_action_not_discoverable_is_informational(self):
        meta = get_error("ACTION_NOT_DISCOVERABLE")
        assert meta.severity == "informational"
        assert meta.retryable is False
        assert meta.retry_delay_hint_ms is None

    def test_action_not_discoverable_does_not_block(self):
        meta = get_error("ACTION_NOT_DISCOVERABLE")
        assert meta.blocks_other_actions is False
        assert meta.human_likely_needed is False

    def test_entry_validation_failed_is_warning(self):
        meta = get_error("ENTRY_VALIDATION_FAILED")
        assert meta.severity == "warning"
        assert meta.retryable is False
        assert meta.retry_delay_hint_ms is None

    def test_entry_validation_failed_does_not_block(self):
        meta = get_error("ENTRY_VALIDATION_FAILED")
        assert meta.blocks_other_actions is False

    def test_all_v04_beta_codes_pass_severity_vocabulary(self):
        valid = {"informational", "warning", "elevated", "critical"}
        for name in V04_BETA_CODES:
            meta = get_error(name)
            assert meta.severity in valid, f"{name}: severity '{meta.severity}' invalid"


class TestV04RcCodes:
    """Spot-checks for v0.4-rc context-scope and review error code metadata."""

    def test_scope_conflict_is_retryable_warning(self):
        meta = get_error("SCOPE_CONFLICT")
        assert meta.severity == "warning"
        assert meta.retryable is True
        assert meta.retry_delay_hint_ms == 0
        assert meta.requires_context_refresh is True

    def test_scope_conflict_does_not_block(self):
        meta = get_error("SCOPE_CONFLICT")
        assert meta.blocks_other_actions is False

    def test_review_required_is_informational_and_blocks(self):
        meta = get_error("REVIEW_REQUIRED")
        assert meta.severity == "informational"
        assert meta.retryable is True
        assert meta.retry_delay_hint_ms == 30000
        assert meta.blocks_other_actions is True
        assert meta.human_likely_needed is True

    def test_review_rejected_is_elevated_and_not_retryable(self):
        meta = get_error("REVIEW_REJECTED")
        assert meta.severity == "elevated"
        assert meta.retryable is False
        assert meta.retry_delay_hint_ms is None
        assert meta.blocks_other_actions is True
        assert meta.human_likely_needed is True
        assert meta.requires_context_refresh is True

    def test_all_v04_rc_codes_pass_severity_vocabulary(self):
        valid = {"informational", "warning", "elevated", "critical"}
        for name in V04_RC_CODES:
            meta = get_error(name)
            assert meta.severity in valid, f"{name}: severity '{meta.severity}' invalid"
