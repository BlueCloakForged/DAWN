"""CONCORD v0.3/v0.4 — Error/conflict code registry with full metadata (38 codes).

PL-01: All 26 v0.3 codes present with all 7 metadata fields non-null.
PL-09: RETRY_RECOMMENDED added (P1 punch list item).
v0.4-alpha adds 6 fleet/environment codes (ENVIRONMENT_* and FLEET_*/DISPATCH_*).
v0.4-beta adds 2 entry-point/discovery codes.
v0.4-rc adds 3 context-scope/review codes.

Severity vocabulary (from Error and Conflict Code Catalog §1):
    informational | warning | elevated | critical
"""

from dataclasses import dataclass
from enum import Enum


class ErrorCode(str, Enum):
    # Conflict codes (16)
    STALE_VERSION = "STALE_VERSION"
    SESSION_STALE_VIEW = "SESSION_STALE_VIEW"
    LEASE_HELD = "LEASE_HELD"
    QUEUE_REQUIRED = "QUEUE_REQUIRED"
    QUEUE_AVAILABLE = "QUEUE_AVAILABLE"
    DUPLICATE_INTENT = "DUPLICATE_INTENT"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    CIRCUIT_OPEN = "CIRCUIT_OPEN"
    QUORUM_INCOMPLETE = "QUORUM_INCOMPLETE"
    DEPENDENCY_PENDING = "DEPENDENCY_PENDING"
    CAPACITY_EXHAUSTED = "CAPACITY_EXHAUSTED"
    NEGOTIATION_AVAILABLE = "NEGOTIATION_AVAILABLE"
    NEGOTIATION_REQUIRED = "NEGOTIATION_REQUIRED"
    ESCALATION_REQUIRED = "ESCALATION_REQUIRED"
    AUTHORITATIVE_RECHECK_REQUIRED = "AUTHORITATIVE_RECHECK_REQUIRED"
    # PL-09: distinct from STALE_VERSION (requires recheck, not blind retry)
    RETRY_RECOMMENDED = "RETRY_RECOMMENDED"

    # Error codes (10)
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    INVALID_FIELD_VALUE = "INVALID_FIELD_VALUE"
    READ_FRESHNESS_UNAVAILABLE = "READ_FRESHNESS_UNAVAILABLE"
    STALE_READ_WARNING = "STALE_READ_WARNING"
    RESOURCE_LOCKED = "RESOURCE_LOCKED"
    NOT_AUTHORIZED_FOR_AGENT_CLASS = "NOT_AUTHORIZED_FOR_AGENT_CLASS"
    OVERRIDE_DENIED = "OVERRIDE_DENIED"
    SAGA_TIMED_OUT = "SAGA_TIMED_OUT"
    SAGA_POISONED = "SAGA_POISONED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"

    # v0.4-alpha: environment + fleet codes (6)
    ENVIRONMENT_UNAVAILABLE = "ENVIRONMENT_UNAVAILABLE"
    ENVIRONMENT_UNHEALTHY = "ENVIRONMENT_UNHEALTHY"
    FLEET_BUDGET_EXCEEDED = "FLEET_BUDGET_EXCEEDED"
    FLEET_CONCURRENCY_LIMIT = "FLEET_CONCURRENCY_LIMIT"
    FLEET_TIMEOUT = "FLEET_TIMEOUT"
    DISPATCH_UNASSIGNABLE = "DISPATCH_UNASSIGNABLE"

    # v0.4-beta: entry-point + discovery codes (2)
    ACTION_NOT_DISCOVERABLE = "ACTION_NOT_DISCOVERABLE"
    ENTRY_VALIDATION_FAILED = "ENTRY_VALIDATION_FAILED"

    # v0.4-rc: context-scope + review codes (3)
    SCOPE_CONFLICT = "SCOPE_CONFLICT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    REVIEW_REJECTED = "REVIEW_REJECTED"


