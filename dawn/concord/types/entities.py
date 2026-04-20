"""CONCORD v0.3/v0.4 — Core entity dataclasses.

PL-05: BlockedReason is a structured object in an array (not a raw string array).
OperationContext.authoritative_for_mutation is always False — enforced at class level.

Fields aligned with:
- Core Specification §3 (entity definitions)
- Runtime Contract Schemas §5–7 (BudgetProfile, BudgetLedger, Lease, Token, CoordinationTelemetry)
- v0.4-alpha: ExecutionEnvironment, TaskFleet, DispatchRequest
- v0.4-beta: EntryPoint; Intent/DispatchRequest extended with entry_point_id/channel
- v0.4-rc: ContextScope, ScopedRule, ReviewBundle; OperationContext/Receipt extended
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from dawn.concord.types.enums import (
    AuthenticationMethod,
    BundleStatus,
    CircuitState,
    CompensationStrategy,
    ConsistencyProfile,
    CooldownPolicy,
    DispatchPriority,
    DispatchStatus,
    EntryChannel,
    EnvironmentClass,
    EnvironmentStatus,
    FleetCompletionPolicy,
    FleetStatus,
    FreshnessStatus,
    IntentStatus,
    IsolationLevel,
    IsolationRequirement,
    LeaseStatus,
    LeaseType,
    ProvisioningStatus,
    RiskLevel,
    SagaTimeoutPolicy,
    ScopedRuleAppliesTo,
    ScopedRuleSeverity,
    ScopedRuleType,
    ScopeType,
    SessionMode,
    SessionStatus,
    TokenStatus,
    TokenType,
    TripRecoveryPolicy,
    TrustTier,
)


# ── Sub-objects ───────────────────────────────────────────────────────────────


@dataclass
class BlockedReason:
    """PL-05: Structured blocked reason entry (appears in arrays).

    Attributes:
        reason_code: An ErrorCode name explaining why the action is blocked.
        unblock_condition: Human-readable description of what must change.
        estimated_wait_ms: Advisory wait time in milliseconds, or None if unknown.
    """

    reason_code: str
    unblock_condition: str
    estimated_wait_ms: Optional[int] = None


@dataclass
class CircuitBreakerThresholds:
    """PL-04: Thresholds that govern when a circuit breaker trips.

    Attributes:
        stale_version_failure_rate: Fraction of requests (0–1) returning
            STALE_VERSION before the circuit trips.
        budget_exceeded_rate: Fraction returning BUDGET_EXCEEDED.
        error_rate: General error fraction (all non-conflict errors).
        evaluation_window_ms: Rolling window over which rates are measured.
        trip_recovery_policy: What happens once the circuit has tripped.
    """

    stale_version_failure_rate: float
    budget_exceeded_rate: float
    error_rate: float
    evaluation_window_ms: int
    trip_recovery_policy: TripRecoveryPolicy


# ── Core entities ─────────────────────────────────────────────────────────────


@dataclass
class Session:
    """An agent session — the unit of trust and budget accounting.

    Spec §3.3 minimum required: session_id, agent_id, task_id, started_at,
    expires_at, mode, status.
    """

    id: str
    agent_id: str
    agent_class_id: str
    trust_tier: TrustTier
    mode: SessionMode
    status: SessionStatus
    watermark: int
    started_at: datetime
    budget_profile_id: str
    task_id: Optional[str] = None
    expires_at: Optional[datetime] = None
    # v0.4-alpha: fleet and environment binding
    environment_id: Optional[str] = None
    fleet_id: Optional[str] = None


@dataclass
class Intent:
    """A declared intention by an agent to perform an action on a resource.

    Spec §3.3 minimum required: intent_id, session_id, resource_type,
    resource_id, action_name, idempotency_key, intent_status.
    """

    id: str
    session_id: str
    resource_type: str
    resource_id: str
    action_name: str
    idempotency_key: str
    status: IntentStatus
    consistency_profile: ConsistencyProfile
    risk_level: RiskLevel
    participates_in_saga: bool
    created_at: datetime
    saga_id: Optional[str] = None
    admitted_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    # v0.4-beta: entry-point traceability
    entry_point_id: Optional[str] = None
    channel: Optional[EntryChannel] = None


@dataclass
class Resource:
    """A shared resource managed by CONCORD.

    business_state and coordination_state are kept separate per spec §3.3.
    Business state MUST NOT encode lease ownership, queue position, or budget state.
    """

    id: str
    resource_type: str
    business_state: dict[str, Any]
    coordination_state: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass
class Lease:
    """An exclusive coordination lock held by a session over a resource."""

    id: str
    resource_id: str
    session_id: str
    lease_type: LeaseType
    expires_at: datetime
    granted_at: datetime
    status: LeaseStatus
    renewal_count: int = 0
    purpose: Optional[str] = None


@dataclass
class Token:
    """A finite coordination token (capacity, quorum, gate) over a resource.

    Tokens differ from leases in that multiple sessions may hold them up to
    the declared capacity (quorum / capacity tokens).
    """

    id: str
    token_type: TokenType
    resource_id: str
    capacity: int
    available_count: int
    holders: list[str]
    issuance_rule: str
    status: TokenStatus
    expires_at: Optional[datetime] = None


@dataclass
class Receipt:
    """An immutable record of a completed (or attempted) mutation.

    Spec §3.3: must include operation_id, intent_id, previous_state,
    next_state, result_status, duration_ms.
    """

    operation_id: str
    intent_id: str
    previous_state: dict[str, Any]
    next_state: dict[str, Any]
    version_before: int
    version_after: int
    result_status: str
    duration_ms: int
    policy_decision: str
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    # v0.4-alpha/beta/rc: traceability fields
    environment_id: Optional[str] = None
    entry_point_id: Optional[str] = None
    scopes_applied: list[str] = field(default_factory=list)  # ContextScope scope_ids active during operation


@dataclass
class SagaRun:
    """A multi-step coordinated saga execution.

    Spec §3.3: must include saga_id, root_intent_id, status, timeout_at,
    timeout_policy, compensation_status.
    """

    id: str
    root_intent_id: str
    steps: list[str]
    current_step: int
    timeout_policy: SagaTimeoutPolicy
    timeout_deadline_ms: int
    compensation_strategy: CompensationStrategy
    max_compensation_attempts: int
    attempt_count: int
    status: IntentStatus
    # Saga timeout mode extra fields (optional based on policy)
    step_timeout_ms: Optional[int] = None
    heartbeat_interval_ms: Optional[int] = None
    external_dependency_timeout_ms: Optional[int] = None
    # When the saga began executing (required for FIXED timeout policy)
    started_at: Optional[datetime] = None


@dataclass
class AgentClass:
    """A class of agents sharing a trust tier and capability set.

    Spec §3.1: trust tier anchor + composed capability sets.
    override_rules may only narrow rights (never expand without PolicyExpansionGrant).
    """

    id: str
    name: str
    trust_tier: TrustTier
    budget_profile_id: str
    capability_set_ids: list[str] = field(default_factory=list)
    composed_from: list[str] = field(default_factory=list)
    prod_allowed: bool = False
    requires_human_gate_for: list[str] = field(default_factory=list)
    override_rules: dict[str, Any] = field(default_factory=dict)


@dataclass
class CapabilitySet:
    """A composable permission bundle for an AgentClass.

    Spec §3.2: grants action families, scopes denials by resource type,
    limits lease classes and max authority mode.
    """

    id: str
    allowed_action_families: list[str] = field(default_factory=list)
    allowed_resource_types: list[str] = field(default_factory=list)
    restricted_resource_types: list[str] = field(default_factory=list)
    restricted_resource_tags: list[str] = field(default_factory=list)
    lease_permissions: list[str] = field(default_factory=list)
    max_authority_mode: Optional[SessionMode] = None
    default_budget_profile_id: Optional[str] = None
    exclusions: list[str] = field(default_factory=list)
    override_rules: list[str] = field(default_factory=list)


@dataclass
class BudgetProfile:
    """Rate limits and circuit-breaker configuration for an agent class.

    Spec §5.1: gateway burst limit + intent-layer quotas + circuit breaker.
    """

    id: str
    max_actions_per_minute: int
    max_mutating_actions_per_hour: int
    max_high_risk_per_day: int
    max_cost_units_per_session: float
    burst_limit: int
    circuit_breaker_thresholds: CircuitBreakerThresholds
    cooldown_policy: CooldownPolicy
    max_parallel_leases: int = 1
    max_queue_depth: Optional[int] = None
    per_resource_class_limits: Optional[dict[str, Any]] = None
    per_action_family_limits: Optional[dict[str, Any]] = None
    # v0.4-alpha: fleet environment ceiling
    max_parallel_environments: Optional[int] = None


@dataclass
class BudgetLedger:
    """Snapshot of budget consumption for a session within a window.

    Spec §5.2: records consumed counts, circuit state, and cooldown deadline.
    """

    ledger_id: str
    session_id: str
    agent_class_id: str
    budget_profile_id: str
    window_start: datetime
    window_end: datetime
    actions_consumed: int
    mutating_actions_consumed: int
    high_risk_actions_consumed: int
    cost_units_consumed: float
    parallel_leases_in_use: int
    queue_slots_in_use: int
    circuit_state: CircuitState
    cooldown_until: Optional[datetime] = None
    # v0.4-alpha: fleet-level accounting
    fleet_id: Optional[str] = None


@dataclass
class OperationContext:
    """Advisory context assembled for an agent before it acts.

    CONCORD Core Law: authoritative_for_mutation is ALWAYS False.
    Agents MUST NOT treat this context as authoritative for mutation decisions.
    Every mutating action must still pass full intent admission checks.

    Spec §4 required fields + worked example (Runtime Contract Schemas §8.4).
    """

    resource_id: str
    resource: Resource
    allowed_actions: list[str]
    blocked_actions: list[str]
    blocked_reasons: list[BlockedReason]
    active_leases: list[Lease]
    pending_intents: list[str]
    budget_remaining: dict[str, Any]
    freshness_status: FreshnessStatus
    context_assembled_at: datetime
    context_ttl_ms: int
    # Optional / profile-specific fields
    queue_position: Optional[int] = None
    recommended_next_action: Optional[str] = None
    safe_parallel_actions: list[str] = field(default_factory=list)
    requires_authoritative_recheck: bool = False
    consistency_profile: Optional[ConsistencyProfile] = None
    projection_lag_ms: Optional[int] = None
    trust_constraints: list[str] = field(default_factory=list)
    # v0.4-rc: matched ContextScope references injected into this context
    active_scopes: list[str] = field(default_factory=list)

    # CONCORD core law — always False, no exceptions
    authoritative_for_mutation: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        # Enforce the invariant regardless of any attempted assignment
        object.__setattr__(self, "authoritative_for_mutation", False)


@dataclass
class CoordinationTelemetry:
    """Portable runtime metrics surface for a CONCORD deployment.

    Spec §7 (Runtime Contract Schemas): required fields form the baseline
    dashboard and scanner input.
    """

    telemetry_window_start: datetime
    telemetry_window_end: datetime
    lease_contention_rate: float
    average_queue_wait_ms: float
    queue_abandonment_rate: float
    stale_write_rejection_rate: float
    budget_throttle_rate: float
    circuit_breaker_trip_count: int
    compensation_invocation_rate: float
    retry_distribution: dict[str, Any]
    resource_type: Optional[str] = None
    arbitration_frequency: Optional[float] = None
    resource_hotspots: list[dict[str, Any]] = field(default_factory=list)
    # v0.4-alpha: environment and fleet metrics (populated by v0.4-alpha runtime)
    environment_pool_utilization: Optional[float] = None
    average_provision_time_ms: Optional[float] = None
    environment_recycle_rate: Optional[float] = None
    fleet_utilization_rate: Optional[float] = None
    average_dispatch_wait_ms: Optional[float] = None
    fleet_completion_rate: Optional[float] = None


# ── v0.4-alpha: Execution environment + fleet entities ────────────────────────


@dataclass
class ExecutionEnvironment:
    """An isolated execution environment bound to an agent session.

    Normative rules (v0.4 §Gap-1):
    - Sessions with mode=supervised MUST be bound to isolation_level >= container.
    - Assignment MUST be recorded on the Session and included in all Receipts.
    - Teardown MUST NOT occur while the bound session has intents in
      admitted or executing status.
    - Preload manifests SHOULD be versioned and content-addressed.
    """

    environment_id: str
    environment_class: EnvironmentClass
    provisioning_status: ProvisioningStatus
    isolation_level: IsolationLevel
    resource_spec: dict[str, Any]
    preload_manifest: list[str]
    created_at: datetime
    max_lifetime_ms: int
    heartbeat_interval_ms: int
    status: EnvironmentStatus
    assigned_session_id: Optional[str] = None
    ready_at: Optional[datetime] = None
    assigned_at: Optional[datetime] = None


@dataclass
class TaskFleet:
    """A group of sessions pursuing related or independent goals under shared governance.

    Normative rules (v0.4 §Gap-2):
    - max_concurrent ceiling MUST be enforced; overflow enters DispatchRequest.QUEUED.
    - All member sessions draw from the fleet's BudgetLedger (fleet_id set).
    - When completion_policy=ALL_MUST_SUCCEED, any member error/abort triggers fleet eval.
    - timeout_at MUST override individual session timeouts.
    """

    fleet_id: str
    owner_session_id: str
    agent_class_id: str
    max_concurrent: int
    member_sessions: list[str]
    fleet_status: FleetStatus
    budget_profile_id: str
    isolation_requirement: IsolationRequirement
    completion_policy: FleetCompletionPolicy
    created_at: datetime
    timeout_at: datetime


@dataclass
class DispatchRequest:
    """A unit of work assigned to an agent within a TaskFleet.

    Normative rules (v0.4 §Gap-2):
    - MUST carry idempotency_key.
    - MUST carry enough structured context for the agent to begin without
      interactive clarification (the outloop contract).
    - Overflow beyond fleet max_concurrent → dispatch_status=QUEUED.
    """

    dispatch_id: str
    fleet_id: str
    task_description: dict[str, Any]
    priority: DispatchPriority
    max_attempts: int
    attempt_count: int
    idempotency_key: str
    dispatch_status: DispatchStatus
    assigned_session_id: Optional[str] = None
    assigned_environment_id: Optional[str] = None
    result_ref: Optional[str] = None
    entry_point_id: Optional[str] = None
    channel: Optional[EntryChannel] = None


# ── v0.4-beta: Entry-point entity ─────────────────────────────────────────────


@dataclass
class EntryPoint:
    """A registered surface through which work enters the CONCORD system.

    Normative rules (v0.4 §Gap-4):
    - Adapters wired to this entry point MUST validate required_fields before
      constructing Intent or DispatchRequest output.
    - Adapters MUST attach entry_point_id and channel to all output.
    - Adapters MUST NOT bypass AgentClass or BudgetProfile checks.
    - Adapters MAY enrich output with defaults from default_agent_class_id and
      default_fleet_policy.
    """

    entry_point_id: str
    channel: EntryChannel
    display_name: str
    admission_adapter_ref: str           # identifier of the wired AdmissionAdapter
    required_fields: list[str]           # fields the channel must supply
    authentication_method: AuthenticationMethod
    audit_channel: bool
    default_agent_class_id: Optional[str] = None
    default_fleet_policy: Optional[dict[str, Any]] = None
    rate_limit_profile_id: Optional[str] = None


# ── v0.4-rc: Context-scope + review entities ─────────────────────────────────


@dataclass
class ScopedRule:
    """A single behavioral rule activated when its parent ContextScope matches.

    Attributes:
        rule_id: Unique identifier within the owning ContextScope.
        rule_type: Category of rule (convention, constraint, preference, etc.).
        content: Rule text, human and machine readable.
        applies_to: Which participant this rule targets.
        severity: How strongly the rule must be followed.
        source_ref: Optional traceability link to originating document or decision.
    """

    rule_id: str
    rule_type: ScopedRuleType
    content: str
    applies_to: ScopedRuleAppliesTo
    severity: ScopedRuleSeverity
    source_ref: Optional[str] = None


@dataclass
class ContextScope:
    """A conditional rule set activated when its match_pattern applies to the current context.

    Normative rules (v0.4 §Gap-5):
    - When an agent requests OperationContext, the runtime MUST evaluate active
      ContextScopes against the resource's type, domain, path, and tags.
    - Matching scopes are merged by priority (higher priority wins on conflicts).
    - Agents MUST NOT receive scopes that don't match their current operational
      context (prevents context bloat).
    - ContextScope definitions SHOULD be versionable and auditable.
    """

    scope_id: str
    scope_type: ScopeType
    match_pattern: str                   # glob, regex, or exact match per scope_type
    priority: int                        # ascending; higher number wins conflicts
    rules: list[ScopedRule]
    context_additions: list[str]         # context fragments to inject when active
    context_exclusions: list[str]        # context fragments to suppress when active
    active: bool
    inherits_from: Optional[str] = None  # parent scope_id for hierarchical composition


@dataclass
class ReviewBundle:
    """Aggregated review artifact for a completed session or dispatch.

    Normative rules (v0.4 §Gap-6):
    - SHOULD be assembled when a session/dispatch reaches terminal state with
      mutating actions.
    - summary MUST be written for domain-context readers (not CONCORD internals).
    - MUST include all Receipts so reviewers can trace every action taken.
    - Approval MAY be wired as a guard predicate on downstream actions (e.g.,
      deploy requires ReviewBundle.bundle_status = approved).
    """

    bundle_id: str
    session_id: str
    created_at: datetime
    bundle_status: BundleStatus
    summary: dict[str, Any]             # human-readable; domain-context language
    receipts: list[str]                 # operation_ids of all Receipts
    state_changes: list[dict[str, Any]] # business state transitions performed
    resources_modified: list[str]       # resource IDs and types touched
    validation_results: dict[str, Any]  # aggregated scoring/validation output
    risk_assessment: dict[str, Any]     # highest risk, escalations, budget consumed
    artifacts: dict[str, Any]          # domain-specific artifact references
    fleet_id: Optional[str] = None
    dispatch_id: Optional[str] = None
    diff_ref: Optional[str] = None
    reviewer_session_id: Optional[str] = None
    review_decision: Optional[BundleStatus] = None
    review_notes: Optional[str] = None
    review_completed_at: Optional[datetime] = None