@dataclass(frozen=True)
class ErrorMetadata:
    """Full metadata for a CONCORD error/conflict code.

    Fields:
        severity: "informational" | "warning" | "elevated" | "critical"
        retryable: Whether the agent may retry automatically.
        retry_delay_hint_ms: Suggested wait before retry (None = not retryable).
        agent_should: Imperative instruction for the agent on encountering this code.
        human_likely_needed: True when a human operator is typically required.
        blocks_other_actions: True when this code prevents sibling actions.
        requires_context_refresh: True when OperationContext must be re-fetched.
    """

    severity: str
    retryable: bool
    retry_delay_hint_ms: int | None
    agent_should: str
    human_likely_needed: bool
    blocks_other_actions: bool
    requires_context_refresh: bool


ERROR_REGISTRY: dict[ErrorCode, ErrorMetadata] = {
    # ── Conflict codes ────────────────────────────────────────────────────────
    ErrorCode.STALE_VERSION: ErrorMetadata(
        severity="warning",
        retryable=True,
        retry_delay_hint_ms=0,
        agent_should="recheck",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=True,
    ),
    ErrorCode.SESSION_STALE_VIEW: ErrorMetadata(
        severity="warning",
        retryable=True,
        retry_delay_hint_ms=0,
        agent_should="refresh_context_then_retry",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=True,
    ),
    ErrorCode.LEASE_HELD: ErrorMetadata(
        severity="warning",
        retryable=True,
        retry_delay_hint_ms=1500,
        agent_should="wait_for_lease_release_or_queue",
        human_likely_needed=False,
        blocks_other_actions=True,
        requires_context_refresh=True,
    ),
    ErrorCode.QUEUE_REQUIRED: ErrorMetadata(
        severity="informational",
        retryable=True,
        retry_delay_hint_ms=1000,
        agent_should="enter_queue_and_wait",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=False,
    ),
    ErrorCode.QUEUE_AVAILABLE: ErrorMetadata(
        severity="informational",
        retryable=True,
        retry_delay_hint_ms=0,
        agent_should="optionally_join_queue",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=False,
    ),
    ErrorCode.DUPLICATE_INTENT: ErrorMetadata(
        severity="informational",
        retryable=False,
        retry_delay_hint_ms=None,
        agent_should="deduplicate_or_await_existing_intent",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=False,
    ),
    ErrorCode.POLICY_BLOCKED: ErrorMetadata(
        severity="elevated",
        retryable=False,
        retry_delay_hint_ms=None,
        agent_should="escalate_or_abort",
        human_likely_needed=True,
        blocks_other_actions=True,
        requires_context_refresh=False,
    ),
    ErrorCode.BUDGET_EXCEEDED: ErrorMetadata(
        severity="warning",
        retryable=True,
        retry_delay_hint_ms=60000,
        agent_should="wait_for_budget_window_reset",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=False,
    ),
    ErrorCode.CIRCUIT_OPEN: ErrorMetadata(
        severity="elevated",
        retryable=True,
        retry_delay_hint_ms=30000,
        agent_should="wait_for_circuit_recovery",
        human_likely_needed=False,
        blocks_other_actions=True,
        requires_context_refresh=True,
    ),
    ErrorCode.QUORUM_INCOMPLETE: ErrorMetadata(
        severity="informational",
        retryable=True,
        retry_delay_hint_ms=10000,
        agent_should="await_quorum_tokens_then_retry",
        human_likely_needed=False,
        blocks_other_actions=True,
        requires_context_refresh=False,
    ),
    ErrorCode.DEPENDENCY_PENDING: ErrorMetadata(
        severity="informational",
        retryable=True,
        retry_delay_hint_ms=5000,
        agent_should="wait_for_dependency_to_commit",
        human_likely_needed=False,
        blocks_other_actions=True,
        requires_context_refresh=False,
    ),
    ErrorCode.CAPACITY_EXHAUSTED: ErrorMetadata(
        severity="warning",
        retryable=True,
        retry_delay_hint_ms=15000,
        agent_should="queue_or_defer_until_capacity_available",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=False,
    ),
    ErrorCode.NEGOTIATION_AVAILABLE: ErrorMetadata(
        severity="informational",
        retryable=True,
        retry_delay_hint_ms=0,
        agent_should="initiate_negotiation_protocol",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=False,
    ),
    ErrorCode.NEGOTIATION_REQUIRED: ErrorMetadata(
        severity="elevated",
        retryable=True,
        retry_delay_hint_ms=0,
        agent_should="must_complete_negotiation_before_proceeding",
        human_likely_needed=False,
        blocks_other_actions=True,
        requires_context_refresh=False,
    ),
    ErrorCode.ESCALATION_REQUIRED: ErrorMetadata(
        severity="elevated",
        retryable=False,
        retry_delay_hint_ms=None,
        agent_should="escalate_to_higher_trust_tier_or_human",
        human_likely_needed=True,
        blocks_other_actions=True,
        requires_context_refresh=False,
    ),
    ErrorCode.AUTHORITATIVE_RECHECK_REQUIRED: ErrorMetadata(
        severity="warning",
        retryable=True,
        retry_delay_hint_ms=0,
        agent_should="fetch_authoritative_state_before_retry",
        human_likely_needed=False,
        blocks_other_actions=True,
        requires_context_refresh=True,
    ),
    ErrorCode.RETRY_RECOMMENDED: ErrorMetadata(
        severity="informational",
        retryable=True,
        retry_delay_hint_ms=1000,
        agent_should="retry",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=False,
    ),
    # ── Error codes ───────────────────────────────────────────────────────────
    ErrorCode.MISSING_REQUIRED_FIELD: ErrorMetadata(
        severity="warning",
        retryable=False,
        retry_delay_hint_ms=None,
        agent_should="fix_contract_or_payload_then_resubmit",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=False,
    ),
    ErrorCode.INVALID_FIELD_VALUE: ErrorMetadata(
        severity="warning",
        retryable=False,
        retry_delay_hint_ms=None,
        agent_should="correct_field_value_then_resubmit",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=False,
    ),
    ErrorCode.READ_FRESHNESS_UNAVAILABLE: ErrorMetadata(
        severity="warning",
        retryable=True,
        retry_delay_hint_ms=2000,
        agent_should="retry_with_relaxed_freshness_or_wait",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=True,
    ),
    ErrorCode.STALE_READ_WARNING: ErrorMetadata(
        severity="informational",
        retryable=True,
        retry_delay_hint_ms=0,
        agent_should="acknowledge_staleness_or_refresh_before_mutation",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=True,
    ),
    ErrorCode.RESOURCE_LOCKED: ErrorMetadata(
        severity="warning",
        retryable=True,
        retry_delay_hint_ms=5000,
        agent_should="wait_for_lock_release_then_retry",
        human_likely_needed=False,
        blocks_other_actions=True,
        requires_context_refresh=False,
    ),
    ErrorCode.NOT_AUTHORIZED_FOR_AGENT_CLASS: ErrorMetadata(
        severity="elevated",
        retryable=False,
        retry_delay_hint_ms=None,
        agent_should="abort_and_report_capability_gap",
        human_likely_needed=True,
        blocks_other_actions=True,
        requires_context_refresh=False,
    ),
    ErrorCode.OVERRIDE_DENIED: ErrorMetadata(
        severity="elevated",
        retryable=False,
        retry_delay_hint_ms=None,
        agent_should="abort_override_attempt_and_escalate",
        human_likely_needed=True,
        blocks_other_actions=True,
        requires_context_refresh=False,
    ),
    ErrorCode.SAGA_TIMED_OUT: ErrorMetadata(
        severity="elevated",
        retryable=False,
        retry_delay_hint_ms=None,
        agent_should="trigger_compensation_and_report",
        human_likely_needed=True,
        blocks_other_actions=True,
        requires_context_refresh=True,
    ),
    ErrorCode.SAGA_POISONED: ErrorMetadata(
        severity="critical",
        retryable=False,
        retry_delay_hint_ms=None,
        agent_should="halt_saga_and_escalate_immediately",
        human_likely_needed=True,
        blocks_other_actions=True,
        requires_context_refresh=True,
    ),
    ErrorCode.COMPENSATION_FAILED: ErrorMetadata(
        severity="critical",
        retryable=False,
        retry_delay_hint_ms=None,
        agent_should="escalate_to_human_for_manual_recovery",
        human_likely_needed=True,
        blocks_other_actions=True,
        requires_context_refresh=True,
    ),
    # ── v0.4-alpha: environment + fleet codes ────────────────────────────────
    ErrorCode.ENVIRONMENT_UNAVAILABLE: ErrorMetadata(
        severity="elevated",
        retryable=True,
        retry_delay_hint_ms=10000,
        agent_should="wait_for_environment_pool_availability",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=False,
    ),
    ErrorCode.ENVIRONMENT_UNHEALTHY: ErrorMetadata(
        severity="warning",
        retryable=True,
        retry_delay_hint_ms=5000,
        agent_should="escalate_and_request_environment_replacement",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=True,
    ),
    ErrorCode.FLEET_BUDGET_EXCEEDED: ErrorMetadata(
        severity="warning",
        retryable=False,
        retry_delay_hint_ms=None,
        agent_should="wait_for_fleet_budget_window_reset",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=False,
    ),
    ErrorCode.FLEET_CONCURRENCY_LIMIT: ErrorMetadata(
        severity="warning",
        retryable=True,
        retry_delay_hint_ms=5000,
        agent_should="queue_dispatch_and_wait_for_slot",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=False,
    ),
    ErrorCode.FLEET_TIMEOUT: ErrorMetadata(
        severity="elevated",
        retryable=False,
        retry_delay_hint_ms=None,
        agent_should="abort_and_trigger_compensation_for_active_members",
        human_likely_needed=True,
        blocks_other_actions=True,
        requires_context_refresh=False,
    ),
    ErrorCode.DISPATCH_UNASSIGNABLE: ErrorMetadata(
        severity="warning",
        retryable=True,
        retry_delay_hint_ms=15000,
        agent_should="escalate_and_await_available_agent_or_environment",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=False,
    ),
    # ── v0.4-beta: entry-point + discovery codes ──────────────────────────────
    ErrorCode.ACTION_NOT_DISCOVERABLE: ErrorMetadata(
        severity="informational",
        retryable=False,
        retry_delay_hint_ms=None,
        agent_should="escalate_or_refine_task_context_and_retry_discovery",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=False,
    ),
    ErrorCode.ENTRY_VALIDATION_FAILED: ErrorMetadata(
        severity="warning",
        retryable=False,
        retry_delay_hint_ms=None,
        agent_should="abort_and_report_missing_required_fields_to_caller",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=False,
    ),
    # ── v0.4-rc: context-scope + review codes ────────────────────────────────
    ErrorCode.SCOPE_CONFLICT: ErrorMetadata(
        severity="warning",
        retryable=True,
        retry_delay_hint_ms=0,
        agent_should="recheck_after_scope_conflict_resolution",
        human_likely_needed=False,
        blocks_other_actions=False,
        requires_context_refresh=True,
    ),
    ErrorCode.REVIEW_REQUIRED: ErrorMetadata(
        severity="informational",
        retryable=True,
        retry_delay_hint_ms=30000,
        agent_should="wait_for_review_bundle_approval",
        human_likely_needed=True,
        blocks_other_actions=True,
        requires_context_refresh=False,
    ),
    ErrorCode.REVIEW_REJECTED: ErrorMetadata(
        severity="elevated",
        retryable=False,
        retry_delay_hint_ms=None,
        agent_should="recheck_review_feedback_and_revise_or_escalate",
        human_likely_needed=True,
        blocks_other_actions=True,
        requires_context_refresh=True,
    ),
}


def get_error(code: "ErrorCode | str") -> ErrorMetadata:
    """Look up metadata for an error/conflict code.

    Args:
        code: An ErrorCode enum member or its string name (e.g. "STALE_VERSION").

    Returns:
        The corresponding ErrorMetadata.

    Raises:
        KeyError: If the code is not found in the registry.
    """
    if isinstance(code, str):
        code = ErrorCode(code)
    return ERROR_REGISTRY[code]
